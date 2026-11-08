# PDFPad — Phase 3 Implementation Report

**Project:** PDFPad — an offline PDF conversion desktop application for Linux  
**Version:** 0.3.0  
**Report date:** 2026-11-08  
**Target platform:** Linux x86_64, glibc ≥ 2.34 (Ubuntu 22.04 / Linux Mint 21 or newer)  
**Runtime model:** fully offline, no network calls, no system binaries required for core conversion  
**Current status:** Phase 1 (core library) complete · Phase 2 (PySide6 GUI) complete · Phase 3 (compression + Office → PDF) complete · 314 automated tests passing  

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [Product overview](#2-product-overview)
3. [Feature status matrix](#3-feature-status-matrix)
4. [Architecture](#4-architecture)
5. [Phase 3 — Compression](#5-phase-3--compression)
6. [Phase 3 — Office conversion](#6-phase-3--office-conversion)
7. [Phase 3 — GUI integration](#7-phase-3--gui-integration)
8. [Dependency inventory](#8-dependency-inventory)
9. [Testing and quality assurance](#9-testing-and-quality-assurance)
10. [Design decisions and rationale](#10-design-decisions-and-rationale)
11. [Limitations and known issues](#11-limitations-and-known-issues)
12. [Roadmap: Phase 4 and beyond](#12-roadmap-phase-4-and-beyond)
13. [Project file map](#13-project-file-map)
14. [Appendix A — Core API quick reference](#appendix-a--core-api-quick-reference)
15. [Appendix B — Naming and format conventions](#appendix-b--naming-and-format-conventions)
16. [Appendix C — Test inventory](#appendix-c--test-inventory)

---

## 1. Executive summary

PDFPad is a Linux desktop application for common PDF conversion and page-manipulation tasks. It is designed for environments where files must not leave the machine: the application makes no network requests and performs every conversion with bundled Python wheels rather than external programs such as Ghostscript, Poppler, or LibreOffice.

Phase 3 adds two new feature areas:

- **Compression** — `core/compress.py`. Two modes:
  - **Lossless** (default): rewrites the PDF with pikepdf/QPDF using object streams and Flate stream recompression. Text and vectors stay intact and searchable.
  - **Rasterize**: renders every page to a JPEG and rebuilds the PDF from those images. It can shrink scanned documents dramatically but removes the text layer, so output is no longer searchable. The GUI labels this mode explicitly.
- **Office → PDF** — `core/office.py`. An optional, decoupled LibreOffice bridge. PDFPad never requires LibreOffice; conversion is enabled only when a LibreOffice executable can be found (explicit path, `PDFPAD_LIBREOFFICE`, the bundled `office/` add-on, or a system `soffice`/`libreoffice`). The GUI exposes capability states and disables Office conversion when the add-on is absent.

Both features follow the established architecture: GUI-independent core functions with explicit inputs/outputs, Qt-free request building in `gui/operations.py`, atomic output writes, cooperative progress/cancellation, and background execution through `OperationWorker`.

The full test suite now contains **314 passing tests** (up from 236 after Phase 2) and runs headlessly through the Qt `offscreen` platform. The suite is stable across repeated runs.

---

## 2. Product overview

### 2.1 New capabilities in Phase 3

| Capability | Core API | GUI exposure | Notes |
|---|---|---|---|
| Lossless PDF compression | `core.compress.compress_pdf(mode="lossless")` | “Compress PDF” | pikepdf object streams + Flate recompression; text kept |
| Rasterize compression | `core.compress.compress_pdf(mode="rasterize")` | “Compress PDF” | Rebuilds pages as JPEG; text becomes unsearchable |
| Compression progress | `progress=` callback | Progress bar | Lossless reports QPDF's 0→100 as 1→100; rasterize maps render+assembly to `2N` |
| Compression cancellation | `cancel=` predicate | Cancel button | Temporary output is discarded; an existing output is preserved |
| Office → PDF detection | `core.office.find_libreoffice()` / `office_info()` / `office_available()` | Compress/office status label | Explicit path → env var → bundled add-on → system binary |
| Office → PDF conversion | `core.office.office_to_pdf()` | “Office to PDF” | Headless LibreOffice, isolated `UserInstallation` profile, per-document timeout |
| Office progress | `progress=` callback | Progress bar | One unit per document |
| Office cancellation | `cancel=` predicate | Cancel button | Terminates the converter process group and removes files created by the run |

### 2.2 Offline and self-contained guarantees (unchanged)

- **No network access in application code.** Core and GUI modules make no HTTP, socket, or download calls.
- **No external conversion binaries for core features.** PDF rendering uses `pypdfium2` (bundled PDFium); PDF writing and manipulation use `pypdf`; image handling uses `Pillow`; compression uses `pikepdf` (bundled QPDF).
- **All dependencies are Python wheels.** There is no runtime dependency on `poppler-utils`, `qpdf`, Ghostscript, or LibreOffice for the core features.
- **Office conversion is genuinely optional.** It only runs when a LibreOffice executable is discoverable; otherwise the operation is disabled in the GUI and `office_to_pdf` raises `OfficeUnavailableError`.
- **Local filesystem only.** Outputs are written next to the inputs or to a user-selected folder. Office inputs are staged in hidden temporary directories under the output folder, never beside the originals.

---

## 3. Feature status matrix

### 3.1 Implemented (Phases 1–3)

| # | Feature area | Status |
|---|---|---|
| 1 | Page operations (extract, split, merge, rotate) | ✅ Phase 1 core + Phase 2 GUI |
| 2 | PDF → images (PNG/JPEG, DPI, page range) | ✅ Phase 1 core + Phase 2 GUI |
| 3 | Images → PDF (order, page size, fit) | ✅ Phase 1 core + Phase 2 GUI |
| 4 | Office → PDF (optional LibreOffice add-on) | ✅ Phase 3 core + GUI |
| 5 | Compress (lossless + optional rasterize) | ✅ Phase 3 core + GUI |
| 6 | PDF → text / Markdown | ✅ text in Phases 1–2 · ⏳ Markdown in Phase 4 |

### 3.2 Planned but not yet implemented

| Capability | Planned phase | Current state |
|---|---|---|
| PDF → Markdown | Phase 4 | `pdfminer.six` declared; not yet used |
| OCR for scanned PDFs | Not in current scope | Text extraction is text-layer only |
| Packaging (`PyInstaller`, `.desktop`, installer) | Phase 5 | Not started |
| Air-gap validation (`unshare -n`, clean VM) | Phase 6 | Not yet performed |

---

## 4. Architecture

Phase 3 does not change the layered design; it adds two modules to `core/` and wires them into `gui/operations.py`, `gui/options_panel.py`, and `gui/main_window.py`.

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
└───────────────────────────┬──────────────────────────────────────────┘
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
│  compress.py   lossless / rasterize PDF compression                  │
│  office.py     optional LibreOffice bridge                           │
│  io.py         input validation + atomic output writes               │
│  progress.py   progress callback + cancellation checkpoints          │
│  errors.py     user-facing exception hierarchy                       │
│                                                                      │
│  Dependencies: pypdf · pypdfium2 · Pillow · pikepdf · pdfminer.six   │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ atomic writes (temp + os.replace)
                            ▼
                     Local filesystem
```

The end-to-end data flow from the Phase 1–2 report is unchanged, with two additions:

- `build_request("compress", …)` validates mode/dpi/quality and maps `OperationOptions.compression_mode` to `compress_pdf(mode=…)`.
- `build_request("office", …)` calls `find_libreoffice()` and raises `RequestError` when no backend is available; otherwise it forwards the discovered binary to `office_to_pdf(binary=…)`.

---

## 5. Phase 3 — Compression

### 5.1 Core API — `core/compress.py`

```python
COMPRESSION_MODES = frozenset({"lossless", "rasterize"})

def compress_pdf(
    input_path,
    output_path,
    mode="lossless",
    dpi=150,
    quality=75,
    password=None,
    progress=None,
    cancel=None,
) -> Path
```

**Lossless mode (`mode="lossless"`):**
- Opens the source with pikepdf (translating `pikepdf.PasswordError` into `EncryptedPdfError` and other `pikepdf.PdfError`/`OSError` into `PdfOperationError`).
- Saves with `compress_streams=True`, `recompress_flate=True`, and `object_stream_mode=pikepdf.ObjectStreamMode.generate`.
- QPDF's progress callback emits `0` and `100`; the wrapper normalises these to `(1, 100)` and `(100, 100)` so the GUI progress bar stays within the 1–100 range.
- The output is written through `atomic_output`. If cancellation arrives while QPDF is writing, the temporary file is discarded and the destination is left untouched.

**Rasterize mode (`mode="rasterize"`):**
- Requires `dpi > 0` and `0 < quality <= 100` (otherwise `ValueError`).
- Renders every page via `render_pages(..., image_format="jpeg")` into a private `tempfile.TemporaryDirectory`, reporting `current / (page_count * 2)` during rendering.
- Reassembles the images into a PDF via `images_to_pdf(..., page_size=None)`, reporting `(page_count + current) / (page_count * 2)` during assembly. `page_size=None` sizes each page from the rendered pixels at the chosen DPI, preserving the physical page dimensions.
- Because pages are rendered to JPEG and re-saved, the output has no text layer: extracted text is empty.

**Validation:**
- Unknown `mode` raises `ValueError`.
- Missing/corrupt input raises `UnsupportedFileError` / `PdfOperationError`.
- Output path equal to the input path raises `PdfOperationError` ("Output would overwrite the input file.").
- Encrypted input without a correct password raises `EncryptedPdfError`.

### 5.2 Lossless vs rasterize — when to use which

| Factor | Lossless | Rasterize |
|---|---|---|
| Text/searchable | Preserved | Lost (image-only pages) |
| Vectors/line art | Preserved | Rasterised |
| Typical size reduction | Modest | Can be large for scans |
| Speed | Fast (stream rewrite) | Slower (render + encode every page) |
| Safe for text documents | Yes | No — destroys the text layer |

The GUI defaults to lossless and only enables DPI/quality controls when rasterize is selected.

---

## 6. Phase 3 — Office conversion

### 6.1 Core API — `core/office.py`

```python
OFFICE_SUFFIXES = frozenset({
    ".doc", ".docm", ".docx", ".dot", ".dotx", ".odt", ".ott",
    ".rtf", ".xls", ".xlsm", ".xlsx", ".ods", ".ots",
    ".ppt", ".pptm", ".pptx", ".odp", ".otp",
})

@dataclass(frozen=True)
class OfficeInfo:
    available: bool
    binary: Path | None
    source: str | None   # "explicit", "environment", "bundled", "system"
    version: str | None

def find_libreoffice(binary=None, bundle_dir=None) -> tuple[Path, str] | None
def office_available() -> bool
def office_info(binary=None, bundle_dir=None) -> OfficeInfo
def office_to_pdf(input_paths, output_dir, binary=None, bundle_dir=None,
                  timeout=120.0, progress=None, cancel=None) -> list[Path]
```

**Detection order (`find_libreoffice`):**
1. An explicit `binary=` argument.
2. The `PDFPAD_LIBREOFFICE` environment variable.
3. The bundled add-on directory: `office/` next to `core/` (or next to the frozen executable), looking for `program/soffice`, `program/soffice.bin`, or `soffice`.
4. A system `soffice` or `libreoffice` on `PATH`.

An explicitly requested binary or environment variable that points at a missing/non-executable file raises `OfficeUnavailableError`; `office_available()` returns `False` in that case.

**Conversion (`office_to_pdf`):**
- Validates every input exists and has an Office suffix; rejects empty lists and non-Office inputs.
- Requires a discovered backend; raises `OfficeUnavailableError` otherwise.
- Creates `output_dir` if missing.
- For each document, copies the input into a hidden temporary directory (`.pdfpad-office-*`) inside `output_dir`, runs LibreOffice headless with `--headless --norestore --nodefault --nolockcheck --nologo --invisible`, a private `-env:UserInstallation=<temp profile>`, `--convert-to pdf --outdir <work/out>`, then atomically moves the produced `<stem>.pdf` into `output_dir` with `os.replace`.
- If LibreOffice produces a differently-named single PDF, that file is adopted (resilient to version-dependent naming). If it produces zero or multiple PDFs, `PdfOperationError` is raised.
- Duplicate output stems are de-duplicated with `-2`, `-3`, … suffixes, preserving input order.
- Progress is reported once per document (`position / len(sources)`).
- Cancellation terminates the converter process group (SIGTERM, then SIGKILL after a grace period) and removes every file created by the cancelled run; unrelated pre-existing files in the output folder are left alone.
- A per-document `timeout` (default 120 s) raises `PdfOperationError` ("…timed out…") and terminates the converter.

**Capability reporting:**
- `office_info()` returns `OfficeInfo(available, binary, source, version)` by probing `--version`.
- `office_available()` returns a boolean without probing the version.

### 6.2 Runtime behaviour and safety

- The original input folder is never written to; staged copies live under the output folder.
- The private `UserInstallation` profile avoids polluting or locking a user's real LibreOffice profile.
- `os.replace` moves the produced PDF onto the final path atomically (same filesystem because the work dir is inside `output_dir`).
- On cancellation, only files created by that run are removed; an unrelated `keep.pdf` next to them survives.

---

## 7. Phase 3 — GUI integration

### 7.1 Operation metadata — `gui/operations.py`

Two new `OperationSpec` entries:

| Key | Label | Inputs | Output | Default suffix |
|---|---|---|---|---|
| `compress` | Compress PDF | `pdf` | file | `_compressed.pdf` |
| `office` | Office to PDF | `office` | dir | `_office` |

`SUPPORTED_SUFFIXES` now includes the Office extensions, so the file dialog and drag-and-drop accept Office documents. `is_office(path)` was added alongside `is_pdf` and `is_image`.

`OperationOptions` gained `compression_mode: str = "lossless"`. `default_output` returns `<stem>_compressed.pdf` for `compress` and `<stem>_office` for `office`.

### 7.2 Request building

`build_request("compress", …)`:
- Requires exactly one PDF.
- Rejects unknown compression modes, DPI ≤ 0, and quality outside 1–100 with `RequestError`.
- Forwards `mode`, `dpi`, `quality`, and `password` to `compress_pdf`.

`build_request("office", …)`:
- Calls `find_libreoffice()` and raises `RequestError("…add-on…")` when unavailable.
- Validates inputs are Office documents.
- Forwards `input_paths`, `output_dir`, and the discovered `binary` to `office_to_pdf`.

### 7.3 Option forms — `gui/options_panel.py`

**Compress form (`_form_compress`):**
- Mode combo: “Lossless (keep text and vectors)” / “Rasterize pages (loses text)”.
- Raster DPI spin box (36–600, default 150).
- JPEG quality spin box (1–100, default 75).
- DPI/quality are disabled in lossless mode; a hint explains the text-loss trade-off.

**Office form (`_form_office`):**
- A status label showing “available (source — path)” or “not installed”, refreshed when the operation is selected and on demand via a **Check add-on** button.
- The status uses `find_libreoffice()` directly, not version probing, so it stays fast and never blocks the UI.
- A hint lists the converted formats (DOC/DOCX, ODT, RTF, XLS/XLSX, ODS, PPT/PPTX, ODP).

`collect_options()` reads `compression_mode`, `compress_dpi`, and `compress_quality` for the compress operation.

### 7.4 Main window — `gui/main_window.py`

- The file filter now includes Office documents (`*.doc *.docx *.odt *.rtf *.xls *.xlsx *.ods *.ppt *.pptx *.odp`).
- `_run` records `last_input_size` (sum of input file sizes) when the operation is `compress`.
- `_on_finished` appends a size summary for compress results, e.g. `Size: 1.2 MB → 0.9 MB (25% smaller).`
- `_format_bytes(size)` helper formats byte counts as B/KB/MB/GB/TB.
- Default output names for compress (`*_compressed.pdf`) and office (`*_office`) are shown when switching operations.

---

## 8. Dependency inventory

Versions used for the Phase 3 test run (`requirements.txt`):

| Package | Version | Purpose |
|---|---|---|
| Python | 3.12.3 | Runtime used for development and tests |
| `pypdf` | 6.21.1 | Reading, writing, merging, rotating, encrypting/decrypting PDFs |
| `pypdfium2` | 5.15.0 | Rendering PDF pages and thumbnails; bundles PDFium |
| `Pillow` | 13.0.0 | Loading images, resizing, compositing, writing image-based PDFs |
| `pikepdf` | 9.11.0 | Lossless PDF compression; bundles QPDF 12.2.0 |
| `pdfminer.six` | 20260107 | Declared for planned Markdown extraction (Phase 4); not yet used |
| `PySide6-Essentials` | 6.12.0 | Qt 6 widgets, signals, threading, settings |
| `pytest` | 9.1.1 | Test runner (development only) |
| `pytest-qt` | 4.5.0 | Qt fixtures, `qtbot`, signal waiting (development only) |

`pikepdf==9.11.0` was added to `requirements.txt` and `pyproject.toml`. LibreOffice (detected at `/usr/bin/soffice`, version 24.2.7.2) is optional and is **not** a Python dependency; the `office/` add-on directory is documented in `office/README.md`.

---

## 9. Testing and quality assurance

### 9.1 Test totals

**314 tests pass** in the current tree. The suite takes roughly 6 seconds on the development machine and is stable across repeated runs.

New and extended test files:

| Test file | Focus |
|---|---|
| `tests/test_compress.py` (new) | Lossless and rasterize modes, progress, cancellation, validation, encryption, atomic output |
| `tests/test_office.py` (new) | LibreOffice detection (explicit/env/bundled/system), conversion, multiple/duplicate stems, timeout, cancellation cleanup, failures, args/profile, unsupported/missing inputs |
| `tests/fake_office.py` (new) | Deterministic fake `soffice` shim with selectable behaviours (success/fail/no-output/multi-output/wrong-name/sleep) and invocation logging |
| `tests/test_operations.py` (extended) | `is_office`, compress/office default outputs, compress/office request building, validation, unavailable backend |
| `tests/test_gui.py` (extended) | Compress/office default outputs and output labels, compress option collection, DPI/quality enable/disable, office unavailable status, compress end-to-end run with size summary |
| `tests/test_progress.py` (extended) | Compress progress sequences (lossless `1→100`/`100→100`, rasterize `1..6/6`), compress cancellation |

### 9.2 Fake LibreOffice helper

`tests/fake_office.py` provides `make_fake_office(directory, name="soffice")`, which writes an executable shell shim that runs the module with the current Python interpreter. Behaviour is controlled by environment variables so one helper covers every Office scenario without installing LibreOffice:

| `FAKE_OFFICE_BEHAVIOR` | Effect |
|---|---|
| `success` (default) | Copies `FAKE_OFFICE_TEMPLATE` to `<stem>.pdf` in `--outdir` |
| `fail` | Exits 1 with an error message |
| `no-output` | Exits 0 producing no PDF |
| `multi-output` | Produces `extra.pdf` and `extra2.pdf` (no stem PDF) |
| `wrong-name` | Produces `Converted.pdf` (resilient single-PDF adoption) |
| `sleep` | Sleeps `FAKE_OFFICE_SLEEP` seconds (used for timeout tests) |
| `ignore-sigterm` | Ignores SIGTERM then sleeps (used for termination escalation) |

Every invocation is appended as JSON to `FAKE_OFFICE_LOG`, and a `FAKE_OFFICE_SENTINEL` marker is touched after success, enabling deterministic cancellation tests.

The real LibreOffice is intentionally **not** required by the suite. Tests that need a backend set `PDFPAD_LIBREOFFICE` to the fake; tests that check unavailability point `PATH` at an empty directory.

### 9.3 What is verified

**Compression:**
- Lossless keeps page count and text layer; rasterize removes extracted text and preserves physical page dimensions.
- Lossless progress is bounded to 1–100 (`(1, 100)` … `(100, 100)`); rasterize progress spans `2N` units (render + assembly).
- Cancellation before writing leaves no output; cancellation during rasterize preserves a pre-existing output.
- Unknown mode, invalid DPI/quality, missing/corrupt input, and output-over-input are rejected.
- Encrypted PDFs require the correct password in both modes.

**Office conversion:**
- Detection honours explicit binary, `PDFPAD_LIBREOFFICE`, the bundled `office/` layout, and system `soffice`; an invalid explicit/env path raises `OfficeUnavailableError` and `office_available()` returns `False`.
- Conversion produces correctly-named PDFs in input order; duplicate stems get `-2`, `-3`, … suffixes.
- Progress fires once per document.
- Cancellation before the first document leaves no PDF output.
- Timeout, conversion failure, no output, and multiple outputs all raise `PdfOperationError`.
- Unsupported, missing, and zero inputs are rejected.
- Command arguments include `--headless`, `--convert-to pdf`, `--outdir`, and a private `-env:UserInstallation=…` profile.
- Original inputs are left unchanged and no temp files appear beside them.

**GUI:**
- Compress and office appear in the operation combo with correct default outputs and output labels.
- Compress DPI/quality controls follow the selected mode.
- Office status reports available/unavailable correctly.
- A compress run completes end to end and shows a size summary.

### 9.4 Headless GUI testing

As in Phases 1–2, `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen` and temporary `XDG_CONFIG_HOME`/`XDG_STATE_HOME` before any test imports PySide6, so tests never open windows or touch the real home directory.

---

## 10. Design decisions and rationale

### 10.1 pikepdf for lossless compression

`pikepdf` (which bundles QPDF) was chosen because it is a wheel with no system binary dependency, matching the project's self-containment requirement. Lossless mode uses object-stream generation and Flate recompression, which is safe for text documents and keeps the PDF searchable. Ghostscript was deliberately avoided to sidestep its AGPL licensing obligations.

### 10.2 Rasterize mode is explicitly lossy

Rasterize rebuilds every page as a JPEG, so the output is an image-only PDF. The GUI labels the mode “Rasterize pages (loses text)” and shows a hint explaining the trade-off. DPI and quality are only enabled in this mode. This keeps lossless the safe default.

### 10.3 Office detection order and optionality

The detection order (explicit → env var → bundled add-on → system) gives deployers full control: a bundled `office/` pack for air-gapped delivery, an env var for controlled environments, and automatic system fallback for development. `find_libreoffice` raises on an explicitly-broken path so misconfiguration is loud, while `office_available()` and `office_info()` degrade gracefully for UI status display.

### 10.4 Staging and atomic moves for Office

Office inputs are copied into `.pdfpad-office-*` temporary directories under the output folder before conversion. This keeps the user's input folder untouched (no LibreOffice lock files beside documents) and makes the final `os.replace` a same-filesystem atomic rename. The temporary work directory and the private `UserInstallation` profile are cleaned up by `tempfile.TemporaryDirectory` context managers.

### 10.5 Cancellation and cleanup

Both compression and Office conversion are cooperative. `office_to_pdf` polls `cancel()` while waiting for each converter process; on cancellation it terminates the process group (SIGTERM, escalating to SIGKILL) and removes only files created by that run. Compression discards its atomic temporary file if cancellation arrives during `pdf.save`. In all cases an already-existing output file is never damaged by a cancelled run.

---

## 11. Limitations and known issues

### 11.1 Feature limitations

- **Office → PDF is optional.** When no LibreOffice backend is discoverable, the operation is disabled in the GUI and `office_to_pdf` raises `OfficeUnavailableError`. The bundled `office/` pack must be assembled manually (see `office/README.md`).
- **Rasterize compression destroys the text layer.** Output is image-only and not searchable. This is intentional and labelled in the GUI; lossless is the default.
- **Office output naming follows LibreOffice.** A differently-named single PDF is adopted, but zero or multiple produced PDFs raise an error. Output names can vary between LibreOffice versions.
- **No Markdown export yet.** Plain text is available; layout-aware Markdown is planned for Phase 4 using `pdfminer.six`.
- **No OCR.** Scanned image-only PDFs produce empty text.
- **No packaging yet.** No AppImage, `.deb`, portable tarball, desktop entry, or icon installation. The app runs from a Python environment.
- **Linux only.** The code uses Linux path conventions and has not been tested on Windows or macOS.

### 11.2 Behavioural caveats

- Cancellation does not restore an already-overwritten file. Compression never replaces the destination until QPDF finishes, so a cancelled lossless run preserves the previous output. Office conversion stages into a temp dir and only moves on success, so a cancelled run leaves no partial PDF.
- `split_pdf` and `render_pages` overwrite same-named files in the output folder atomically; files newly created by a cancelled run are removed, unrelated files survive.
- Password attempts are limited to three per file; there is no saved-password feature.
- Rotation in the GUI is limited to 90°, 180°, and 270° clockwise.

### 11.3 Platform caveats

- The glibc ≥ 2.34 floor excludes older distributions.
- Qt's `xcb` platform plugin may require OS libraries on minimal installations; this is the most likely clean-machine startup issue.
- The project has not yet been validated in an air-gapped VM or with `unshare -n`; that is Phase 6 work.

### 11.4 Unused dependency

`pdfminer.six` is declared but not imported; it is reserved for Phase 4 Markdown extraction.

---

## 12. Roadmap: Phase 4 and beyond

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

## 13. Project file map

```
pdfpad/
├── core/
│   ├── __init__.py          # Public error exports and parse_ranges
│   ├── compress.py          # Phase 3: lossless / rasterize compression
│   ├── errors.py            # PdfPadError hierarchy (incl. OfficeUnavailableError)
│   ├── io.py                # require_file, atomic_output, write_text
│   ├── office.py            # Phase 3: LibreOffice detection + conversion
│   ├── pages.py             # open_pdf, page_count, extract, split, merge, rotate
│   ├── progress.py          # progress/cancel helpers
│   ├── render.py            # PDFium rendering, thumbnails
│   ├── images.py            # images → PDF
│   ├── ranges.py            # parse_ranges, validate_indices
│   └── text.py              # text extraction
├── gui/
│   ├── __init__.py
│   ├── __main__.py          # python -m gui
│   ├── app.py               # logging, QApplication, main() (version 0.3.0)
│   ├── main_window.py       # window, password prompts, worker orchestration,
│   │                        # compress size summary, Office file filter
│   ├── operations.py        # Qt-free operation metadata and request builder
│   │                        # (compress + office specs, is_office)
│   ├── options_panel.py     # operation forms incl. compress/office,
│   │                        # Office availability status
│   ├── workers.py           # OperationWorker and WorkerSignals
│   └── widgets/
│       ├── __init__.py
│       ├── drop_list.py     # FileDropList
│       └── preview.py       # PreviewStrip, PreviewWorker, pil_to_pixmap
├── office/
│   └── README.md            # Optional LibreOffice add-on layout, detection,
│                            # runtime behaviour, licensing
├── tests/
│   ├── conftest.py          # offscreen Qt, temp XDG dirs, fixtures
│   ├── fake_office.py       # Phase 3: deterministic fake soffice shim
│   ├── pdf_fixtures.py      # generated PDF/image helpers
│   ├── test_compress.py     # Phase 3: compression tests
│   ├── test_office.py       # Phase 3: Office conversion tests
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
│   ├── PDFPad-Phase1-2-Report.md
│   └── PDFPad-Phase3-Report.md   # this document
├── README.md
├── pyproject.toml           # version 0.3.0, pikepdf dependency
├── requirements.txt         # includes pikepdf==9.11.0
└── requirements-dev.txt
```

---

## Appendix A — Core API quick reference

### Compression

| Function | Signature |
|---|---|
| `compress_pdf` | `(input_path, output_path, mode="lossless", dpi=150, quality=75, password=None, progress=None, cancel=None) -> Path` |

### Office conversion

| Function | Signature |
|---|---|
| `find_libreoffice` | `(binary=None, bundle_dir=None) -> tuple[Path, str] \| None` |
| `office_available` | `() -> bool` |
| `office_info` | `(binary=None, bundle_dir=None) -> OfficeInfo` |
| `office_to_pdf` | `(input_paths, output_dir, binary=None, bundle_dir=None, timeout=120.0, progress=None, cancel=None) -> list[Path]` |

`OfficeInfo` fields: `available`, `binary`, `source` (`"explicit"`/`"environment"`/`"bundled"`/`"system"`), `version`.

### Pages, rendering, images, text

(unchanged from Phases 1–2; see the Phase 1–2 report Appendix A)

### GUI request builder

| Name | Purpose |
|---|---|
| `OPERATIONS` | Tuple of `OperationSpec` entries (now 9 operations) |
| `OPERATIONS_BY_KEY` | Lookup by operation key |
| `OperationOptions` | Dataclass of collected UI values (incl. `compression_mode`) |
| `OperationRequest` | Core function + kwargs + output path |
| `default_output(key, files)` | Default output path (incl. `*_compressed.pdf`, `*_office`) |
| `build_request(key, files, options, passwords=None)` | Validate and build a core call |
| `is_office(path)` | True for Office document extensions |
| `RequestError` | Pre-flight validation failure |

---

## Appendix B — Naming and format conventions

### Accepted input extensions

| Kind | Extensions |
|---|---|
| PDF | `.pdf` |
| Images | `.bmp`, `.gif`, `.jpeg`, `.jpg`, `.png`, `.tif`, `.tiff`, `.webp` |
| Office documents | `.doc`, `.docm`, `.docx`, `.dot`, `.dotx`, `.odt`, `.ott`, `.rtf`, `.xls`, `.xlsm`, `.xlsx`, `.ods`, `.ots`, `.ppt`, `.pptm`, `.pptx`, `.odp`, `.otp` |

### Output naming

| Operation | Pattern | Example |
|---|---|---|
| Compress | `<stem>_compressed.pdf` | `report_compressed.pdf` |
| Office | `<stem>_office/` → `<stem>.pdf` (de-duped with `-2`, `-3`) | `report_office/report.pdf` |

(All other naming unchanged from the Phase 1–2 report Appendix B.)

---

## Appendix C — Test inventory

New Phase 3 test files:

### `tests/fake_office.py` (helper, not a test module)

Executable fake `soffice` shim. Behaviours: `success`, `fail`, `no-output`, `multi-output`, `wrong-name`, `sleep`, `ignore-sigterm`. Logs invocations as JSON-lines; touches `FAKE_OFFICE_SENTINEL` on success.

### `tests/test_compress.py` (~30 tests)

- Compression modes documented; lossless is the default.
- Lossless keeps pages and text; rasterize removes the text layer and preserves page dimensions.
- Lossless progress `(1, 100)` … `(100, 100)`; rasterize progress `1..6 / 6` for a 3-page PDF.
- Cancellation leaves no output and preserves pre-existing output.
- Unknown mode, invalid DPI/quality, missing/corrupt input, output-over-input rejected.
- Encrypted PDFs: password required, wrong password rejected, correct password accepted in both modes.

### `tests/test_office.py` (~22 tests)

- Detection: system binary, env var, explicit path, bundled `program/soffice`, invalid env var raises, `office_available()` False when nothing installed.
- `office_info()` returns `OfficeInfo` with `available`, `binary`, `source`, `version`.
- Conversion: single document, multiple documents in order, duplicate stems de-duplicated, `binary=` overrides env.
- Progress: `(1, N)` … `(N, N)`.
- Cancellation before the first document leaves no PDF output.
- Timeout, conversion failure, no output, multiple outputs → `PdfOperationError`.
- Unsupported/missing/zero inputs rejected; `OfficeUnavailableError` when no backend.
- Invocation arguments include `--headless`, `--convert-to pdf`, `--outdir`, private `UserInstallation` profile.
- Original inputs unchanged; no temp files beside originals.

Extended existing files:

- `tests/test_operations.py`: `is_office`, compress/office default outputs, compress/office request building and validation, unavailable-backend `RequestError`.
- `tests/test_gui.py`: compress/office default outputs and labels, compress option collection, DPI/quality enable/disable, office unavailable status, compress end-to-end run with size summary.
- `tests/test_progress.py`: compress lossless and rasterize progress sequences; compress cancellation.

---

## Closing note

Phase 3 completes the compression and Office → PDF feature areas. Compression offers a safe lossless default plus an explicitly-labelled rasterize mode, both with progress, cancellation, encryption support, and atomic output. Office conversion is fully optional, decoupled from the core, and protected by timeouts, cancellation cleanup, isolated profiles, and atomic staging. The GUI exposes operation metadata, option forms, Office availability status, and a compression size summary.

The full suite of **314 tests** passes stably across repeated runs, covering correctness, atomicity, encryption, progress, cancellation, Office detection, conversion failure modes, and GUI integration. The architecture from Phases 1–2 — GUI-independent core, Qt-free request building, background workers, progress/cancel — scales cleanly to the new operations and remains the foundation for Phase 4 (Markdown export), Phase 5 (packaging), and Phase 6 (air-gap validation).
