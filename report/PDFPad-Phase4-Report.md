# PDFPad — Phase 4 Implementation Report

**Project:** PDFPad — an offline PDF conversion desktop application for Linux  
**Version:** 0.4.0  
**Report date:** 2026-11-08  
**Target platform:** Linux x86_64, glibc ≥ 2.34 (Ubuntu 22.04 / Linux Mint 21 or newer)  
**Runtime model:** fully offline, no network calls, no system binaries required for core conversion  
**Current status:** Phase 1 (core library) complete · Phase 2 (PySide6 GUI) complete · Phase 3 (compression + Office → PDF) complete · Phase 4 (Markdown export) complete · **345 automated tests passing**

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [Product overview](#2-product-overview)
3. [Feature status matrix](#3-feature-status-matrix)
4. [Architecture](#4-architecture)
5. [Phase 4 — Markdown conversion](#5-phase-4--markdown-conversion)
6. [Phase 4 — GUI integration](#6-phase-4--gui-integration)
7. [Dependency inventory](#7-dependency-inventory)
8. [Testing and quality assurance](#8-testing-and-quality-assurance)
9. [Design decisions and rationale](#9-design-decisions-and-rationale)
10. [Limitations and known issues](#10-limitations-and-known-issues)
11. [Roadmap: Phase 5 and beyond](#11-roadmap-phase-5-and-beyond)
12. [Project file map](#12-project-file-map)
13. [Appendix A — Core API quick reference](#appendix-a--core-api-quick-reference)
14. [Appendix B — Markdown conventions](#appendix-b--markdown-conventions)
15. [Appendix C — Test inventory](#appendix-c--test-inventory)

---

## 1. Executive summary

PDFPad is a Linux desktop application for common PDF conversion and page-manipulation tasks. It is designed for environments where files must not leave the machine: the application makes no network requests and performs every conversion with bundled Python wheels rather than external programs such as Ghostscript, Poppler, or LibreOffice.

Phase 4 completes the sixth and final feature area from the product plan:

- **PDF → Markdown** — `core/markdown.py`. A best-effort converter built on `pdfminer.six` that recognises headings, paragraphs, bullet and numbered lists, and simple tables. It is intentionally heuristic: the goal is a readable Markdown starting point, not a pixel-perfect reproduction of the source layout.
- **GUI integration** — a new **Extract Markdown** operation with a page-range field, a `.md` output default, a dedicated file filter, and an explanatory hint about the heuristic nature of the conversion.
- **Atomic output** — Markdown is written through the same `write_text` / `atomic_output` helper used by text export, so a cancelled or failed run never damages an existing file.

The Markdown feature reuses the established architecture: GUI-independent core functions, Qt-free request building in `gui/operations.py`, cooperative progress/cancellation, and background execution through `OperationWorker`.

The full test suite now contains **345 passing tests** (up from 314 after Phase 3) and runs headlessly through the Qt `offscreen` platform. The suite is stable across repeated runs.

---

## 2. Product overview

### 2.1 New capability in Phase 4

| Capability | Core API | GUI exposure | Notes |
|---|---|---|---|
| PDF → Markdown | `core.markdown.extract_markdown()` | “Extract Markdown” | Returns best-effort Markdown as a string |
| Markdown to file | `core.markdown.extract_markdown_to_file()` | “Extract Markdown” | Writes UTF-8 atomically |
| Page selection | `indices=` parameter | Pages field | Same 1-based grammar as every other operation |
| Progress | `progress=` callback | Progress bar | One unit per selected page |
| Cancellation | `cancel=` predicate | Cancel button | Stops before writing; existing output is preserved |
| Password support | `password=` parameter | Password prompt | Encrypted PDFs use the shared prompt flow |

### 2.2 What “best-effort Markdown” means

The converter uses font size, text position, and line geometry to infer document structure. It recognises:

- **Headings** — lines significantly larger than the document's dominant body size become `#`, `##`, or `###`.
- **Paragraphs** — consecutive lines with a small vertical gap are joined into one paragraph; larger gaps start a new paragraph.
- **Lists** — lines starting with a bullet character or a number become Markdown list items.
- **Tables** — consecutive rows with the same number of horizontally aligned cells become a pipe table.

Anything that does not fit these patterns is emitted as plain paragraph text. The output is valid Markdown but may not preserve multi-column layouts, merged table cells, exact spacing, or inline styling (bold/italic runs inside a paragraph).

### 2.3 Offline and self-contained guarantees (unchanged)

- **No network access in application code.** Core and GUI modules make no HTTP, socket, or download calls.
- **No external conversion binaries for core features.** PDF parsing for Markdown uses `pdfminer.six`, a pure-Python wheel. Rendering still uses `pypdfium2` (bundled PDFium), PDF writing uses `pypdf`, images use `Pillow`, and compression uses `pikepdf` (bundled QPDF).
- **All dependencies are Python wheels.** There is no runtime dependency on `poppler-utils`, `qpdf`, Ghostscript, or LibreOffice for Markdown conversion.
- **Office conversion remains optional.** Markdown conversion does not require LibreOffice.
- **Local filesystem only.** Outputs are written next to the inputs or to a user-selected folder.

---

## 3. Feature status matrix

### 3.1 Implemented (Phases 1–4)

| # | Feature area | Status |
|---|---|---|
| 1 | Page operations (extract, split, merge, rotate) | ✅ Phase 1 core + Phase 2 GUI |
| 2 | PDF → images (PNG/JPEG, DPI, page range) | ✅ Phase 1 core + Phase 2 GUI |
| 3 | Images → PDF (order, page size, fit) | ✅ Phase 1 core + Phase 2 GUI |
| 4 | Office → PDF (optional LibreOffice add-on) | ✅ Phase 3 core + GUI |
| 5 | Compress (lossless + optional rasterize) | ✅ Phase 3 core + GUI |
| 6 | PDF → text / Markdown | ✅ text in Phases 1–2 · ✅ Markdown in Phase 4 |

### 3.2 Planned but not yet implemented

| Capability | Planned phase | Current state |
|---|---|---|
| OCR for scanned PDFs | Not in current scope | Text extraction is text-layer only |
| Packaging (`PyInstaller`, `.desktop`, installer) | Phase 5 | Not started |
| Air-gap validation (`unshare -n`, clean VM) | Phase 6 | Not yet performed |

---

## 4. Architecture

Phase 4 adds one module to `core/` and wires it into `gui/operations.py`, `gui/options_panel.py`, and the existing worker flow. The layered design is unchanged.

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
│  markdown.py   PDF → best-effort Markdown (pdfminer.six)             │
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

The end-to-end flow for Markdown:

1. The user selects one or more PDFs and chooses **Extract Markdown**.
2. The GUI collects the page range and output path, then calls `build_request("markdown", …)`.
3. `build_request` validates the input, resolves the page indices, and returns an `OperationRequest` bound to `extract_markdown_to_file`.
4. `OperationWorker` runs the core function on the thread pool, forwarding progress and cancellation.
5. The core function validates the PDF and password with `open_pdf`, parses the selected pages with `pdfminer.six`, converts each page to Markdown, and writes the result atomically.
6. The GUI reports completion and reveals the **Open output folder** button.

---

## 5. Phase 4 — Markdown conversion

### 5.1 Core API — `core/markdown.py`

```python
def extract_markdown(
    input_path,
    indices=None,
    password=None,
    progress=None,
    cancel=None,
) -> str

def extract_markdown_to_file(
    input_path,
    output_path,
    indices=None,
    password=None,
    progress=None,
    cancel=None,
) -> Path
```

**Semantics:**

- `indices=None` converts every page. Otherwise `indices` is a sequence of 0-based page indices validated by `core.ranges.validate_indices`.
- Selection order is preserved, and duplicate indices are repeated in the output. Each unique page is parsed only once.
- Blank pages contribute nothing; pages are separated by a blank line in the final document.
- `password` is used for encrypted PDFs. The password is validated first by `open_pdf` (pypdf) and then passed to `pdfminer`.
- `progress(current, total)` is called once per unique selected page after it has been parsed.
- `cancel()` is checked before each page is processed and again before each page is formatted. Cancellation raises `OperationCancelled` before the output is written.

**Errors:**

| Situation | Exception |
|---|---|
| Missing or non-file input | `UnsupportedFileError` |
| Corrupt / unreadable PDF | `PdfOperationError` |
| Encrypted PDF without a password | `EncryptedPdfError` |
| Incorrect password | `EncryptedPdfError` |
| Empty or out-of-range page selection | `RangeSpecError` |
| Cancellation | `OperationCancelled` |

### 5.2 Conversion pipeline

```
PDF file
   │
   ├─ open_pdf(path, password)             # pypdf: validate file, password, page count
   │
   ├─ validate_indices(indices, total)     # shared page-selection validation
   │
   ├─ pdfminer.extract_pages(...,          # parse only the selected pages
   │       page_numbers=set(ordered),
   │       password=...)
   │
   ├─ _extract_lines(layout)               # flatten to _Line(text, x0, x1, y0, y1, size, bold)
   │
   ├─ _body_size(all_lines)                # weighted median font size
   │
   ├─ for each selected page:
   │     _group_rows(lines)                # visual rows by baseline
   │     _find_tables(rows, page_width)    # detect aligned multi-cell blocks
   │     _format_flow(non_table_lines)     # headings, lists, paragraphs
   │
   └─ write_text(output, markdown)         # atomic UTF-8 write
```

### 5.3 Line extraction

`_extract_lines` recursively walks the `pdfminer` layout tree and collects every `LTTextLine`. For each line it records:

- **Text** — whitespace-normalised (`" ".join(text.split())`).
- **Geometry** — `x0`, `x1`, `y0`, `y1` from the line's bounding box.
- **Font size** — the median size of the line's `LTChar` children.
- **Bold flag** — true when more than half of the characters use a font whose name contains `bold`, `black`, `heavy`, `semibold`, or `demi`.

Empty lines are discarded.

### 5.4 Body size and heading detection

The document's **body size** is the weighted median of all line sizes, where each line's weight is its text length (capped at 200 characters). Weighting by text length prevents a document with many headings from mistaking headings for body text.

Heading levels are assigned by comparing a line's size with the body size:

| Size ratio | Heading level | Markdown |
|---|---|---|
| ≥ 1.70 | 1 | `#` |
| ≥ 1.32 | 2 | `##` |
| ≥ 1.12 and bold | 3 | `###` |
| otherwise | body | paragraph / list |

Lines longer than 120 characters are never treated as headings.

### 5.5 Paragraph grouping

Lines are grouped into visual rows by baseline, then flattened in reading order. Within a run of non-table lines:

- A new paragraph starts when the vertical gap between the previous line and the next line exceeds `0.6 × max(line heights)`.
- A new paragraph also starts when the font size changes by more than 0.5 pt.
- Lines in the same paragraph are joined with a space.
- A trailing hyphen is removed when the next line starts with a lowercase letter (simple de-hyphenation).

### 5.6 Lists

The converter recognises two list kinds:

| Input pattern | Output |
|---|---|
| `• item`, `· item`, `- item`, `* item`, `+ item`, `– item`, `— item` | `- item` |
| `1. item`, `1) item` | `1. item` |

Consecutive items of the same kind are emitted as one Markdown list. A change from bullets to numbers (or vice versa) starts a new list block. An indented continuation line that follows a list item with a small vertical gap is appended to that item.

### 5.7 Simple tables

A table is detected when:

1. At least two consecutive visual rows have the **same number of cells** (≥ 2).
2. The cells in each column start at approximately the same x-coordinate (`max(x0) − min(x0) ≤ max(20 pt, 5% of page width)`).
3. No cell contains more than 100 characters.

The first row becomes the Markdown header, the second line becomes the `| --- |` separator, and the remaining rows become the table body. Pipe characters inside cells are escaped as `\|`.

If a row with a different cell count appears, it starts a new candidate block rather than invalidating the table that came before it. This keeps a table from being lost when it is followed by a differently shaped line.

### 5.8 Page order, duplicates, and progress

`validate_indices` preserves the caller's order and duplicates. The converter:

1. Deduplicates the selection while preserving first-occurrence order.
2. Parses the unique pages in ascending document order (pdfminer yields pages in document order).
3. Emits pages in the originally requested order, repeating duplicates.

Progress counts unique pages. For example, selecting pages `[0, 0, 1]` reports `(1, 2)` and `(2, 2)`, and the output contains page 0 twice and page 1 once.

### 5.9 Atomic output and cancellation

`extract_markdown_to_file` builds the complete Markdown string in memory and then calls `core.io.write_text`, which uses `atomic_output`:

- A temporary file is created in the destination directory.
- The Markdown is written as UTF-8.
- `os.replace` moves it onto the final path only on success.
- On cancellation or any exception, the temporary file is removed and the destination is left untouched.

This means a cancelled run never damages a pre-existing `.md` file.

---

## 6. Phase 4 — GUI integration

### 6.1 Operation metadata — `gui/operations.py`

A new `OperationSpec` was added after **Extract text**:

| Key | Label | Inputs | Output | Default suffix |
|---|---|---|---|---|
| `markdown` | Extract Markdown | `pdf` | file | `.md` |

- `_FUNCTIONS["markdown"]` maps to `extract_markdown_to_file`.
- `default_output("markdown", files)` returns `<stem>.md`.
- `build_request("markdown", …)` validates exactly one PDF, resolves the page range, and forwards `input_path`, `output_path`, `indices`, and `password`.
- Output paths without a suffix receive `.md` via the existing `_normalise_output` logic.

### 6.2 Options panel — `gui/options_panel.py`

The new **Extract Markdown** form (`_form_markdown`) contains:

- A **Pages** field using the shared 1-based page-range grammar, with the placeholder `e.g. 1-3,5 — leave empty to convert all pages`.
- A hint: *“Best-effort Markdown: headings, paragraphs, lists and simple tables. Complex layouts are flattened, not reproduced exactly.”*

The output picker recognises `.md` and opens a **Markdown files (*.md)** save dialog. `collect_options()` reads the page range through the existing `_page_range_edits` mechanism; no new `OperationOptions` fields were needed.

### 6.3 Main window — `gui/main_window.py`

No special-case logic was required. The existing pipeline handles the new operation:

- Password prompts work because Markdown input is a PDF.
- The worker runs `extract_markdown_to_file` in the background.
- On success, the result is a `Path`; the window shows `Done — saved <path>` and reveals **Open output folder**.
- Progress and cancellation use the same signals as every other operation.

### 6.4 Version

`gui/app.py` and `pyproject.toml` were bumped from `0.3.0` to `0.4.0`.

---

## 7. Dependency inventory

Versions used for the Phase 4 test run (`requirements.txt`):

| Package | Version | Purpose |
|---|---|---|
| Python | 3.12.3 | Runtime used for development and tests |
| `pypdf` | 6.21.1 | Reading, writing, merging, rotating, encrypting/decrypting PDFs |
| `pypdfium2` | 5.15.0 | Rendering PDF pages and thumbnails; bundles PDFium |
| `Pillow` | 13.0.0 | Loading images, resizing, compositing, writing image-based PDFs |
| `pikepdf` | 9.11.0 | Lossless PDF compression; bundles QPDF 12.2.0 |
| `pdfminer.six` | 20260107 | **Now used:** layout analysis and text-line extraction for Markdown |
| `PySide6-Essentials` | 6.12.0 | Qt 6 widgets, signals, threading, settings |
| `pytest` | 9.1.1 | Test runner (development only) |
| `pytest-qt` | 4.5.0 | Qt fixtures, `qtbot`, signal waiting (development only) |

`pdfminer.six` was declared in earlier phases but unused; Phase 4 makes it an active runtime dependency. No new packages were added.

---

## 8. Testing and quality assurance

### 8.1 Test totals

**345 tests pass** in the current tree. The suite takes roughly 6–7 seconds on the development machine and is stable across repeated runs.

| Test file | Tests | Focus |
|---|---:|---|
| `tests/test_markdown.py` (new) | 19 | Headings, paragraphs, lists, tables, page order, duplicates, errors, output, progress, cancellation |
| `tests/test_operations.py` (extended) | 89 | Markdown default output, request building, suffix handling, end-to-end execution |
| `tests/test_gui.py` (extended) | 41 | Markdown default output/label, option collection, end-to-end GUI run |
| `tests/test_progress.py` (extended) | 22 | Markdown progress and cancellation |
| Other existing files | 174 | Ranges, pages, render, images, text, io, workers, compress, office |

### 8.2 New fixture: positioned, styled PDFs

`tests/pdf_fixtures.py` gained `make_rich_pdf(path, pages, page_size)`:

```python
make_rich_pdf(
    path,
    [
        [
            ("Document Title", 72, 720, 24, True),
            ("Introduction", 72, 680, 16, True),
            ("First paragraph line one", 72, 650, 11, False),
            ...
        ],
        ...
    ],
)
```

Each tuple is `(text, x, y, size, bold)`. The helper builds a PDF with Helvetica and Helvetica-Bold resources and one content stream per page. This makes heading, list, and table tests deterministic without depending on an external document.

The `rich_pdf` fixture in `tests/conftest.py` combines a title, a section heading, two paragraphs, a bullet list, a numbered list, a 3×3 table, and a second page.

### 8.3 What is verified

**Markdown structure:**

- Headings become `#`, `##`; paragraphs are joined and separated correctly.
- Bullet and numbered lists are emitted as separate list blocks.
- Simple tables produce a header row, a separator row, and body rows.
- Pages are separated by a blank line; selection order is preserved.
- Duplicate indices repeat the selected page without re-parsing it.
- Plain text PDFs become simple paragraphs; blank pages produce no output.
- Single-page selections omit the other pages.

**Markdown errors and output:**

- Out-of-range indices raise `RangeSpecError`.
- Missing files raise `UnsupportedFileError`.
- Encrypted PDFs require the correct password; wrong/missing passwords raise `EncryptedPdfError`.
- `extract_markdown_to_file` writes UTF-8 and replaces an existing output atomically.

**Progress and cancellation:**

- Progress reports one event per unique selected page.
- Cancellation before the first page leaves no output.
- Cancellation preserves a pre-existing output file.
- A cancel predicate that never trips still produces the full document.

**GUI:**

- The operation combo includes **Extract Markdown** with a `.md` default output and an “Output file” label.
- `collect_options()` reads the Markdown page range.
- A Markdown run completes end to end, writes the expected file, updates the status label, and reveals the output button.

### 8.4 Headless GUI testing

As in earlier phases, `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen` and temporary `XDG_CONFIG_HOME`/`XDG_STATE_HOME` before any test imports PySide6, so tests never open windows or touch the real home directory.

---

## 9. Design decisions and rationale

### 9.1 pdfminer.six instead of regexing pypdf text

`pypdf` can extract plain text but discards the geometry and font information needed to infer headings, lists, and tables. `pdfminer.six` provides a layout tree with bounding boxes and character-level font data, which makes the heuristics possible. It is a pure-Python wheel, preserving the offline/self-contained guarantee.

### 9.2 Best-effort, clearly labelled

PDF layout is not a structured document format. Any converter that promises perfect Markdown is either using a large ML model or making assumptions that fail on real files. PDFPad deliberately labels the feature “best-effort” in the GUI hint and in this report. The output is valid Markdown and useful for search, note-taking, and re-authoring, but it is not a lossless conversion.

### 9.3 Two-pass page processing

The converter parses all selected pages first, computes a document-wide body size, and only then formats each page. This keeps heading thresholds consistent across the document. A per-page body size would misclassify a title-only page or a page with many headings. Memory use is modest because only extracted line records are retained, not the full pdfminer layout.

### 9.4 Deduplicate parsing, preserve output order

`validate_indices` preserves duplicates and order to match the rest of the core API. Parsing each duplicate again would waste time, so the converter parses unique pages once and repeats them when emitting output. Progress counts unique pages, which matches the amount of work actually performed.

### 9.5 Reuse atomic writes and cancellation

Markdown export uses the same `write_text` helper and `progress`/`cancel` conventions as text export. This keeps behaviour consistent: cancellation never damages an existing output, and the GUI needs no special-case code.

### 9.6 Table detection is conservative

The table heuristic requires uniform cell counts, aligned columns, and reasonably short cells. It will miss merged cells and complex tables, but it avoids turning ordinary paragraphs into spurious tables in most cases. Multi-column page layouts can still be mistaken for tables; this is documented as a limitation.

---

## 10. Limitations and known issues

### 10.1 Markdown fidelity

- **Heuristic, not lossless.** Headings, lists, and tables are inferred from geometry; unusual fonts or layouts may be misclassified.
- **Inline styling is lost.** Bold/italic runs inside a paragraph are not represented; only line-level heading detection uses boldness.
- **Multi-column layouts are flattened.** Reading order is top-to-bottom, left-to-right by line position, which interleaves columns.
- **Merged table cells are not supported.** Rows must have the same number of cells to be recognised as a table.
- **Tables without consistent column alignment are missed.** They fall back to paragraph text.
- **Images, charts, and figures are ignored.** Only text is converted.
- **No OCR.** Scanned image-only PDFs produce no Markdown.

### 10.2 Behavioural caveats

- A page with only a title and no body text may not have its title recognised as a heading, because the document-wide body size is derived from the same text.
- Hyphenated line breaks are de-hyphenated only when the next line starts with a lowercase letter; compound words broken at an existing hyphen may lose the hyphen.
- Numbered list markers are preserved as written; Markdown renderers may renumber them.
- Markdown pages are separated by a blank line, not by an explicit page marker.

### 10.3 Platform caveats

- The glibc ≥ 2.34 floor excludes older distributions.
- Qt's `xcb` platform plugin may require OS libraries on minimal installations; this is the most likely clean-machine startup issue.
- The project has not yet been validated in an air-gapped VM or with `unshare -n`; that is Phase 6 work.

---

## 11. Roadmap: Phase 5 and beyond

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

### Possible future improvements (not scheduled)

- Optional OCR integration for scanned PDFs.
- Richer Markdown (inline emphasis, code blocks, nested lists).
- Multi-column reading-order detection.
- Batch Markdown export with a manifest.

---

## 12. Project file map

```
pdfpad/
├── core/
│   ├── __init__.py          # Public error exports and parse_ranges
│   ├── compress.py          # Phase 3: lossless / rasterize compression
│   ├── errors.py            # PdfPadError hierarchy (incl. OfficeUnavailableError)
│   ├── io.py                # require_file, atomic_output, write_text
│   ├── markdown.py          # Phase 4: best-effort PDF → Markdown
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
│   ├── app.py               # logging, QApplication, main() (version 0.4.0)
│   ├── main_window.py       # window, password prompts, worker orchestration
│   ├── operations.py        # Qt-free operation metadata and request builder
│   ├── options_panel.py     # operation forms incl. Markdown
│   ├── workers.py           # OperationWorker and WorkerSignals
│   └── widgets/
│       ├── __init__.py
│       ├── drop_list.py     # FileDropList
│       └── preview.py       # PreviewStrip, PreviewWorker, pil_to_pixmap
├── office/
│   └── README.md            # Optional LibreOffice add-on layout and behaviour
├── tests/
│   ├── conftest.py          # offscreen Qt, temp XDG dirs, fixtures
│   ├── fake_office.py       # deterministic fake soffice shim
│   ├── pdf_fixtures.py      # generated PDF/image helpers (incl. make_rich_pdf)
│   ├── test_compress.py
│   ├── test_gui.py
│   ├── test_images.py
│   ├── test_io.py
│   ├── test_markdown.py     # Phase 4
│   ├── test_office.py
│   ├── test_operations.py
│   ├── test_pages.py
│   ├── test_progress.py
│   ├── test_ranges.py
│   ├── test_render.py
│   ├── test_text.py
│   └── test_workers.py
├── report/
│   ├── PDFPad-Phase1-2-Report.md
│   ├── PDFPad-Phase3-Report.md
│   └── PDFPad-Phase4-Report.md   # this document
├── README.md
├── pyproject.toml           # version 0.4.0
├── requirements.txt         # includes pdfminer.six==20260107
└── requirements-dev.txt
```

---

## Appendix A — Core API quick reference

### Markdown

| Function | Signature |
|---|---|
| `extract_markdown` | `(input_path, indices=None, password=None, progress=None, cancel=None) -> str` |
| `extract_markdown_to_file` | `(input_path, output_path, indices=None, password=None, progress=None, cancel=None) -> Path` |

### Other core APIs

(unchanged from the Phase 3 report; see `report/PDFPad-Phase3-Report.md` Appendix A)

### GUI request builder

| Name | Purpose |
|---|---|
| `OPERATIONS` | Tuple of `OperationSpec` entries (now 10 operations) |
| `OPERATIONS_BY_KEY` | Lookup by operation key |
| `OperationOptions` | Dataclass of collected UI values |
| `OperationRequest` | Core function + kwargs + output path |
| `default_output(key, files)` | Default output path (incl. `<stem>.md`) |
| `build_request(key, files, options, passwords=None)` | Validate and build a core call |
| `RequestError` | Pre-flight validation failure |

---

## Appendix B — Markdown conventions

### Output naming

| Operation | Pattern | Example |
|---|---|---|
| Extract text | `<stem>.txt` | `report.txt` |
| Extract Markdown | `<stem>.md` | `report.md` |

### Structural mapping

| Detected structure | Markdown |
|---|---|
| Large title line | `# Title` |
| Section heading | `## Section` |
| Sub-section heading | `### Sub-section` |
| Paragraph | Blank-line separated text |
| Bullet list | `- item` lines |
| Numbered list | `1. item` lines |
| Simple table | Pipe table with a `---` separator row |
| Page boundary | Blank line between page blocks |

### Escaping

- Pipes inside table cells are escaped as `\|`.
- Other Markdown-sensitive characters are left as-is; the converter does not attempt to escape every possible construct.

---

## Appendix C — Test inventory

### `tests/test_markdown.py` (19 tests)

- Headings and paragraphs.
- Bullet and numbered lists, including separation of list kinds.
- Simple table output.
- Blank line between pages.
- Selection order and duplicate indices.
- Plain text PDFs and blank pages.
- Single-page selection.
- Out-of-range indices, missing files, encrypted PDFs.
- UTF-8 output and replacement of an existing file.
- Progress events, cancellation before output, cancellation preserving an existing file, and a non-tripping cancel predicate.

### Extended existing files

- `tests/test_operations.py`: Markdown default output, request building (with and without a page range), suffix handling, and end-to-end execution.
- `tests/test_gui.py`: Markdown default output/label, option collection, and a full GUI run.
- `tests/test_progress.py`: Markdown progress reporting and cancellation.

### Test totals

| Area | Tests |
|---|---:|
| Markdown-specific | 19 |
| Operations (all) | 89 |
| GUI (all) | 41 |
| Progress (all) | 22 |
| Other core areas | 174 |
| **Total** | **345** |

---

## Closing note

Phase 4 completes the feature set defined at the start of the project: page operations, PDF → images, images → PDF, Office → PDF, compression, and PDF → text/Markdown. The Markdown converter is deliberately modest in scope — it infers structure from layout and documents its limits — but it fits the project's core principles: offline operation, bundled wheels, GUI-independent core functions, atomic writes, and cooperative progress/cancellation.

The full suite of **345 tests** passes stably across repeated runs. The remaining work is packaging (Phase 5) and air-gap/robustness validation (Phase 6), after which PDFPad will be ready for distribution as a self-contained Linux desktop application.
