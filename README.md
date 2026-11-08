# PDFPad

Offline PDF conversion desktop app for Linux. The project is built in phases;
the full plan is in `/home/kvy/.opencode/plan/pdfpad-linux-plan.md` and the
implementation reports are in [`report/`](report/).

**Current status:** Phases 1 (core library), 2 (PySide6 GUI), 3
(compression + Office → PDF), 4 (Markdown export), 5 (packaging) and 6
(air-gap validation) are implemented, with 374 passing tests.

## Features

- Page-selection parsing (`"1-3,7"`, open ranges, duplicate handling)
- Extract, split, merge, and rotate PDF pages
- Render pages to PNG/JPEG and thumbnails (bundled PDFium, no poppler)
- Combine images into a PDF with page-size, fit, DPI, and quality options
- Extract page text (and write it to a UTF-8 file)
- **Convert PDFs to best-effort Markdown** (headings, paragraphs, lists, simple
  tables)
- **Compress PDFs losslessly (pikepdf) or by rasterizing pages to JPEG**
- **Convert Office documents to PDF via the optional LibreOffice add-on pack**
- Password-protected PDF support in every operation
- Atomic output writes and clear user-facing errors
- PySide6 desktop GUI with drag-and-drop input, page previews, per-operation
  options, output picker, background execution, progress, and cancellation
- **Self-contained PyInstaller build, portable tarball, `install.sh`, and
  optional `.deb`**
- **Bundled PDFium, QPDF, and Qt — no system conversion binaries required**

Everything in `core/` is GUI-independent and makes no network calls.

## Run the GUI

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m gui
```

After an editable install (`pip install -e .`) the `pdfpad` command is also
available.

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The GUI tests run headlessly through the Qt `offscreen` platform.

## Build a portable release

Packaging uses PyInstaller in `--onedir` mode. The build is fully local; it
does not download anything.

```bash
.venv/bin/pip install -r requirements-dev.txt
./packaging/build_linux.sh          # onedir + dist/PDFPad-<version>-linux-<arch>.tar.gz
./packaging/build_linux.sh --deb    # also build a .deb
./packaging/build_linux.sh --no-tarball
```

The build script generates the icons and license bundle, runs the frozen
`--self-test` (pypdf, PDFium, pdfminer, pikepdf, Pillow, and Qt), and only then
creates the release. The optional LibreOffice add-on is copied into
`PDFPad/office/` only when `office/program/soffice` exists.

### Install a release

```bash
tar -xzf dist/PDFPad-0.5.0-linux-x86_64.tar.gz
cd PDFPad-0.5.0-linux-x86_64

./install.sh                  # install for the current user under ~/.local
sudo ./install.sh --system    # install system-wide under /usr/local
./install.sh --set-default    # make PDFPad the default PDF handler
./install.sh --uninstall      # remove the installation
```

The optional `.deb` installs the application under `/opt/pdfpad`, adds
`/usr/bin/pdfpad`, and registers the desktop entry, icons, and MIME type:

```bash
sudo apt install ./dist/pdfpad_0.5.0_amd64.deb
```

The app can be smoke-tested without a display:

```bash
PDFPad/PDFPad --self-test
PDFPad/PDFPad --version
```

### Optional LibreOffice add-on

Office → PDF stays disabled until a LibreOffice tree is available. Place the
add-on so that `office/program/soffice` exists next to the `PDFPad` executable
(for example `PDFPad/office/program/soffice`), or point
`PDFPAD_LIBREOFFICE` at a `soffice` binary. See `office/README.md`.

## Air-gap validation

`packaging/airgap_validate.sh` proves a release works without network access:

```bash
./packaging/airgap_validate.sh
./packaging/airgap_validate.sh --pages 300      # larger fixture
./packaging/airgap_validate.sh --no-office      # skip optional LibreOffice
```

It runs the frozen app and the core checks inside an unprivileged
`unshare -Urn` network namespace, verifies with `strace` that no
`AF_INET`/`AF_INET6` socket calls occur, repeats the frozen self-test with an
empty environment and no `PATH`, confirms the bundle (not the system) supplies
Python and Qt, runs the full test suite, performs two install/uninstall cycles,
and extracts and runs the `.deb` when one exists.

The core checks (`packaging/airgap_checks.py`) cover all six feature areas on a
many-page PDF, large images, an AES-256 encrypted PDF, cancellation, atomic
failure, repeated runs, and temporary-file cleanup. A true clean-VM run on the
oldest supported distribution is still a manual release step; see
[`report/PDFPad-Phase6-Report.md`](report/PDFPad-Phase6-Report.md).

## Layout

```
core/       GUI-independent operations and error types
gui/        PySide6 application shell, widgets, workers, request builder
office/     Optional LibreOffice add-on pack (program/soffice, share/, LICENSE)
packaging/  PyInstaller spec, build scripts, desktop/MIME files, icons,
            licenses, air-gap validation harness
tests/      pytest suite with generated PDF/image fixtures plus a fake-office
            helper for Office-conversion tests
report/     Phase implementation reports
```

## License

Third-party license texts are collected into `licenses/` in every release; the
component summary is
[`packaging/licenses/THIRD_PARTY_NOTICES.md`](packaging/licenses/THIRD_PARTY_NOTICES.md).
The PDFPad application code does not currently declare a license; choose one
before public distribution.

## Example

```python
from core.compress import compress_pdf
from core.markdown import extract_markdown_to_file
from core.office import office_to_pdf, office_available
from core.pages import extract_pages
from core.ranges import parse_ranges

pages = parse_ranges("1-3,7", total=10)   # -> [0, 1, 2, 6]
extract_pages("input.pdf", pages, "selected.pdf")

extract_markdown_to_file("input.pdf", "input.md", indices=pages)

compress_pdf("input.pdf", "input_compressed.pdf", mode="lossless")

if office_available():
    office_to_pdf(["report.docx"], "output_folder")
```
# pdfpad
