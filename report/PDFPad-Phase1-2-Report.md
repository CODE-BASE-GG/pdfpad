# PDFPad — Phase 1 & Phase 2 Implementation Report

**Project:** PDFPad — an offline PDF conversion desktop application for Linux  
**Version:** 0.2.0  
**Report date:** 2026-11-07  
**Target platform:** Linux x86_64, glibc ≥ 2.34 (Ubuntu 22.04 / Linux Mint 21 or newer)  
**Runtime model:** fully offline, no network calls, no system binaries required for core conversion  
**Current status:** Phase 1 (core library) complete · Phase 2 (PySide6 GUI) complete · 236 automated tests passing

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [Product overview](#2-product-overview)
3. [Feature status matrix](#3-feature-status-matrix)
4. [Architecture](#4-architecture)
5. [Phase 1 — Core library](#5-phase-1--core-library)
6. [Phase 2 — PySide6 GUI](#6-phase-2--pyside6-gui)
7. [Installation, launch, and usage](#7-installation-launch-and-usage)
8. [Testing and quality assurance](#8-testing-and-quality-assurance)
9. [Design decisions and rationale](#9-design-decisions-and-rationale)
10. [Limitations and known issues](#10-limitations-and-known-issues)
11. [Roadmap: Phase 3 and beyond](#11-roadmap-phase-3-and-beyond)
12. [Project file map](#12-project-file-map)
13. [Appendix A — Core API quick reference](#appendix-a--core-api-quick-reference)
14. [Appendix B — Naming and format conventions](#appendix-b--naming-and-format-conventions)
15. [Appendix C — Test inventory](#appendix-c--test-inventory)

---

## 1. Executive summary

PDFPad is a Linux desktop application for common PDF conversion and page-manipulation tasks. It is designed for environments where files must not leave the machine: the application makes no network requests and performs every conversion with bundled Python wheels rather than external programs such as Ghostscript, Poppler, or LibreOffice.

The implementation is deliberately split into two layers:

- **`core/`** — a GUI-independent Python library that does the actual work. It accepts filesystem paths and plain data, returns paths, strings, or PIL images, and contains no Qt imports.
- **`gui/`** — a PySide6 application shell that collects files and options, validates them through a Qt-free request builder, and runs core operations on a background thread with progress reporting and cancellation.

Phase 1 delivered the core library and 113 tests. Phase 2 added the desktop GUI, a background worker, drag-and-drop input, page previews, password prompts, progress/cancel controls, persistent settings, logging, and 123 additional tests. The full suite now contains **236 passing tests** and runs headlessly through the Qt `offscreen` platform.

The following six feature areas were planned. Four are implemented end to end today:

| # | Feature area | Status |
|---|---|---|
| 1 | Page operations (extract, split, merge, rotate) | ✅ Phase 1 core + Phase 2 GUI |
| 2 | PDF → images (PNG/JPEG, DPI, page range) | ✅ Phase 1 core + Phase 2 GUI |
| 3 | Images → PDF (order, page size, fit) | ✅ Phase 1 core + Phase 2 GUI |
| 4 | Office → PDF (optional LibreOffice add-on) | ⏳ Phase 3 |
| 5 | Compress (lossless + optional rasterize) | ⏳ Phase 3 |
| 6 | PDF → text / Markdown | ✅ text in Phases 1–2 · ⏳ Markdown in Phase 4 |

---

## 2. Product overview

### 2.1 What the application does

PDFPad covers the everyday PDF tasks that normally require several different command-line tools:

- Copy selected pages into a new PDF.
- Split a PDF into one file per page or into fixed-size chunks.
- Merge several PDFs in a chosen order.
- Rotate all pages or a selected range.
- Render PDF pages to PNG or JPEG at a chosen resolution.
- Combine images (PNG, JPEG, WebP, BMP, TIFF, GIF) into a PDF.
- Extract the text of selected pages to a UTF-8 `.txt` file.

### 2.2 Offline and self-contained guarantees

- **No network access in application code.** Core and GUI modules make no HTTP, socket, or download calls.
- **No external conversion binaries.** PDF rendering uses `pypdfium2`, which bundles PDFium; PDF writing and page manipulation use `pypdf`; image handling uses `Pillow`.
- **All dependencies are Python wheels.** There is no runtime dependency on `poppler-utils`, `qpdf`, Ghostscript, or LibreOffice for the features implemented in Phases 1–2.
- **Local filesystem only.** Outputs are written next to the inputs or to a user-selected folder.

The only OS-level integration in Phase 2 is the “Open output folder” button, which asks the desktop environment to open a local folder through `QDesktopServices`. It is not used for conversion.

### 2.3 Target users

- Privacy-sensitive users who cannot upload documents to online converters.
- Air-gapped or restricted-network workstations.
- Linux users who want a simple GUI instead of chaining `pdftk`, `qpdf`, `pdftoppm`, and similar tools.
- Developers who want a reusable, testable PDF core (`core/`) independent of the GUI.

---

## 3. Feature status matrix

### 3.1 Implemented in Phase 1 (core) and Phase 2 (GUI)

| Capability | Core API | GUI exposure | Notes |
|---|---|---|---|
| Page selection grammar | `core.ranges.parse_ranges` | Page-range fields | 1-based, inclusive, open ranges, dedupe |
| Extract pages | `core.pages.extract_pages` | “Extract pages” | Preserves selection order |
| Split PDF | `core.pages.split_pdf` | “Split PDF” | One file per page or chunks |
| Merge PDFs | `core.pages.merge_pdfs` | “Merge PDFs” | List order, per-file passwords |
| Rotate pages | `core.pages.rotate_pages` | “Rotate pages” | 90°/180°/270° in GUI |
| Page count | `core.pages.page_count` | Pre-flight / preview | Also drives password detection |
| PDF → PNG/JPEG | `core.render.render_pages` | “PDF to images” | DPI, format, quality, page range |
| Single-page render | `core.render.render_page_image` | Library only | Useful for integrations |
| Thumbnails | `core.render.render_thumbnail(s)` | Preview strip | First 12 pages in the GUI |
| Images → PDF | `core.images.images_to_pdf` | “Images to PDF” | Page size, fit, DPI, quality, background |
| Text extraction | `core.text.extract_text*` | “Extract text” | UTF-8 output, selected pages |
| Password-protected PDFs | Optional `password=` argument | Password dialog | Up to three attempts per file |
| Atomic output writes | `core.io.atomic_output` | All operations | No partial target files |
| Progress reporting | `core.progress.report` | Progress bar | `progress(current, total)` |
| Cooperative cancellation | `core.progress.check_cancel` | Cancel button | Stops at page/image/file boundaries |
| Persistent settings | — | `QSettings` INI | Window geometry, last folder, last operation |
| Logging | — | Rotating file log | Startup logging today; extensible |

### 3.2 Planned but not yet implemented

| Capability | Planned phase | Current state |
|---|---|---|
| Office → PDF | Phase 3 | Optional LibreOffice add-on pack; no code yet |
| Lossless compression | Phase 3 | `pikepdf` planned; not yet a dependency |
| Rasterize compression | Phase 3 | Planned with a text-loss warning |
| PDF → Markdown | Phase 4 | `pdfminer.six` declared but not yet used |
| OCR for scanned PDFs | Not in current scope | Text extraction is text-layer only |
| Packaging (`PyInstaller`, `.desktop`, installer) | Phase 5 | Not started |
| Air-gap validation (`unshare -n`, clean VM) | Phase 6 | Not yet performed |

---

## 4. Architecture

### 4.1 Layered design

```
┌──────────────────────────────────────────────────────────────────────┐
│                         PySide6 GUI — gui/                          │
│                                                                      │
│  MainWindow                                                          │
│    ├── FileDropList        drag-and-drop, duplicate filtering        │
│    ├── PreviewStrip        asynchronous page thumbnails              │
│    ├── OptionsPanel        operation selector, forms, output picker  │
│    └── OperationWorker     QRunnable, progress/cancel/result signals │
│                                                                      │
│  gui.operations            Qt-free validation + request building     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ calls core functions with paths/options
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       Core library — core/                           │
│                                                                      │
│  ranges.py     page-selection grammar → 0-based indices              │
│  pages.py      extract · split · merge · rotate · page_count         │
│  render.py     PDF → PIL images / PNG / JPEG / thumbnails            │
│  images.py     ordered images → PDF                                  │
│  text.py       PDF → text / UTF-8 file                               │
│  io.py         input validation + atomic output writes               │
│  progress.py   progress callback + cancellation checkpoints          │
│  errors.py     user-facing exception hierarchy                       │
│                                                                      │
│  Dependencies: pypdf · pypdfium2 (bundled PDFium) · Pillow           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ atomic writes (temp + os.replace)
                                ▼
                         Local filesystem
```

### 4.2 Separation of concerns

The split is enforced by a simple rule: **nothing under `core/` imports Qt, and nothing under `gui/operations.py` imports Qt.** This gives three benefits:

1. Core operations are testable without a display server.
2. Validation and the mapping from UI options to core calls are testable headlessly.
3. A future CLI, batch processor, or service can reuse `core/` unchanged.

`gui/operations.py` is the bridge. It knows the list of operations, their input/output kinds, default output names, and how to translate display values such as `"A4"`, `"Cover"`, or `"JPEG"` into core arguments such as `"a4"`, `"cover"`, or `"jpeg"`. It performs all validation before any worker starts.

### 4.3 End-to-end data flow

1. The user adds files through the file dialog or drag-and-drop. `FileDropList` rejects unsupported extensions and duplicate paths.
2. `MainWindow` updates `OptionsPanel` with the current file list and shows a preview of the selected file.
3. The user chooses an operation and options. Default output paths are derived from the first input file.
4. On **Run**, `MainWindow._resolve_passwords()` checks every PDF. Encrypted files trigger a password dialog.
5. `build_request()` validates files, output paths, page ranges, and option values. It returns an `OperationRequest` containing the core function, keyword arguments, and output path.
6. An `OperationWorker` is started on `QThreadPool.globalInstance()`. The worker injects `progress=` and `cancel=` into the core call.
7. Core operations write outputs atomically and report progress per page/image/file.
8. The worker emits `finished`, `failed`, or `cancelled`; the GUI restores its controls and shows the result.

### 4.4 Dependency inventory

Versions below are the exact versions used for the Phase 2 test run (`requirements.txt`).

| Package | Version | Purpose |
|---|---|---|
| Python | 3.12.3 | Runtime used for development and tests |
| `pypdf` | 6.21.1 | Reading, writing, merging, rotating, encrypting/decrypting PDFs |
| `pypdfium2` | 5.15.0 | Rendering PDF pages and thumbnails; bundles PDFium |
| `Pillow` | 13.0.0 | Loading images, resizing, compositing, writing image-based PDFs |
| `pdfminer.six` | 20260107 | Declared for planned Markdown extraction (Phase 4); not yet used |
| `PySide6-Essentials` | 6.12.0 | Qt 6 widgets, signals, threading, settings |
| `pytest` | 9.1.1 | Test runner (development only) |
| `pytest-qt` | 4.5.0 | Qt fixtures, `qtbot`, signal waiting (development only) |

`pikepdf`, `PyInstaller`, and LibreOffice are **not** current dependencies; they belong to Phase 3/5.

---

## 5. Phase 1 — Core library

The core library lives in `core/`. Every public function accepts paths or plain data, performs validation, and either returns a result or raises a user-facing exception.

### 5.1 Page-selection grammar — `core/ranges.py`

`parse_ranges(spec, total)` converts a 1-based, human-friendly page selection into 0-based page indices.

Supported syntax:

| Input | Meaning | Result for a 5-page PDF |
|---|---|---|
| `"1"` | page 1 | `[0]` |
| `"1-3"` | pages 1 through 3 | `[0, 1, 2]` |
| `"3-"` | page 3 through the end | `[2, 3, 4]` |
| `"-3"` | pages 1 through 3 | `[0, 1, 2]` |
| `"1,3,5"` | pages 1, 3, 5 | `[0, 2, 4]` |
| `"1 3 5"` | whitespace-separated | `[0, 2, 4]` |
| `"1 - 3"` | spaces around the hyphen | `[0, 1, 2]` |
| `"3,1-2"` | selection order preserved | `[2, 0, 1]` |
| `"2,2,1"` | duplicates removed, first occurrence kept | `[1, 0]` |

Rules and errors:

- Page numbers are **1-based and inclusive**.
- Ranges can be open-ended at either end (`3-`, `-3`).
- Separators are commas, whitespace, or a mix. Trailing or repeated separators are tolerated (`"1,"`, `"1,,2"`).
- Duplicates are removed while preserving the order in which pages were first selected.
- Reversed ranges (`5-2`), zero/negative page numbers, out-of-bounds pages, empty selections, and malformed text raise `RangeSpecError`.
- Non-string specs and non-integer totals raise `TypeError`; a negative total raises `ValueError`.

A separate function, `validate_indices(indices, total)`, validates an already-computed sequence of 0-based indices. Unlike `parse_ranges`, it **preserves duplicates and order exactly as given**. Core operations use it so programmatic callers get the same clear errors as GUI users. For example, `extract_pages(pdf, [0, 0], out)` deliberately keeps the first page twice.

### 5.2 Page operations — `core/pages.py`

All page operations accept an optional `password` for encrypted PDFs.

#### `page_count(path, password=None) -> int`

Opens the PDF and returns the number of pages. Used by the GUI for pre-flight checks and password detection.

#### `extract_pages(input_path, indices, output_path, password=None, progress=None, cancel=None) -> Path`

Copies the selected 0-based page indices into a new PDF.

- Selection order is preserved; duplicates are allowed.
- Empty or out-of-range selections raise `RangeSpecError`.
- The output is written atomically; a cancelled run leaves no partial file.

#### `split_pdf(input_path, output_dir, chunk_size=1, password=None, progress=None, cancel=None) -> list[Path]`

Splits a PDF into chunks of `chunk_size` pages.

- Default `chunk_size=1` creates one PDF per page.
- Files are named `<stem>_pages_<first>-<last>.pdf`, zero-padded to the width of the page count. For a 5-page file: `five_pages_1-1.pdf` … `five_pages_5-5.pdf`.
- `chunk_size` must be an integer ≥ 1.
- On cancellation, files **created by that run** are deleted. Unrelated files in the output folder are left alone.

#### `merge_pdfs(input_paths, output_path, passwords=None, progress=None, cancel=None) -> Path`

Appends every page of every input PDF, in list order, into one PDF.

- At least one input is required by the core (the GUI requires at least two).
- `passwords`, when supplied, must have the same length as `input_paths`; each entry is the password for the corresponding file.
- Encrypted inputs without a correct password raise `EncryptedPdfError`.

#### `rotate_pages(input_path, output_path, degrees, indices=None, password=None, progress=None, cancel=None) -> Path`

Rotates selected pages clockwise.

- `degrees` must be an integer multiple of 90.
- When `indices` is `None`, every page is rotated.
- Rotation is cumulative with any rotation already stored on a page.
- The GUI offers 90°, 180°, and 270°.

### 5.3 PDF rendering — `core/render.py`

Rendering uses `pypdfium2`, which bundles PDFium. No Poppler installation is needed.

PDFium is not safe to call concurrently from several threads. Because the GUI can render a preview while a conversion is running, every PDFium call in `core/render.py` is serialised through a process-wide re-entrant lock. Rendering remains correct and stable when preview and operation threads overlap.

#### `render_pages(input_path, output_dir, indices=None, dpi=150, image_format="png", quality=90, password=None, prefix=None, progress=None, cancel=None) -> list[Path]`

Renders selected pages to PNG or JPEG files.

- `image_format` accepts `"png"`, `"jpeg"`, or `"jpg"`.
- `dpi` must be greater than 0.
- `quality` must be between 1 and 100 (used for JPEG).
- Output names are `<prefix>_page_<number>.<ext>`, where `<number>` is the **1-based page number** and `<ext>` is `png` or `jpg`. The prefix defaults to the input stem.
- When `indices` is `None`, every page is rendered.
- Files are written atomically. On cancellation, files created by that run are removed.

#### `render_page_image(input_path, index, dpi=150, password=None) -> PIL.Image.Image`

Renders a single 0-based page and returns a PIL image. Useful for integrations and previews.

#### `render_thumbnail(input_path, index, max_size=256, password=None) -> PIL.Image.Image`

Renders one page scaled so its longest side is at most `max_size` pixels.

#### `render_thumbnails(input_path, max_pages=12, max_size=120, password=None, progress=None, cancel=None) -> list[PIL.Image.Image]`

Renders the first `max_pages` pages as small thumbnails. The GUI preview strip uses the defaults (12 pages, 120 px).

### 5.4 Images → PDF — `core/images.py`

`images_to_pdf(image_paths, output_path, page_size="a4", fit="contain", dpi=150, background="white", quality=90, progress=None, cancel=None) -> Path`

Combines images into a single PDF, preserving list order.

Supported page sizes (dimensions in PostScript points, 1/72 inch):

| Preset | Width × Height |
|---|---|
| `a3` | 841.89 × 1190.55 |
| `a4` | 595.28 × 841.89 |
| `a5` | 419.53 × 595.28 |
| `letter` | 612.0 × 792.0 |
| `legal` | 612.0 × 1008.0 |
| `None` | Page sized from the image pixels at the chosen DPI |

Fit modes:

| Mode | Behaviour |
|---|---|
| `contain` | Scale the image to fit inside the page, letterboxing with the background colour |
| `cover` | Scale the image to cover the page, centre-cropping the overflow |
| `stretch` | Resize the image to exactly fill the page, ignoring aspect ratio |

Other options:

- `background` accepts `"white"`, `"black"`, or an `(R, G, B)` tuple with values 0–255.
- Transparent images are composited onto the background.
- EXIF orientation is applied before placement.
- `quality` controls JPEG quality for embedded images.
- `dpi` controls the pixel dimensions used to lay images onto page-sized pages and is stored in the PDF.

### 5.5 Text extraction — `core/text.py`

#### `extract_text_per_page(input_path, indices=None, password=None, progress=None, cancel=None) -> list[str]`

Returns the extracted text of each selected page, in selection order. Pages with no text return an empty string.

#### `extract_text(...) -> str`

Joins the selected pages with a blank line between pages.

#### `extract_text_to_file(input_path, output_path, indices=None, password=None, progress=None, cancel=None) -> Path`

Extracts text and writes it to `output_path` as UTF-8, atomically.

Text extraction currently uses `pypdf`'s text layer. It does **not** perform OCR, so scanned image-only PDFs produce empty strings. `pdfminer.six` is declared in the requirements for the planned layout-aware Markdown work in Phase 4.

### 5.6 Password-protected PDFs

`open_pdf(path, password=None)` is the shared entry point for PDF reading:

- If the PDF is unencrypted, it opens normally.
- If it is encrypted and no password is supplied, it raises `EncryptedPdfError`.
- If a password is supplied but wrong, it raises `EncryptedPdfError` with a distinct message.
- Rendering uses a separate PDFium open path but applies the same error semantics.

Every core operation accepts `password=` or, for merge, a `passwords=` sequence. Passwords are used only in memory and are never written to settings or logs.

### 5.7 Atomic output writes — `core/io.py`

All file outputs go through `atomic_output(path, suffix=".tmp")`:

1. Create the destination directory if needed.
2. Create a temporary file **in the destination directory** (same filesystem).
3. Write the complete output to the temporary file.
4. `os.replace()` the temporary file onto the target.
5. On any exception, delete the temporary file and leave the target untouched.

Consequences:

- A crash or cancellation never leaves a half-written PDF or image at the target path.
- Replacing an existing file is atomic.
- The temporary file is hidden (prefix `.<target-name>.`) and cleaned up on failure.

### 5.8 Progress and cancellation — `core/progress.py`

The core defines two lightweight callback types:

```python
ProgressCallback = Callable[[int, int], None]   # (current, total)
CancelCallback   = Callable[[], bool]           # True means "stop now"
```

Operations call `check_cancel(cancel)` before each unit of work and `report(progress, current, total)` after it. Cancellation is **cooperative**: an operation stops at the next checkpoint and raises `OperationCancelled`.

Cleanup guarantees:

| Operation | On cancellation |
|---|---|
| `extract_pages` | No output file is created (atomic write happens at the end) |
| `split_pdf` | Files created by this run are deleted; unrelated files remain |
| `render_pages` | Files created by this run are deleted; unrelated files remain |
| `images_to_pdf` | No output file is created |
| `extract_text_per_page` / `extract_text` | Raises before returning; no file output |
| `extract_text_to_file` | No output file is created |

### 5.9 Error model — `core/errors.py`

All user-facing errors derive from `PdfPadError`:

```
PdfPadError
├── RangeSpecError        (also a ValueError)
├── PdfOperationError
│   └── EncryptedPdfError
├── OperationCancelled
├── UnsupportedFileError
└── OfficeUnavailableError   (reserved for Phase 3)
```

| Exception | Meaning |
|---|---|
| `RangeSpecError` | Invalid page selection or page index |
| `PdfOperationError` | A PDF could not be read, written, or manipulated |
| `EncryptedPdfError` | A PDF is encrypted and the password is missing or wrong |
| `OperationCancelled` | The user cancelled a long-running operation |
| `UnsupportedFileError` | A file is missing or not a supported format |
| `OfficeUnavailableError` | The optional LibreOffice add-on is not installed (reserved) |

Programming errors such as an unsupported DPI, fit mode, or image format raise `ValueError`/`TypeError` instead, because they indicate a caller bug rather than a user-facing condition. The GUI validates options before starting, so users see friendly `RequestError` messages rather than raw programming exceptions.

### 5.10 Core usage examples

```python
from core.pages import extract_pages, merge_pdfs, split_pdf
from core.ranges import parse_ranges

# Extract pages 1-3 and 7 from a 10-page PDF.
indices = parse_ranges("1-3,7", total=10)      # [0, 1, 2, 6]
extract_pages("input.pdf", indices, "selected.pdf")

# Split into chunks of two pages.
outputs = split_pdf("input.pdf", "chunks", chunk_size=2)

# Merge with one encrypted input.
merge_pdfs(
    ["secret.pdf", "appendix.pdf"],
    "merged.pdf",
    passwords=["hunter2", None],
)
```

```python
from core.render import render_pages
from core.images import images_to_pdf
from core.text import extract_text_to_file

# Render pages 1 and 4 at 200 DPI as JPEG.
render_pages("input.pdf", "images", indices=[0, 3], dpi=200, image_format="jpeg")

# Combine images onto A4 pages, cropping to fill.
images_to_pdf(
    ["scan-1.png", "scan-2.png"],
    "scans.pdf",
    page_size="a4",
    fit="cover",
)

# Save the text of pages 1-2.
extract_text_to_file("input.pdf", "notes.txt", indices=[0, 1])
```

```python
from core.errors import OperationCancelled
from core.pages import extract_pages

def progress(current, total):
    print(f"{current}/{total}")

cancelled = False
def cancel():
    return cancelled

try:
    extract_pages(
        "large.pdf", list(range(500)), "out.pdf",
        progress=progress, cancel=cancel,
    )
except OperationCancelled:
    print("Stopped; no partial output was written.")
```

---

## 6. Phase 2 — PySide6 GUI

Phase 2 turns the core library into a desktop application. The GUI is built with PySide6 (Qt 6) and runs on Linux with the `xcb` platform plugin in normal use and the `offscreen` plugin in tests.

### 6.1 Entry points

| Command | Module | Effect |
|---|---|---|
| `python -m gui` | `gui/__main__.py` → `gui.app.main` | Starts logging, creates `QApplication`, shows `MainWindow` |
| `pdfpad` | `pyproject.toml` console script | Same as above after installation |
| `python -m gui.app` | `gui/app.py` | Same as above |

`gui.app.create_application()` sets the organization name `pdfpad`, application name `PDFPad`, and version `0.2.0`. It reuses an existing `QApplication` if one is already present, which keeps tests and embedded use straightforward.

### 6.2 Main window layout

The window is a horizontal splitter with an input side and an operation side.

```
┌─────────────────────────────────────────────────────────────────────┐
│ PDFPad — Offline PDF Toolkit                                        │
├───────────────────────────────┬─────────────────────────────────────┤
│ Input files                   │ Operation                           │
│ ┌───────────────────────────┐ │ [Extract pages ▾]                   │
│ │ three.pdf                 │ │ Copy selected pages into a new PDF. │
│ │ photo.png                 │ │                                     │
│ │                           │ │ Pages: [1-3,5              ]         │
│ │                           │ │ Page numbers are 1-based …          │
│ └───────────────────────────┘ │                                     │
│ [Add files…] [Remove] [Clear] │ Output                              │
│                               │ Output file: [three_extracted.pdf]  │
│ Preview                       │ [Browse…]                           │
│ ┌───────────────────────────┐ │                                     │
│ │ [thumb] [thumb] [thumb]   │ │ [ Run ]                             │
│ └───────────────────────────┘ │                                     │
│                               │ Progress                            │
│                               │ [██████████████░░░░]  Working… 2/3  │
│                               │ [Cancel] [Open output folder]       │
├───────────────────────────────┴─────────────────────────────────────┤
│ Ready.                                                              │
└─────────────────────────────────────────────────────────────────────┘
```

Default size is 1120 × 760; minimum size is 880 × 620. A status bar shows transient operation descriptions and completion messages.

### 6.3 Input panel — `gui/widgets/drop_list.py`

`FileDropList` is a `QListWidget` that accepts drag-and-drop from the file manager and filters input:

- Accepts `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff`, and `.gif`.
- Rejects unsupported extensions and missing files; rejected paths are reported to the main window and shown in the status label.
- Skips duplicates by resolved path.
- Keeps list order, which matters for merge and images → PDF.
- Supports multi-selection; `Delete` or `Backspace` removes selected rows.
- Emits `filesChanged` when the list changes and `rejected(list[str])` for ignored files.

The input panel also provides **Add files…**, **Remove selected**, and **Clear** buttons.

### 6.4 Preview strip — `gui/widgets/preview.py`

`PreviewStrip` shows thumbnails of the currently selected file:

- For PDFs, a `PreviewWorker` runs in the thread pool and renders up to 12 pages at 120 px using `render_thumbnails`.
- For images, the image is loaded directly and scaled to 120 px high.
- A generation counter discards stale results when the selection changes quickly.
- A status line shows page count, “Rendering preview…”, or an error message.
- Encrypted PDFs cannot be previewed until a password is entered for an operation; the preview shows the encryption error instead of prompting.

`pil_to_pixmap(image)` converts a PIL image to a `QPixmap`. It copies the underlying buffer so the pixmap does not reference temporary Python memory.

### 6.5 Operation panel — `gui/options_panel.py`

The panel contains an operation combo box, a short description, a stacked widget with one form per operation, an output field with a **Browse…** button, and the **Run** button.

| Operation | Inputs | Output | Form controls |
|---|---|---|---|
| Extract pages | exactly one PDF | file | Page range |
| Split PDF | exactly one PDF | folder | Pages per file (1–1000) |
| Merge PDFs | at least two PDFs | file | None (uses list order) |
| Rotate pages | exactly one PDF | file | Rotation 90/180/270; page range |
| PDF to images | exactly one PDF | folder | Page range; DPI 36–600; PNG/JPEG; JPEG quality 1–100 |
| Images to PDF | one or more images | file | Page size; fit mode; DPI 36–600; image quality 1–100 |
| Extract text | exactly one PDF | file | Page range |

Behaviour details:

- Default output names are derived from the first input file. For `report.pdf`, the defaults are `report_extracted.pdf`, `report_pages/`, `report_merged.pdf`, `report_rotated.pdf`, `report_images/`, `report_images.pdf`, and `report.txt`.
- The output label switches between “Output file” and “Output folder”.
- **Browse…** uses a save dialog for files and a directory dialog for folders. File filters match PDF or text output.
- The JPEG quality spin box is enabled only when the render format is JPEG.
- While an operation runs, the operation combo, forms, output field, browse button, and run button are disabled.

`collect_options()` returns an `OperationOptions` dataclass containing the page range, chunk size, rotation, DPI, format, quality, page size, fit, and output path. Display values are translated by `gui.operations.build_request()`.

### 6.6 Qt-free request builder — `gui/operations.py`

This module is intentionally free of Qt imports. It defines:

- `OperationSpec` / `OPERATIONS` — key, label, input kind (`pdf`, `pdfs`, `images`), output kind (`file`, `dir`), default suffix, description.
- `OperationOptions` — plain dataclass of UI values.
- `OperationRequest` — the core function, keyword arguments, and output path.
- `build_request(key, files, options, passwords=None)` — validation and mapping.

Validation performed before an operation starts:

- At least one file is present and every file exists.
- Single-PDF operations receive exactly one PDF.
- Merge receives at least two PDFs.
- Images → PDF receives only supported images.
- Output is present, has a sensible suffix, is not an input file, and is a folder when the operation writes multiple files.
- Page ranges parse successfully against the real page count.
- Chunk size, rotation, DPI, quality, format, page size, and fit values are valid.

`build_request` raises `RequestError` for selection/option problems and lets `PdfPadError` subclasses propagate for unreadable or encrypted PDFs. The main window catches both and shows a dialog.

### 6.7 Background execution — `gui/workers.py`

`OperationWorker` is a `QRunnable` that runs exactly one core operation on the global thread pool.

```python
class WorkerSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str, str)      # user message, traceback/details
    cancelled = Signal()
```

The worker:

- Injects `progress=` and `cancel=` into every core call.
- Converts `OperationCancelled` into the `cancelled` signal.
- Converts `PdfPadError` into `failed(message, "")`.
- Converts any other exception into `failed("Unexpected error while processing the files.", traceback)`.
- Emits `finished(result)` on success.

Cancellation uses a `threading.Event`; `worker.cancel()` sets it and core checkpoints observe it. The GUI allows only one active worker at a time.

### 6.8 Progress and cancellation in the GUI

- When an operation starts, the progress bar becomes visible and indeterminate (`range 0,0`), and the **Cancel** button appears.
- As progress signals arrive, the bar switches to determinate mode (`range 0,total`) and shows `Working… current/total`.
- **Cancel** asks the worker to stop and disables itself. The operation stops at its next checkpoint, partial outputs are cleaned up by the core, and the status becomes “Cancelled.”
- On success, the bar and cancel button hide, and the status shows either “Done — saved …” or “Done — created N file(s) in …”.
- **Open output folder** becomes visible after a successful run and opens the relevant folder through the desktop environment.
- Closing the window while an operation is running requests cancellation before the window closes.

### 6.9 Password handling

`MainWindow._resolve_passwords()` checks each PDF with `page_count()`:

- Unencrypted PDFs are skipped.
- An `EncryptedPdfError` opens a masked `QInputDialog` showing the file name.
- The user has up to three attempts per file.
- Cancelling the dialog aborts the whole run with “Cancelled.”
- Three wrong attempts show a critical dialog and abort.
- Successful passwords are passed to `build_request` as a `{Path: str}` mapping and then to the core operation. Merge receives one password per input in list order.

### 6.10 Settings and logging

**Settings** use `QSettings` in INI format with organization and application name `pdfpad`. On Linux this resolves to `~/.config/pdfpad/pdfpad.ini` (respecting `XDG_CONFIG_HOME`). Stored keys:

| Key | Value |
|---|---|
| `window/geometry` | Saved window geometry |
| `files/last_dir` | Last folder used in the file dialog |
| `operation/last` | Last selected operation key |

Settings are saved on window close.

**Logging** is configured by `gui.app.setup_logging()`:

- Directory: `$XDG_STATE_HOME/pdfpad/` or `~/.local/state/pdfpad/`.
- File: `pdfpad.log`.
- Rotating handler: 1,000,000 bytes per file, three backups, UTF-8.
- Format: `%(asctime)s %(levelname)s %(name)s: %(message)s`.
- Current log content is mostly startup information; the structure is ready for per-operation logging in later phases.

### 6.11 Error handling and user feedback

| Situation | Feedback |
|---|---|
| No files | Warning dialog “No input files” |
| Unsupported files dropped | Status label listing ignored names |
| Invalid options or file selection | Critical dialog “Cannot start” with the validation message |
| Encrypted PDF | Password dialog, up to three attempts |
| Core operation failure | Critical dialog “Operation failed”; unexpected exceptions include traceback details |
| Cancellation | Status label “Cancelled.” |
| Success | Status label and status bar; “Open output folder” button |

Success is deliberately non-modal so batch-style repeated work stays fast; failures are modal so they cannot be missed.

---

## 7. Installation, launch, and usage

### 7.1 Requirements

- Linux x86_64.
- glibc 2.34 or newer (Ubuntu 22.04, Linux Mint 21, or newer).
- Python 3.10 or newer (development and tests used Python 3.12.3).
- A desktop session with the Qt `xcb` platform plugin. Minimal systems may need the usual Qt runtime libraries (`libGL`, `libxkbcommon`, `libxcb-*`). These are OS libraries, not conversion binaries.

### 7.2 Install from the repository

```bash
cd pdfpad
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes the runtime requirements plus `pytest` and `pytest-qt`.

For an editable install with the `pdfpad` command:

```bash
.venv/bin/pip install -e .
```

### 7.3 Run

```bash
# From the project root, without installing:
.venv/bin/python -m gui

# Or, after an editable install:
.venv/bin/pdfpad
```

### 7.4 Typical workflows

**Extract selected pages**

1. Add a PDF with **Add files…** or drag it in.
2. Choose **Extract pages**.
3. Enter a range such as `1-3,7` (leave empty for all pages).
4. Keep or change the default output path.
5. Click **Run**. The status shows the saved file.

**Split a PDF**

1. Add the PDF and choose **Split PDF**.
2. Set “Pages per file” (1 creates one PDF per page).
3. Choose an output folder.
4. Click **Run**.

**Merge PDFs**

1. Add two or more PDFs in the desired order.
2. Choose **Merge PDFs**.
3. Pick an output file and run.

**Rotate pages**

1. Add a PDF and choose **Rotate pages**.
2. Select 90°, 180°, or 270°.
3. Optionally enter a page range; leave empty to rotate all pages.

**PDF → images**

1. Add a PDF and choose **PDF to images**.
2. Optionally enter a page range.
3. Choose DPI, PNG or JPEG, and JPEG quality.
4. Choose an output folder and run.

**Images → PDF**

1. Add images in the desired order.
2. Choose **Images to PDF**.
3. Choose page size (`A4`, `A5`, `A3`, `Letter`, `Legal`, or original size).
4. Choose fit (`Contain`, `Cover`, or `Stretch`), DPI, and quality.
5. Choose an output PDF and run.

**Extract text**

1. Add a PDF and choose **Extract text**.
2. Optionally enter a page range.
3. Choose an output `.txt` file and run.

**Password-protected PDFs**

Any PDF operation prompts for the password when needed. Merge prompts once per encrypted input. Cancelling the prompt aborts the run; three wrong attempts abort with an error.

### 7.5 Running the tests

```bash
.venv/bin/python -m pytest -q
```

The suite sets `QT_QPA_PLATFORM=offscreen` and temporary `XDG_CONFIG_HOME` / `XDG_STATE_HOME` values in `tests/conftest.py`, so it does not open windows or touch the real user configuration.

To run one file or one test:

```bash
.venv/bin/python -m pytest tests/test_gui.py -q
.venv/bin/python -m pytest tests/test_operations.py::test_build_extract_request -q
```

---

## 8. Testing and quality assurance

### 8.1 Test totals

**236 tests pass** in the current tree. The suite takes roughly 3–5 seconds on the development machine.

| Test file | Tests | Focus |
|---|---:|---|
| `tests/test_ranges.py` | 42 | Page-selection grammar, validation, type errors |
| `tests/test_pages.py` | 25 | Extract, split, merge, rotate, encryption, missing/corrupt files |
| `tests/test_images.py` | 18 | Page sizes, fit modes, transparency, option validation |
| `tests/test_render.py` | 16 | PNG/JPEG rendering, DPI, subsets, thumbnails, encryption, concurrent safety |
| `tests/test_progress.py` | 15 | Progress events and cancellation cleanup |
| `tests/test_io.py` | 5 | Atomic writes, replacement, failure cleanup, text output |
| `tests/test_text.py` | 8 | Per-page text, joining, file output, encryption |
| `tests/test_operations.py` | 69 | Qt-free request builder, defaults, validation, mappings, encrypted PDFs, execution of every operation |
| `tests/test_workers.py` | 8 | Worker success, progress, errors, traceback, cancellation, single terminal signal |
| `tests/test_gui.py` | 30 | Window construction, file list, output defaults, option collection, end-to-end runs, password flows, previews |
| **Total** | **236** | |

### 8.2 Test fixtures

`tests/pdf_fixtures.py` generates small deterministic files at test time:

- `make_pdf(path, page_sizes, texts)` — blank pages with distinct sizes, optionally with Helvetica text.
- `make_text_pdf(path, texts)` — one text string per page.
- `make_encrypted_pdf(path, password)` — an encrypted multi-page PDF.
- `make_image(path, size, color, mode)` — PNG images with controlled dimensions and colours.

Distinct page widths make ordering assertions unambiguous. No binary fixtures are committed, so the suite is easy to audit and portable.

### 8.3 Headless GUI testing

`tests/conftest.py` sets environment variables **before** any test module imports PySide6:

- `QT_QPA_PLATFORM=offscreen` — no display server required.
- `XDG_CONFIG_HOME` and `XDG_STATE_HOME` — point at a temporary directory so tests never write to the real home directory.

`pytest-qt` provides `qtbot`, `waitSignal`, and `waitUntil`. GUI tests use `qtbot.addWidget()` for cleanup and wait for real signals rather than sleeping:

- Worker tests wait on `finished`, `failed`, or `cancelled`.
- End-to-end GUI tests click **Run** and wait until the output file exists.
- Password tests monkeypatch `QInputDialog.getText` and `QMessageBox` to avoid blocking dialogs.

### 8.4 What is verified

**Core correctness**

- Selection grammar: valid forms, open ranges, separators, duplicates, reversed ranges, out-of-bounds, malformed input, type errors.
- Page operations: order preservation, duplicate indices, chunking, cumulative rotation, parent-directory creation, encrypted inputs, wrong passwords, corrupt files.
- Rendering: exact output names, DPI scaling, JPEG conversion to RGB, custom prefixes, thumbnail sizing, invalid options, and safe concurrent rendering from several threads.
- Images → PDF: A4 default, original-size mode, custom sizes, all three fit modes, transparency, background tuples, invalid options.
- Text: per-page extraction, joining, subset order, UTF-8 file output, blank pages, encryption.
- Atomic I/O: target not visible before commit, replacement, failure keeps the old file, temporary files removed.

**GUI and integration**

- The request builder produces the exact core kwargs for all seven operations.
- Page-size, fit, and format display values map correctly.
- Output suffix normalization, default naming, overwrite rejection, and folder/file validation.
- Progress callbacks fire once per page/image/chunk.
- Cancellation raises `OperationCancelled`, leaves no partial output, and removes only files created by the cancelled run.
- The worker emits the right terminal signal and includes tracebacks for unexpected errors.
- The main window builds, lists operations, filters files, switches defaults, collects options, and runs extract/text/render end to end.
- Password prompt success, cancel, and three-wrong-attempts paths.
- PIL → QPixmap conversion for RGB and RGBA images; image preview and clear.

### 8.5 Manual smoke test performed

In addition to the automated suite, the application was started headlessly with the real bootstrap code:

```bash
QT_QPA_PLATFORM=offscreen \
XDG_CONFIG_HOME=/tmp/.../config \
XDG_STATE_HOME=/tmp/.../state \
.venv/bin/python -c "from gui.app import main; main()"
```

The window constructed with the expected title, all seven operations, and the settings file at the temporary `XDG_CONFIG_HOME`. Logging wrote to the temporary `XDG_STATE_HOME`, and shutdown completed cleanly.

### 8.6 Quality practices

- **Generated fixtures** instead of opaque binary test data.
- **No network in tests.** Everything runs locally.
- **Temporary directories** for all outputs and settings.
- **No arbitrary sleeps** in GUI tests; signals and polling conditions are used.
- **Separation of pure logic**: `gui/operations.py` can be tested without Qt, which keeps most validation tests fast and deterministic.
- **Atomic output tests** explicitly verify that failed operations preserve the previous target.

---

## 9. Design decisions and rationale

### 9.1 Why pypdf, pypdfium2, and Pillow

- `pypdf` is pure Python, permissively licensed, and handles page copying, merging, rotation, and encryption without external tools.
- `pypdfium2` bundles PDFium, so rendering is fast and does not require Poppler or system fonts to be installed. This is central to the “no system binaries” requirement. Because PDFium is not thread-safe, all PDFium work is serialised with a process-wide lock so previews and conversions can overlap safely.
- `Pillow` handles the image side: decoding many formats, applying EXIF orientation, compositing transparency, resizing, and writing image-based PDFs.

### 9.2 Why PySide6 instead of Flask

The application is a desktop tool, not a web service. PySide6 provides native widgets, drag-and-drop, file dialogs, background threading, settings, and a packaged Qt runtime. Dropping Flask also removes a local HTTP server from the security and packaging story.

### 9.3 Why `PySide6-Essentials`

Only Qt Widgets, Qt Core, and Qt Gui are needed. `PySide6-Essentials` provides those without the larger optional modules, reducing install and packaging size.

### 9.4 Why atomic writes

PDF and image writes can be large and can fail midway. Writing to a temporary file and renaming ensures the user never sees a truncated PDF and never loses an existing file because of a failed replacement. Keeping the temporary file in the destination directory guarantees that `os.replace` stays on the same filesystem and is atomic.

### 9.5 Why cooperative cancellation

Thread termination is unsafe: it can leave file handles open and bypass cleanup. Instead, operations check a predicate at page/image/file boundaries and raise a dedicated exception. This gives deterministic cleanup and keeps the core library free of threading primitives.

### 9.6 Why a Qt-free request builder

Putting validation and option mapping in `gui/operations.py` means:

- Most GUI logic is testable without a display server.
- Core functions stay free of UI concerns.
- Error messages are consistent between pre-flight validation and core errors.
- A future CLI can reuse the same operation metadata and mapping.

### 9.7 Why 1-based page numbers

Users think in 1-based page numbers; PDF libraries think in 0-based indices. The GUI and `parse_ranges` expose 1-based values, while core APIs accept 0-based indices for programmatic use. The boundary is explicit and documented.

### 9.8 Why Linux-first paths

Settings and logs follow the XDG base-directory conventions:

- Config: `$XDG_CONFIG_HOME/pdfpad/pdfpad.ini` (default `~/.config/pdfpad/pdfpad.ini`).
- State/logs: `$XDG_STATE_HOME/pdfpad/pdfpad.log` (default `~/.local/state/pdfpad/pdfpad.log`).

This keeps the application well-behaved on Linux desktops and makes tests easy to isolate with temporary environment variables.

### 9.9 Why no Office or compression in Phase 2

Office conversion requires a large optional LibreOffice add-on pack, and compression needs `pikepdf` and careful lossy-mode warnings. Both are substantial enough to deserve their own phase. Phase 2 focuses on making the core features reliable and usable through the GUI.

---

## 10. Limitations and known issues

### 10.1 Feature limitations

- **No OCR.** Text extraction reads the PDF text layer. Scanned image-only PDFs produce empty text.
- **No Office → PDF yet.** DOCX/XLSX/PPTX conversion is planned for Phase 3 as an optional LibreOffice add-on.
- **No compression yet.** Lossless and rasterize modes are planned for Phase 3.
- **No Markdown export yet.** Plain text is available; layout-aware Markdown is planned for Phase 4.
- **No packaging yet.** There is no AppImage, `.deb`, portable tarball, desktop entry, or icon installation in the current tree. The app runs from a Python environment.
- **Linux only.** The code uses Linux path conventions and has not been tested on Windows or macOS.

### 10.2 Behavioural caveats

- **Output overwrites are atomic but not confirmed.** The GUI prevents an output path from being exactly the same as an input file, but it does not ask before replacing some other existing file. `split_pdf` and `render_pages` overwrite same-named files in the output folder atomically.
- **Cancellation does not restore an already-overwritten file.** If a split/render run overwrites a pre-existing file and is then cancelled, the overwritten file keeps the new content. Files newly created by the cancelled run are removed.
- **Preview of encrypted PDFs does not prompt.** The preview strip shows an encryption error; the password dialog appears only when an operation runs.
- **Preview shows at most 12 pages.** This keeps the UI responsive for large documents.
- **Password attempts are limited to three per file.** There is no password manager or saved-password feature.
- **Rotation in the GUI is limited to 90°, 180°, and 270° clockwise.** The core accepts any multiple of 90.
- **Merge requires at least two files in the GUI.** The core accepts one or more.
- **No undo.** Operations write new files; the application does not maintain a history.
- **Errors are modal.** Operation failures use a critical dialog; this is intentional but may interrupt batch workflows.

### 10.3 Platform caveats

- The glibc ≥ 2.34 floor excludes older distributions.
- Qt’s `xcb` platform plugin may require OS libraries on minimal installations. This is the most likely clean-machine startup issue.
- The project has not yet been validated in an air-gapped VM or with `unshare -n`; that is Phase 6 work.

### 10.4 Unused dependency

`pdfminer.six` is declared in `requirements.txt` and `pyproject.toml` but is not imported by the current code. It is reserved for Phase 4 Markdown extraction. It does not affect runtime behaviour or network isolation.

---

## 11. Roadmap: Phase 3 and beyond

### Phase 3 — Compression and Office conversion

- Add `core/compress.py` using `pikepdf`:
  - Lossless object-stream and metadata cleanup.
  - Optional image downsampling.
  - Optional rasterize mode with an explicit warning that text becomes unsearchable.
- Add `core/office.py`:
  - Detect the optional LibreOffice add-on pack.
  - Run headless with an isolated `UserInstallation` profile.
  - Expose capability states in the GUI; disable Office conversion when the add-on is absent.
- Add GUI forms and tests for both features.
- Extend the request builder and worker mappings.

### Phase 4 — Markdown export

- Use `pdfminer.six` layout analysis to produce best-effort Markdown.
- Preserve headings, paragraphs, lists, and simple tables where possible.
- Document fidelity limits clearly; Markdown output is heuristic, not lossless.

### Phase 5 — Packaging

- PyInstaller `--onedir` specification.
- Portable tarball and `install.sh`.
- `.desktop` entry, icon, MIME association.
- License collection for bundled wheels and PDFium.
- Optional `.deb`; AppImage deferred.

### Phase 6 — Air-gap and robustness validation

- Run under `unshare -n` to prove no network access.
- Test on a clean VM matching the minimum glibc baseline.
- Exercise large PDFs, encrypted PDFs, malformed files, and cancellation.
- Verify temporary-file cleanup and repeated-run behaviour.

---

## 12. Project file map

```
pdfpad/
├── core/
│   ├── __init__.py          # Public error exports and parse_ranges
│   ├── errors.py            # PdfPadError hierarchy
│   ├── io.py                # require_file, atomic_output, write_text
│   ├── ranges.py            # parse_ranges, validate_indices
│   ├── pages.py             # open_pdf, page_count, extract, split, merge, rotate
│   ├── render.py            # PDFium rendering, thumbnails
│   ├── images.py            # images → PDF
│   ├── text.py              # text extraction
│   └── progress.py          # progress/cancel helpers
├── gui/
│   ├── __init__.py
│   ├── __main__.py          # python -m gui
│   ├── app.py               # logging, QApplication, main()
│   ├── main_window.py       # window, password prompts, worker orchestration
│   ├── operations.py        # Qt-free operation metadata and request builder
│   ├── options_panel.py     # operation forms, output picker, run button
│   ├── workers.py           # OperationWorker and WorkerSignals
│   └── widgets/
│       ├── __init__.py
│       ├── drop_list.py     # FileDropList
│       └── preview.py       # PreviewStrip, PreviewWorker, pil_to_pixmap
├── tests/
│   ├── conftest.py          # offscreen Qt, temp XDG dirs, fixtures
│   ├── pdf_fixtures.py      # generated PDF/image helpers
│   ├── test_ranges.py
│   ├── test_pages.py
│   ├── test_render.py
│   ├── test_images.py
│   ├── test_text.py
│   ├── test_io.py
│   ├── test_progress.py
│   ├── test_operations.py
│   ├── test_workers.py
│   └── test_gui.py
├── report/
│   └── PDFPad-Phase1-2-Report.md   # this document
├── README.md
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

---

## Appendix A — Core API quick reference

### Page selection

| Function | Signature |
|---|---|
| `parse_ranges` | `(spec: str, total: int) -> list[int]` |
| `validate_indices` | `(indices: Iterable[int], total: int) -> list[int]` |

### Pages

| Function | Signature |
|---|---|
| `open_pdf` | `(path, password=None) -> PdfReader` |
| `page_count` | `(path, password=None) -> int` |
| `extract_pages` | `(input_path, indices, output_path, password=None, progress=None, cancel=None) -> Path` |
| `split_pdf` | `(input_path, output_dir, chunk_size=1, password=None, progress=None, cancel=None) -> list[Path]` |
| `merge_pdfs` | `(input_paths, output_path, passwords=None, progress=None, cancel=None) -> Path` |
| `rotate_pages` | `(input_path, output_path, degrees, indices=None, password=None, progress=None, cancel=None) -> Path` |

### Rendering

| Function | Signature |
|---|---|
| `render_page_image` | `(input_path, index, dpi=150, password=None) -> PIL.Image.Image` |
| `render_thumbnail` | `(input_path, index, max_size=256, password=None) -> PIL.Image.Image` |
| `render_thumbnails` | `(input_path, max_pages=12, max_size=120, password=None, progress=None, cancel=None) -> list[PIL.Image.Image]` |
| `render_pages` | `(input_path, output_dir, indices=None, dpi=150, image_format="png", quality=90, password=None, prefix=None, progress=None, cancel=None) -> list[Path]` |

### Images and text

| Function | Signature |
|---|---|
| `images_to_pdf` | `(image_paths, output_path, page_size="a4", fit="contain", dpi=150, background="white", quality=90, progress=None, cancel=None) -> Path` |
| `extract_text_per_page` | `(input_path, indices=None, password=None, progress=None, cancel=None) -> list[str]` |
| `extract_text` | `(input_path, indices=None, password=None, progress=None, cancel=None) -> str` |
| `extract_text_to_file` | `(input_path, output_path, indices=None, password=None, progress=None, cancel=None) -> Path` |

### GUI request builder

| Name | Purpose |
|---|---|
| `OPERATIONS` | Tuple of `OperationSpec` entries for all seven GUI operations |
| `OPERATIONS_BY_KEY` | Lookup by operation key |
| `OperationOptions` | Dataclass of collected UI values |
| `OperationRequest` | Core function + kwargs + output path |
| `default_output(key, files)` | Default output path for an operation |
| `build_request(key, files, options, passwords=None)` | Validate and build a core call |
| `RequestError` | Pre-flight validation failure |

### Error types

| Name | Base |
|---|---|
| `PdfPadError` | `Exception` |
| `RangeSpecError` | `PdfPadError`, `ValueError` |
| `PdfOperationError` | `PdfPadError` |
| `EncryptedPdfError` | `PdfOperationError` |
| `OperationCancelled` | `PdfPadError` |
| `UnsupportedFileError` | `PdfPadError` |
| `OfficeUnavailableError` | `PdfPadError` (reserved) |

---

## Appendix B — Naming and format conventions

### Accepted input extensions

| Kind | Extensions |
|---|---|
| PDF | `.pdf` |
| Images | `.bmp`, `.gif`, `.jpeg`, `.jpg`, `.png`, `.tif`, `.tiff`, `.webp` |

### Output naming

| Operation | Pattern | Example |
|---|---|---|
| Extract | `<stem>_extracted.pdf` | `report_extracted.pdf` |
| Split | `<stem>_pages_<first>-<last>.pdf` | `report_pages_1-2.pdf` |
| Merge | `<stem>_merged.pdf` (first input stem) | `report_merged.pdf` |
| Rotate | `<stem>_rotated.pdf` | `report_rotated.pdf` |
| Render | `<prefix>_page_<number>.<ext>` | `report_page_3.png`, `report_page_3.jpg` |
| Images → PDF | `<stem>_images.pdf` (first image stem) | `scan_images.pdf` |
| Text | `<stem>.txt` | `report.txt` |

### Page numbering

| Layer | Numbering |
|---|---|
| User-facing ranges and GUI | 1-based, inclusive |
| `parse_ranges` output | 0-based indices |
| Core `indices` arguments | 0-based |
| Rendered file names | 1-based page numbers |
| Split file names | 1-based first/last page numbers |

### Format values

| UI display | Core value |
|---|---|
| `A3` | `"a3"` |
| `A4` | `"a4"` |
| `A5` | `"a5"` |
| `Letter` | `"letter"` |
| `Legal` | `"legal"` |
| `Original size` | `None` |
| `Contain` | `"contain"` |
| `Cover` | `"cover"` |
| `Stretch` | `"stretch"` |
| `PNG` | `"png"` |
| `JPEG` | `"jpeg"` |

---

## Appendix C — Test inventory

### `tests/test_ranges.py` (42)

- Valid grammar: single pages, closed ranges, open ranges, comma/whitespace separators, spaces around hyphens, selection order, duplicate removal, repeated/trailing separators, overlapping ranges.
- Invalid grammar: empty, zero/negative, out-of-bounds, reversed, malformed text, bad separators, decimals, multiple hyphens.
- Type errors and negative totals.
- `validate_indices`: order/duplicate preservation, generators, out-of-range values, type errors.

### `tests/test_pages.py` (25)

- Page count.
- Extract order, duplicate indices, nested output directories, bad indices, non-integer indices.
- Merge order, empty input, password sequence length mismatch, encrypted inputs, wrong passwords.
- Split per page, chunked split, naming, bad chunk sizes.
- Rotate selected/all/cumulative pages, invalid degrees.
- Encrypted PDF password requirements and successful extraction/rotation.
- Missing and corrupt files.

### `tests/test_images.py` (18)

- A4 default, original-size mode, custom page size.
- All three fit modes.
- Transparency handling.
- Empty image list, missing files, non-images.
- Invalid page size, dimensions, fit, DPI, quality, background.
- RGB background tuples.

### `tests/test_render.py` (16)

- Render all pages, subsets in selection order, DPI scaling.
- JPEG output and RGB conversion.
- Custom prefix.
- Single-page render and thumbnail sizing.
- Out-of-range indices.
- Invalid format/DPI/quality.
- Encrypted PDF rendering.
- Nested output directory creation.
- Concurrent thumbnail rendering from several threads, verifying the PDFium lock.

### `tests/test_text.py` (8)

- Per-page extraction, joining, subset order, file output.
- Blank pages.
- Bad indices.
- Encryption and missing files.

### `tests/test_io.py` (5)

- Atomic write visibility, replacement, failure preservation, parent creation.
- UTF-8 text output.

### `tests/test_progress.py` (15)

- Progress event sequences for extract, split, render, images → PDF, text.
- Optional progress callback.
- Cancellation for each operation.
- No partial output and preservation of unrelated files.
- Cancel predicate that never trips.

### `tests/test_operations.py` (69)

- Operation metadata and suffix helpers.
- Default output names for every operation.
- Request construction for extract, split, merge, rotate, render, images → PDF, and text.
- Page-size, fit, and format mappings.
- Output suffix normalization, default output, overwrite rejection, folder validation.
- Input-count and file-type validation.
- Invalid chunk size, rotation, DPI, quality, format, page size, and fit.
- Invalid page ranges.
- Encrypted PDFs and per-file merge passwords.
- Execution of every built request.

### `tests/test_workers.py` (8)

- Result and progress signals.
- Keyword argument forwarding.
- `PdfPadError` message propagation.
- Unexpected exception message and traceback.
- `OperationCancelled` signal.
- Cancel flag observed by the operation.
- Cancel before start.
- Exactly one terminal signal.

### `tests/test_gui.py` (30)

- Window construction, operation count, initial state.
- File add/reject/duplicate/remove/clear.
- First-item selection and preview start.
- Default output for every operation.
- Output label switching.
- Render and images option collection.
- JPEG quality enable/disable.
- No-files warning and invalid-selection error.
- End-to-end extract, text, and render runs.
- Encrypted password success, cancel, and three-wrong-attempts paths.
- RGB and RGBA PIL → QPixmap conversion.
- Image preview and clear.

---

## Closing note

Phases 1 and 2 deliver a working, fully offline PDF toolkit with a reusable core and a native Linux GUI. The core is covered by deterministic tests for correctness, atomicity, encryption, progress, and cancellation. The GUI is covered by offscreen tests that exercise real widgets, real worker threads, and real output files.

The remaining planned features — compression, Office conversion, Markdown export, and packaging — build on the same architecture: core operations with explicit inputs and outputs, Qt-free request building, a background worker, and progress/cancel support. That foundation is in place and tested.
