import os
import math
import base64
import io
import json
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, UnidentifiedImageError
import webview


# =============================================================================
# SpriteGrid Splitter — experimental PyWebView version
# Core processing is based on the tested 1.2 Auto / grid-test version.
# =============================================================================

SUPPORTED_EXTENSIONS = (".png", ".webp")
ALPHA_THRESHOLD = 16
TRIM_MARGIN = 3


def get_best_grid(total_frames):
    if total_frames <= 0:
        return 1, 1

    sqrt_val = math.isqrt(total_frames)

    for c in range(sqrt_val, 0, -1):
        if total_frames % c == 0:
            r = total_frames // c
            cols, rows = max(c, r), min(c, r)
            if cols / float(rows) <= 2.5:
                return cols, rows

    cols = math.ceil(math.sqrt(total_frames))
    rows = math.ceil(total_frames / float(cols))
    return cols, rows


def get_frame_bounds(full_w, total_frames, index):
    x0 = int(round(index * full_w / float(total_frames)))
    x1 = int(round((index + 1) * full_w / float(total_frames)))
    return x0, x1


def validate_frame_count(full_w, total_frames):
    if total_frames <= 0:
        return False
    return full_w / float(total_frames) >= 1.0


def _projection(signal_size, alpha):
    return [
        float(v)
        for v in alpha.resize(
            (signal_size, 1), Image.Resampling.BOX
        ).getdata()
    ]


def _correlation_at_shift(signal, shift, max_samples=1200):
    n = len(signal)
    if shift <= 0 or shift >= n:
        return 0.0

    span = n - shift
    if span < 2:
        return 0.0

    step = max(1, span // max_samples)
    a = [signal[i] for i in range(0, span, step)]
    b = [signal[i + shift] for i in range(0, span, step)]

    if len(a) < 2:
        return 0.0

    ma = sum(a) / len(a)
    mb = sum(b) / len(b)

    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a)
    db = sum((y - mb) ** 2 for y in b)

    if da <= 0 or db <= 0:
        return 0.0

    return num / math.sqrt(da * db)


