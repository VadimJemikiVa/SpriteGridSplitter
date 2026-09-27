SpriteGrid Splitter

A small portable Windows tool for converting long or horizontal sprite strips into grid-based sprite sheets.

SpriteGrid Splitter takes a sprite sheet containing animation frames arranged in a strip or other linear layout and reorganizes those frames into a regular grid.

It is designed for a simple workflow when an existing animation strip needs to be converted into a more practical sprite-sheet layout for use in game engines and other graphics tools.

Copyright © 2026 JemikiVa

## Features

-   PNG and WebP input
-   Automatic frame-grid detection
-   Manual frame count when automatic detection is uncertain
-   Automatic or manual column count
-   Common transparent-area **Trim** across all frames
-   PNG or WebP output
-   Drag & Drop
-   Russian, Latvian and English interface
-   Resizable desktop window
-   Portable single-EXE distribution

## How it works

SpriteGrid Splitter takes a sprite sheet containing multiple frames and
creates a new sprite sheet arranged as a regular grid.

The automatic detector is deliberately conservative. When it cannot
determine the frame count with sufficient confidence, the application
asks for the frame count instead of silently guessing.

When **Trim** is enabled, the application calculates a common
transparent-content rectangle for the frames and applies the same
rectangle to every frame. This keeps the relative position of the sprite
consistent and helps avoid animation jitter.

## Supported formats

### Input

-   PNG
-   WebP

### Output

-   PNG
-   WebP

The suggested output format follows the source format where appropriate.

## Portable distribution

This release is distributed as a portable Windows executable:

`SpriteGridSplitter.exe`

No installer is required. The executable can be run directly from a
folder.

This project intentionally does not assign a product version number to
this first public release.

## License

The SpriteGrid Splitter software and source code authored by JemikiVa
are licensed under the **PolyForm Noncommercial License 1.0.0**.

Official license text:

https://polyformproject.org/licenses/noncommercial/1.0.0

PolyForm Noncommercial permits use, modification, and distribution for
permitted **noncommercial purposes**, subject to the conditions of the
license. The license expressly includes personal research,
experimentation, testing, study, hobby projects, and other specified
personal uses when there is no anticipated commercial application.

The project is **source-available** and is not licensed under an
OSI-approved Open Source license.

The project license does not grant commercial rights. A use that is not
a permitted noncommercial purpose under the PolyForm Noncommercial
License 1.0.0 is not licensed by this project. Separate permission from
the copyright holder may be required for such use.

The PolyForm license also requires recipients of copies to receive the
license terms or the official license URL, together with the applicable
`Required Notice` supplied with the software.

See [`LICENSE`](LICENSE) for the license identification and required
notice.

The official PolyForm license text, rather than this README, determines
the legal permissions, conditions, restrictions, and definitions
applicable to the software.

## Third-party components

SpriteGrid Splitter uses third-party software components. Those
components remain under their own licenses and are not relicensed by the
PolyForm Noncommercial License for SpriteGrid Splitter.

Third-party components include Python, Pillow, PyWebView, and
dependencies used by the distributed application.

See [`THIRD-PARTY-NOTICES.txt`](THIRD-PARTY-NOTICES.txt) for the
project's third-party software notices and applicable license
information.

When redistributing the application, the applicable third-party
copyright notices and license terms must be preserved as required by
their respective licenses.

## Disclaimer

The software is provided **"as is"**, without warranties or conditions,
to the extent provided by the applicable licenses and permitted by
applicable law.

The author is not responsible for loss or damage to user data to the
extent permitted by applicable law. Keep backup copies of important
original images.

## Author

**JemikiVa**

Copyright © 2026 JemikiVa

## Repository contents

-   `SheetSplitter_PyWebView_AlphaTest3.py` --- source code of the
    tested application
-   `SpriteGridSplitter.ico` --- application icon
-   `README.md` --- project documentation
-   `LICENSE` --- project license notice
-   `THIRD-PARTY-NOTICES.txt` --- third-party software notices

## Legal note

This README is informational only and does not modify the PolyForm
Noncommercial License 1.0.0.

For the legally controlling terms, consult the official license text:

https://polyformproject.org/licenses/noncommercial/1.0.0
