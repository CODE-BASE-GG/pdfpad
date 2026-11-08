# PDFPad third-party notices

PDFPad is distributed with the Python runtime and several third-party
libraries. This file summarises the components and their licenses. The
`licenses/` directory in a release contains the license texts collected from
the installed wheels and from the build system.

## Application code

PDFPad is free software, licensed under the **GNU General Public License,
version 3 or (at your option) any later version** (GPL-3.0-or-later).

Copyright (C) 2026 Rainiel Dejito.

The full license text is in the `LICENSE` file at the root of the source tree
and in `licenses/GPL-3.0.txt` in a release. The third-party components below
keep their own licenses regardless of the project license.

## Bundled runtime components

| Component | Version at build time | License | Notes |
|---|---|---|---|
| Python | 3.12 | PSF-2.0 | Bundled by PyInstaller as `libpython` |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with a special exception | The exception permits distributing bundled applications |
| pypdf | 6.21.1 | BSD-3-Clause | PDF reading, writing, merging, rotation |
| pypdfium2 | 5.15.0 | Apache-2.0 OR BSD-3-Clause | Python bindings; bundles PDFium |
| PDFium | (bundled with pypdfium2) | BSD-3-Clause | PDF rendering engine; see `pypdfium2*/BUILD_LICENSES/` |
| Pillow | 13.0.0 | MIT-CMU | Image loading, resizing, composition |
| pikepdf | 9.11.0 | MPL-2.0 | PDF compression; bundles QPDF |
| QPDF | (bundled with pikepdf) | Apache-2.0 | Structural PDF rewriting |
| pdfminer.six | 20260107 | MIT | Layout analysis and text extraction |
| PySide6-Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Qt 6 bindings |
| shiboken6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Binding generator runtime |
| Qt 6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | GUI toolkit bundled with PySide6 |

The pypdfium2 wheel contains additional notices for libraries compiled into
PDFium (FreeType, HarfBuzz, ICU, libjpeg-turbo, libpng, libtiff, zlib, and
others). Those files are copied into `licenses/pypdfium2-*/BUILD_LICENSES/`.

Qt and PySide6 do not ship license files in their wheels. The build script
copies the system copies of LGPL-3.0 and GPL-3.0 into `licenses/qt-*` when they
are available. Qt's LGPL option also carries the usual relinking requirements;
distributors who modify the bundled Qt libraries must comply with those terms.

## Optional LibreOffice add-on

The optional Office → PDF add-on is **not** included in the default build. If a
LibreOffice tree is placed in `PDFPad/office/`, that copy is governed by
LibreOffice's own licenses (primarily MPL-2.0 and LGPL-3.0-or-later), and its
license files must be kept with the add-on. PDFPad only invokes the add-on as a
separate process.

## Build-time-only components

The following are used to build the release but are not part of the shipped
application (apart from the PyInstaller bootloader noted above):

- PyInstaller
- pytest, pytest-qt
- The DejaVu Sans font, used to render the application icon at build time

## No network access

PDFPad makes no network requests at runtime. This notice is provided for
license compliance only; it is not a network or update mechanism.