def _find_period(signal, min_period=24, max_frames=256):
    n = len(signal)
    if n < min_period * 2:
        return None, 0.0

    best_period = None
    best_corr = 0.0

    for period in range(min_period, n // 2 + 1):
        approx_frames = n / float(period)

        if approx_frames < 2 or approx_frames > max_frames:
            continue

        corr = _correlation_at_shift(signal, period)

        if corr > best_corr:
            best_corr = corr
            best_period = period

    return best_period, best_corr


def _grid_confidence(size, period, correlation):
    if not period or correlation <= 0:
        return 0.0

    count = round(size / float(period))

    if count < 2:
        return 0.0

    fitted_period = size / float(count)
    relative_error = abs(fitted_period - period) / fitted_period
    fit = max(0.0, 1.0 - relative_error * 8.0)

    return max(
        0.0,
        min(1.0, 0.75 * correlation + 0.25 * fit)
    )


def _estimate_content_regions(img):
    alpha = img.getchannel("A")

    scale = min(
        1.0,
        256.0 / img.width,
        64.0 / img.height
    )

    sw = max(1, int(round(img.width * scale)))
    sh = max(1, int(round(img.height * scale)))

    small = alpha.resize((sw, sh), Image.Resampling.BOX)
    data = list(small.getdata())

    mask = [v > ALPHA_THRESHOLD for v in data]
    visited = [False] * len(mask)
    regions = []

    for sy in range(sh):
        for sx in range(sw):
            idx = sy * sw + sx

            if visited[idx] or not mask[idx]:
                continue

            stack = [idx]
            visited[idx] = True
            pixels = []

            while stack:
                cur = stack.pop()
                pixels.append(cur)

                cy, cx = divmod(cur, sw)

                for dy, dx in (
                    (1, 0), (-1, 0), (0, 1), (0, -1)
                ):
                    ny, nx = cy + dy, cx + dx

                    if 0 <= ny < sh and 0 <= nx < sw:
                        ni = ny * sw + nx

                        if not visited[ni] and mask[ni]:
                            visited[ni] = True
                            stack.append(ni)

            if len(pixels) >= 3:
                xs = [p % sw for p in pixels]
                ys = [p // sw for p in pixels]

                regions.append({
                    "area": len(pixels),
                    "cx": sum(xs) / len(xs) / scale,
                    "cy": sum(ys) / len(ys) / scale,
                })

    return regions


def _region_count_confidence(img, regions):
    w, _ = img.size
    count = len(regions)

    if count < 2 or count > 128:
        return 0.0

    centers = sorted(r["cx"] for r in regions)

    if len(centers) < 3:
        return 0.0

    gaps = [
        b - a
        for a, b in zip(centers, centers[1:])
        if b > a
    ]

    if not gaps:
        return 0.0

    median_gap = sorted(gaps)[len(gaps) // 2]

    if median_gap <= 0:
        return 0.0

    expected_gap = w / float(count)
    ratio = median_gap / expected_gap

    spacing_fit = max(
        0.0,
        1.0 - min(1.0, abs(ratio - 1.0) / 0.20)
    )

    areas = sorted(r["area"] for r in regions)
    median_area = areas[len(areas) // 2]

    substantial = sum(
        1 for a in areas
        if a >= max(3, median_area * 0.25)
    )

    size_fit = substantial / float(count)

    return max(
        0.0,
        min(1.0, 0.70 * size_fit + 0.30 * spacing_fit)
    )


def detect_frame_count(img):
    w, h = img.size

    if w < 64 or h < 1:
        return None, 0.0

    regions = _estimate_content_regions(img)
    region_conf = _region_count_confidence(img, regions)

    if 2 <= len(regions) <= 128 and region_conf >= 0.68:
        return len(regions), region_conf

    signal = _projection(w, img.getchannel("A"))

    period, correlation = _find_period(
        signal,
        min_period=max(24, h // 8)
    )

    if period is None:
        return None, 0.0

    detected = round(w / float(period))

    if detected < 2 or detected > 256:
        return None, 0.0

    confidence = _grid_confidence(
        w, period, correlation
    )

    if confidence < 0.68:
        return None, confidence

    return detected, confidence


def analyze_frame_regions(img, total_frames):
    if total_frames <= 0:
        return False, 0

    regions = _estimate_content_regions(img)
    region_count = len(regions)

    return (
        region_count / float(total_frames) >= 1.5,
        region_count
    )


def process_image(
    img,
    save_path,
    total_frames,
    cols=0,
    trim_alpha=True,
    padding=0,
):
    img = img.convert("RGBA")
    full_w, full_h = img.size

    if full_w <= 0 or full_h <= 0:
        raise ValueError("The image has an invalid size.")

    if total_frames <= 0:
        raise ValueError("Frame count must be greater than zero.")

    if not validate_frame_count(full_w, total_frames):
        raise ValueError(
            f"Invalid frame count for image size "
            f"{full_w}x{full_h}."
        )

    if cols <= 0:
        cols, rows = get_best_grid(total_frames)
    else:
        cols = min(cols, total_frames)
        rows = math.ceil(total_frames / float(cols))

    padding = max(0, int(padding))

    frame_crops = []

    for i in range(total_frames):
        x0, x1 = get_frame_bounds(
            full_w, total_frames, i
        )

        if x1 <= x0:
            raise ValueError(
                "One of the calculated frames has zero width."
            )

        crop = img.crop(
            (x0, 0, x1, full_h)
        )

        alpha = crop.getchannel("A")

        alpha_mask = alpha.point(
            lambda value:
                255 if value > ALPHA_THRESHOLD else 0
        )

        frame_crops.append(
            (crop, alpha_mask.getbbox())
        )

    if not trim_alpha:
        out_frame_w = int(
            round(full_w / float(total_frames))
        )
        out_frame_h = full_h

        out_w = (
            cols * out_frame_w
            + (cols + 1) * padding
        )

        out_h = (
            rows * out_frame_h
            + (rows + 1) * padding
        )

        grid_img = Image.new(
            "RGBA",
            (out_w, out_h),
            (0, 0, 0, 0)
        )

        for i, (crop, _) in enumerate(frame_crops):
            c = i % cols
            r = i // cols

            cell_x = (
                padding
                + c * (out_frame_w + padding)
            )

            cell_y = (
                padding
                + r * (out_frame_h + padding)
            )

            grid_img.paste(
                crop,
                (cell_x, cell_y),
                crop
            )

        grid_img.save(save_path)

        return (
            total_frames,
            out_frame_w,
            out_frame_h,
            cols,
            rows
        )

    # Common content rectangle across all frames.
    # The same rectangle is applied to every frame, which preserves
    # relative object position and avoids frame-to-frame jitter.
    common_left = full_w
    common_top = full_h
    common_right = 0
    common_bottom = 0
    has_content = False

    for crop, bbox in frame_crops:
        if not bbox:
            continue

        has_content = True

        common_left = min(common_left, bbox[0])
        common_top = min(common_top, bbox[1])
        common_right = max(common_right, bbox[2])
        common_bottom = max(common_bottom, bbox[3])

    if not has_content:
        raise ValueError(
            "All frames are fully transparent."
        )

    common_left = max(
        0, common_left - TRIM_MARGIN
    )
    common_top = max(
        0, common_top - TRIM_MARGIN
    )
    common_right = min(
        full_w, common_right + TRIM_MARGIN
    )
    common_bottom = min(
        full_h, common_bottom + TRIM_MARGIN
    )

    out_frame_w = max(
        1, common_right - common_left
    )
    out_frame_h = max(
        1, common_bottom - common_top
    )

    out_w = (
        cols * out_frame_w
        + (cols + 1) * padding
    )

    out_h = (
        rows * out_frame_h
        + (rows + 1) * padding
    )

    grid_img = Image.new(
        "RGBA",
        (out_w, out_h),
        (0, 0, 0, 0)
    )

    for i, (crop, _) in enumerate(frame_crops):
        c = i % cols
        r = i // cols

        cell_x = (
            padding
            + c * (out_frame_w + padding)
        )

        cell_y = (
            padding
            + r * (out_frame_h + padding)
        )

        content = crop.crop(
            (
                common_left,
                common_top,
                common_right,
                common_bottom
            )
        )

        grid_img.paste(
            content,
            (cell_x, cell_y),
            content
        )

    grid_img.save(save_path)

    return (
        total_frames,
        out_frame_w,
        out_frame_h,
        cols,
        rows
    )


# =============================================================================
# HTML / CSS / JavaScript UI
# =============================================================================

HTML = r"""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>SpriteGrid Splitter</title>

<style>
:root {
    font-family: Segoe UI, Arial, sans-serif;
    color: #202124;
    background: #f3f4f6;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 24px;
}

.app {
    max-width: 760px;
    margin: 0 auto;
}

h1 {
    margin: 0 0 18px;
    font-size: 26px;
}

.card {
    background: white;
    border-radius: 14px;
    padding: 20px;
    box-shadow: 0 2px 12px rgba(0,0,0,.08);
    margin-bottom: 14px;
}

.drop-zone {
    border: 2px dashed #8b95a5;
    border-radius: 12px;
    min-height: 170px;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 20px;
    cursor: pointer;
    transition: .15s;
    background: #fafafa;
}

.drop-zone.dragover {
    border-color: #1677ff;
    background: #eef5ff;
}

.drop-zone strong {
    display: block;
    font-size: 17px;
    margin-bottom: 7px;
}

button {
    border: 0;
    border-radius: 8px;
    padding: 11px 18px;
    font-size: 15px;
    cursor: pointer;
}

.primary {
    width: 100%;
    background: #1677ff;
    color: white;
    font-weight: 600;
    margin-top: 14px;
}

.secondary {
    background: #e9edf3;
    color: #202124;
    margin-top: 12px;
}

.grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
}

.field label {
    display: block;
    font-size: 13px;
    margin-bottom: 6px;
    color: #5f6368;
}

input[type=number], select {
    width: 100%;
    padding: 9px;
    border: 1px solid #c8ccd2;
    border-radius: 7px;
    font-size: 14px;
    background: white;
}

.status {
    margin-top: 14px;
    padding: 12px;
    border-radius: 8px;
    background: #f1f3f4;
    white-space: pre-wrap;
    word-break: break-word;
}

.status.good {
    background: #e8f5e9;
}

.status.error {
    background: #fdecec;
}

.file-name {
    margin-top: 10px;
    font-size: 13px;
    color: #5f6368;
    word-break: break-word;
}

.footer {
    text-align: center;
    color: #777;
    font-size: 11px;
    margin-top: 12px;
}

@media (max-width: 600px) {
    .grid {
        grid-template-columns: 1fr;
    }

    body {
        padding: 12px;
    }
}
</style>
</head>

<body>
<div class="app">

    <div class="card">
        <h1>SpriteGrid Splitter</h1>

        <div id="dropZone" class="drop-zone">
            <div>
                <strong></strong>
                <span id="dropHint"></span>
            </div>
        </div>

        <button id="openButton" class="secondary"></button>

        <div id="fileName" class="file-name"></div>
    </div>

    <div class="card">

        <div class="grid">

            <div class="field">
                <label></label>
                <input id="frames" type="number"
                       min="0" max="9999" value="0">
            </div>

            <div class="field">
                <label></label>
                <input id="cols" type="number"
                       min="0" max="999" value="0">
            </div>

            <div class="field">
                <label></label>
                <input id="padding" type="number"
                       min="0" max="500" value="0">
            </div>

            <div class="field">
                <label></label>
                <select id="language">
                    <option value="RU">Русский</option>
                    <option value="LV">Latviešu</option>
                    <option value="EN">English</option>
                </select>
            </div>

        </div>

        <p>
            <label>
                <input id="trim" type="checkbox"><span id="trimLabel"></span>
            </label>
        </p>

        <button id="runButton" class="primary"></button>

        <div id="status" class="status"></div>
    </div>

    <div class="footer">
        SpriteGrid Splitter © JemikiVa
    </div>

</div>

<script>
let selectedFile = null;
let droppedData = null;
let currentLang = "RU";

const I18N = {
    RU: {
        drop: "Перетащите PNG/WebP сюда",
        drop2: "или нажмите для выбора файла",
        open: "Открыть файл...",
        nofile: "Файл не выбран.",
        frames: "Всего кадров (0 = авто)",
        cols: "Колонки (0 = авто)",
        padding: "Отступ между кадрами (px)",
        language: "Язык интерфейса",
        trim: "Убрать прозрачные поля и сохранить положение объекта",
        run: "Сформировать сетку",
        wait: "Ожидание файла.",
        selected: "Файл выбран. Можно запускать обработку.",
        cancelOpen: "Выбор файла отменён.",
        openError: "Не удалось открыть файл.",
        readDrop: "Читаю перетащенный файл...",
        receiveError: "Не удалось принять файл.",
        dropError: "Ошибка Drag & Drop: ",
        badType: "Поддерживаются только PNG и WebP.",
        noDropFile: "Файл не получен.",
        noFile: "Сначала выберите или перетащите файл.",
        analyzing: "Анализирую Sprite Sheet...",
        autoFail: "Auto не смог надёжно определить количество кадров.\nВведите количество кадров вручную:",
        autoFound: "Auto обнаружил {n} кадров.\nПредполагаемая сетка: {c} × {r}\nРазмер кадра: {w} × {h} px\nУверенность: {conf}%",
        multiple: "\n\nВнимание: обнаружены отдельные области содержимого. Возможно, в некоторых кадрах находятся несколько объектов.",
        useDetection: "\n\nИспользовать это определение?",
        manual: "Введите количество кадров вручную:",
        processing: "Формирую сетку...",
        done: "Готово.\n\nСохранено: {path}\nКадров: {frames}\nСетка: {cols} × {rows}\nРазмер кадра: {w} × {h} px",
        langChosen: "Язык: {lang}"
    },
    LV: {
        drop: "Velciet PNG/WebP šeit",
        drop2: "vai noklikšķiniet, lai izvēlētos failu",
        open: "Atvērt failu...",
        nofile: "Fails nav izvēlēts.",
        frames: "Kopējais kadru skaits (0 = automātiski)",
        cols: "Kolonnas (0 = automātiski)",
        padding: "Atstarpe starp kadriem (px)",
        language: "Interfeisa valoda",
        trim: "Noņemt caurspīdīgās malas un saglabāt objekta novietojumu",
        run: "Izveidot tīklāju",
        wait: "Gaidām failu.",
        selected: "Fails izvēlēts. Var sākt apstrādi.",
        cancelOpen: "Faila izvēle atcelta.",
        openError: "Neizdevās atvērt failu.",
        readDrop: "Lasu ievilkto failu...",
        receiveError: "Neizdevās saņemt failu.",
        dropError: "Drag & Drop kļūda: ",
        badType: "Atbalstīti tikai PNG un WebP faili.",
        noDropFile: "Fails nav saņemts.",
        noFile: "Vispirms izvēlieties vai ievelciet failu.",
        analyzing: "Analizēju Sprite Sheet...",
        autoFail: "Auto nevarēja droši noteikt kadru skaitu.\nIevadiet kadru skaitu manuāli:",
        autoFound: "Auto atrada {n} kadrus.\nIespējamais tīklojums: {c} × {r}\nKadra izmērs: {w} × {h} px\nPārliecība: {conf}%",
        multiple: "\n\nUzmanību: atrastas atsevišķas satura zonas. Iespējams, dažos kadros ir vairāki objekti.",
        useDetection: "\n\nIzmantot šo noteikšanu?",
        manual: "Ievadiet kadru skaitu manuāli:",
        processing: "Veidoju tīklāju...",
        done: "Gatavs.\n\nSaglabāts: {path}\nKadru skaits: {frames}\nTīklojums: {cols} × {rows}\nKadra izmērs: {w} × {h} px",
        langChosen: "Valoda: {lang}"
    },
    EN: {
        drop: "Drag & drop PNG/WebP here",
        drop2: "or click to choose a file",
        open: "Open file...",
        nofile: "No file selected.",
        frames: "Total frames (0 = auto)",
        cols: "Columns (0 = auto)",
        padding: "Padding between frames (px)",
        language: "Interface language",
        trim: "Remove transparent margins and preserve object position",
        run: "Generate grid",
        wait: "Waiting for a file.",
        selected: "File selected. Ready to process.",
        cancelOpen: "File selection cancelled.",
        openError: "Failed to open file.",
        readDrop: "Reading dropped file...",
        receiveError: "Failed to receive file.",
        dropError: "Drag & Drop error: ",
        badType: "Only PNG and WebP files are supported.",
        noDropFile: "No file received.",
        noFile: "Please select or drop a file first.",
        analyzing: "Analyzing Sprite Sheet...",
        autoFail: "Auto could not reliably determine the frame count.\nEnter the frame count manually:",
        autoFound: "Auto detected {n} frames.\nSuggested grid: {c} × {r}\nFrame size: {w} × {h} px\nConfidence: {conf}%",
        multiple: "\n\nWarning: separate content regions were detected. Some frames may contain multiple objects.",
        useDetection: "\n\nUse this detection?",
        manual: "Enter the frame count manually:",
        processing: "Generating grid...",
        done: "Done.\n\nSaved: {path}\nFrames: {frames}\nGrid: {cols} × {rows}\nFrame size: {w} × {h} px",
        langChosen: "Language: {lang}"
    }
};

const dropZone = document.getElementById("dropZone");
const fileName = document.getElementById("fileName");
const statusEl = document.getElementById("status");

function t(key, vars = {}) {
    let value = I18N[currentLang][key] || key;
    return value.replace(/\{(\w+)\}/g, (_, k) =>
        vars[k] !== undefined ? vars[k] : ""
    );
}

function status(message, kind = "") {
    statusEl.textContent = message;
    statusEl.className = "status " + kind;
}

function applyLanguage() {
    document.querySelector("#dropZone strong").textContent = t("drop");
    document.getElementById("dropHint").textContent = t("drop2");
    document.getElementById("openButton").textContent = t("open");
    document.getElementById("fileName").textContent = selectedFile?.name || droppedData?.name
        ? "Файл: " + (selectedFile?.name || droppedData?.name)
        : t("nofile");

    const labels = document.querySelectorAll(".field label");
    labels[0].textContent = t("frames");
    labels[1].textContent = t("cols");
    labels[2].textContent = t("padding");
    labels[3].textContent = t("language");

    document.getElementById("trimLabel").textContent = " " + t("trim");
    document.getElementById("runButton").textContent = t("run");

    if (!selectedFile && !droppedData) {
        status(t("wait"));
    }
}

function showSelected(name) {
    fileName.textContent = (currentLang === "RU" ? "Файл: " : currentLang === "LV" ? "Fails: " : "File: ") + name;
    status(t("selected"), "good");
}

async function openFile() {
    const result = await window.pywebview.api.open_file(currentLang);

    if (!result || !result.ok) {
        if (result && result.cancelled) status(t("cancelOpen"));
        else status((result && result.error) || t("openError"), "error");
        return;
    }

    selectedFile = { path: result.path, name: result.name };
    droppedData = null;
    showSelected(result.name);
}

document.getElementById("openButton").addEventListener("click", openFile);

dropZone.addEventListener("dragover", function(event) {
    event.preventDefault();
    dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", function() {
    dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", async function(event) {
    event.preventDefault();
    dropZone.classList.remove("dragover");

    const files = event.dataTransfer.files;
    if (!files || files.length === 0) {
        status(t("noDropFile"), "error");
        return;
    }

    const file = files[0];
    const name = file.name.toLowerCase();
    if (!name.endsWith(".png") && !name.endsWith(".webp")) {
        status(t("badType"), "error");
        return;
    }

    status(t("readDrop"));
    try {
        const buffer = await file.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        const result = await window.pywebview.api.drop_file(file.name, Array.from(bytes));
        if (!result || !result.ok) {
            status((result && result.error) || t("receiveError"), "error");
            return;
        }
        selectedFile = null;
        droppedData = { name: result.name };
        showSelected(result.name);
    } catch (error) {
        status(t("dropError") + error, "error");
    }
});

document.getElementById("runButton").addEventListener("click", async function() {
    const frames = Number(document.getElementById("frames").value);
    const cols = Number(document.getElementById("cols").value);
    const padding = Number(document.getElementById("padding").value);
    const trim = document.getElementById("trim").checked;

    if (!selectedFile && !droppedData) {
        status(t("noFile"), "error");
        return;
    }

    if (frames === 0) {
        status(t("analyzing"));
        const result = await window.pywebview.api.analyze(
            selectedFile ? selectedFile.path : "",
            droppedData ? droppedData.name : ""
        );

        if (!result.ok) {
            status(result.error, "error");
            return;
        }

        if (!result.detected) {
            const manual = prompt(t("autoFail"), "1");
            if (manual === null) return;
            document.getElementById("frames").value = manual;
        } else {
            let message = t("autoFound", {
                n: result.detected, c: result.cols, r: result.rows,
                w: result.frame_width, h: result.frame_height,
                conf: result.confidence
            });
            if (result.multiple_regions) message += t("multiple");
            message += t("useDetection");

            if (confirm(message)) {
                document.getElementById("frames").value = result.detected;
            } else {
                const manual = prompt(t("manual"), String(result.detected));
                if (manual === null) return;
                document.getElementById("frames").value = manual;
            }
        }
    }

    const finalFrames = Number(document.getElementById("frames").value);
    status(t("processing"));

    const result = await window.pywebview.api.process(
        selectedFile ? selectedFile.path : "",
        droppedData ? droppedData.name : "",
        finalFrames,
        cols,
        padding,
        trim,
        currentLang
    );

    if (!result.ok) {
        status(result.error, "error");
        return;
    }

    status(t("done", {
        path: result.path,
        frames: result.frames,
        cols: result.cols,
        rows: result.rows,
        w: result.width,
        h: result.height
    }), "good");
});

document.getElementById("language").addEventListener("change", function() {
    currentLang = this.value;
    applyLanguage();
    status(t("langChosen", {lang: this.options[this.selectedIndex].text}));
});

applyLanguage();
</script>
</script>
</body>
</html>
"""


# =============================================================================
# Python API exposed to JavaScript
# =============================================================================

class Api:

    def __init__(self):
        self.dropped_images = {}

    def open_file(self, lang="RU"):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        try:
            path = filedialog.askopenfilename(
                title={"RU": "Выберите спрайтшит", "LV": "Izvēlieties spraitu joslu", "EN": "Select spritesheet"}.get(lang, "Select spritesheet"),
                filetypes=[
                    ("Images", "*.png *.webp"),
                    ("PNG", "*.png"),
                    ("WebP", "*.webp"),
                ],
            )
        finally:
            root.destroy()

        if not path:
            return {
                "ok": False,
                "cancelled": True
            }

        return {
            "ok": True,
            "path": path,
            "name": os.path.basename(path)
        }

    def drop_file(self, name, byte_list):
        try:
            if not name.lower().endswith(SUPPORTED_EXTENSIONS):
                return {
                    "ok": False,
                    "error": "Поддерживаются только PNG и WebP."
                }

            raw = bytes(byte_list)

            # Validate the image immediately.
            with Image.open(io.BytesIO(raw)) as img:
                img.verify()

            # Keep the bytes in memory for this prototype.
            # A unique key prevents collisions between similarly named files.
            key = str(id(raw))
            self.dropped_images[key] = (name, raw)

            # The key is encoded into the name field only for internal use.
            # The browser only displays the real file name.
            self.last_drop_key = key

            return {
                "ok": True,
                "name": name
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": "Не удалось прочитать файл: " + str(exc)
            }

    def _load_image(self, path, dropped_name):
        if path and os.path.exists(path):
            return Image.open(path).convert("RGBA"), path

        key = getattr(self, "last_drop_key", None)

        if not key or key not in self.dropped_images:
            raise ValueError("Перетащенный файл больше недоступен.")

        name, raw = self.dropped_images[key]

        image = Image.open(io.BytesIO(raw)).convert("RGBA")

        return image, None

    def analyze(self, path, dropped_name):
        try:
            img, _ = self._load_image(path, dropped_name)

            detected, confidence = detect_frame_count(img)

            if detected is None:
                return {
                    "ok": True,
                    "detected": None,
                    "confidence": round(confidence * 100)
                }

            cols, rows = get_best_grid(detected)
            frame_width = int(
                round(img.width / float(detected))
            )
            frame_height = img.height

            multiple_regions, region_count = (
                analyze_frame_regions(img, detected)
            )

            return {
                "ok": True,
                "detected": detected,
                "confidence": round(confidence * 100),
                "cols": cols,
                "rows": rows,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "multiple_regions": multiple_regions,
                "region_count": region_count,
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": "Не удалось проанализировать файл:\n" + str(exc)
            }

    def process(
        self,
        path,
        dropped_name,
        total_frames,
        cols,
        padding,
        trim_alpha,
        lang="RU"
    ):
        try:
            total_frames = int(total_frames)
            cols = int(cols)
            padding = int(padding)

            img, original_path = self._load_image(
                path, dropped_name
            )

            # Always use Save As. The user explicitly chooses the
            # destination and filename, so Trim on/off or repeated runs
            # can never silently overwrite an earlier result.
            if original_path:
                base = os.path.splitext(
                    os.path.basename(original_path)
                )[0]
                source_extension = os.path.splitext(
                    original_path
                )[1].lower()
            else:
                base = os.path.splitext(
                    dropped_name or "spritesheet"
                )[0]
                source_extension = ".png"

            # Determine the final grid before opening Save As, and use
            # exactly that same grid in the suggested filename.
            # Example: character_grid_8x4.png
            if cols <= 0:
                cols, rows = get_best_grid(total_frames)
            else:
                cols = min(cols, total_frames)
                rows = math.ceil(total_frames / float(cols))

            trim_suffix = "_trim" if bool(trim_alpha) else ""
            grid_suffix = f"{trim_suffix}_grid_{cols}x{rows}"

            if source_extension == ".webp":
                default_extension = ".webp"
                initial_name = base + grid_suffix + ".webp"
                filetypes = [
                    ("WebP", "*.webp"),
                    ("PNG", "*.png"),
                ]
            else:
                default_extension = ".png"
                initial_name = base + grid_suffix + ".png"
                filetypes = [
                    ("PNG", "*.png"),
                    ("WebP", "*.webp"),
                ]

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            try:
                save_path = filedialog.asksaveasfilename(
                    title={"RU": "Сохранить сетку", "LV": "Saglabāt tīklāju", "EN": "Save grid"}.get(lang, "Save grid"),
                    defaultextension=default_extension,
                    filetypes=filetypes,
                    initialfile=initial_name,
                )
            finally:
                root.destroy()

            if not save_path:
                return {
                    "ok": False,
                    "cancelled": True,
                    "error": "Сохранение отменено."
                }

            if os.path.exists(save_path):
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)

                try:
                    overwrite = messagebox.askyesno(
                        "Файл уже существует",
                        {"RU": "Файл уже существует:\n\n", "LV": "Fails jau pastāv:\n\n", "EN": "File already exists:\n\n"}.get(lang, "File already exists:\n\n") +
                        save_path +
                        "\n\n" + {"RU": "Перезаписать его?", "LV": "Pārrakstīt to?", "EN": "Overwrite it?"}.get(lang, "Overwrite it?")
                    )
                finally:
                    root.destroy()

                if not overwrite:
                    return {
                        "ok": False,
                        "cancelled": True,
                        "error": "Сохранение отменено."
                    }

            result = process_image(
                img,
                save_path,
                total_frames=total_frames,
                cols=cols,
                trim_alpha=bool(trim_alpha),
                padding=padding,
            )

            count, width, height, out_cols, rows = result

            return {
                "ok": True,
                "path": save_path,
                "frames": count,
                "width": width,
                "height": height,
                "cols": out_cols,
                "rows": rows,
            }

        except (OSError, UnidentifiedImageError) as exc:
            return {
                "ok": False,
                "error": "Ошибка работы с изображением:\n" + str(exc)
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": "Не удалось обработать файл:\n" + str(exc)
            }


def main():
    api = Api()

    webview.create_window(
        "SpriteGrid Splitter",
        html=HTML,
        js_api=api,
        width=800,
        height=760,
        resizable=True,
        min_size=(620, 560),
        background_color="#f3f4f6",
    )

    webview.start()


if __name__ == "__main__":
    main()
