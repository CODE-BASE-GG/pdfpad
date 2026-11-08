# PDFPad — Phase 6 Implementation Report

**Project:** PDFPad — an offline PDF conversion desktop application for Linux  
**Version:** 0.5.0  
**Report date:** 2026-11-08  
**Target platform:** Linux x86_64, glibc ≥ 2.34 (Ubuntu 22.04 / Linux Mint 21 or newer)  
**Runtime model:** fully offline, no network calls, no system binaries required for core conversion  
**Current status:** Phase 1 (core library) complete · Phase 2 (PySide6 GUI) complete · Phase 3 (compression + Office → PDF) complete · Phase 4 (Markdown export) complete · Phase 5 (packaging) complete · Phase 6 (air-gap validation) complete · **374 automated tests passing**

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [What "air-gap" means here](#2-what-air-gap-means-here)
3. [Validation environment](#3-validation-environment)
4. [Harness architecture](#4-harness-architecture)
5. [Network isolation and evidence](#5-network-isolation-and-evidence)
6. [Empty-environment and bundled-runtime evidence](#6-empty-environment-and-bundled-runtime-evidence)
7. [Core validation matrix](#7-core-validation-matrix)
8. [Encrypted PDFs](#8-encrypted-pdfs)
9. [Large inputs and stress coverage](#9-large-inputs-and-stress-coverage)
10. [Cancellation, atomicity, and cleanup](#10-cancellation-atomicity-and-cleanup)
11. [Install, uninstall, and `.deb` validation](#11-install-uninstall-and-deb-validation)
12. [Full test suite under isolation](#12-full-test-suite-under-isolation)
13. [Results summary](#13-results-summary)
14. [Changes made in Phase 6](#14-changes-made-in-phase-6)
15. [Limitations and manual clean-VM checklist](#15-limitations-and-manual-clean-vm-checklist)
16. [Project file map](#16-project-file-map)
17. [Appendix A — Commands](#appendix-a--commands)
18. [Appendix B — Air-gap check inventory](#appendix-b--air-gap-check-inventory)
19. [Appendix C — Sample validation log](#appendix-c--sample-validation-log)

---

## 1. Executive summary

Phases 1–5 produced a fully offline PDF application and a self-contained Linux release. Phase 6 answers the remaining release question: **does the packaged application actually behave as an air-gapped product on a machine that is not the development environment?**

Phase 6 adds a reproducible validation harness and runs it end-to-end:

- **`packaging/airgap_validate.sh`** — an orchestrator that runs the frozen release inside an unprivileged network namespace, traces socket syscalls, runs the core checks, runs the full test suite, performs two install/uninstall cycles, and extracts and runs the `.deb`.
- **`packaging/airgap_checks.py`** — 24 independent checks covering every feature area, encrypted PDFs, large inputs, cancellation, atomic failure, repeated runs, and temporary-file cleanup.
- **An expanded frozen `--self-test`** — grown from 8 to 16 checks so the packaged application exercises page operations, rasterize compression, and AES-256 encrypted PDFs, not just library loading.
- **Six new tests** (`tests/test_airgap.py`) that keep the harness contracts honest and run the core checks on a small fixture.

The validation run passed every check:

| Area | Result |
|---|---|
| Network namespace | Only loopback; no external interfaces |
| Frozen self-test under isolation | 16/16 checks passed |
| `strace` network trace | **0 network-family syscalls** |
| Empty environment, `PATH=/nonexistent` | Frozen self-test passed |
| Bundled Python/Qt/PDFium/QPDF | Present; no system Python/Qt dependency |
| Core air-gap checks | 24/24 passed |
| Full test suite under isolation | 374 passed |
| Install/uninstall, twice | Passed; no application files left behind |
| `.deb` extraction and run | Self-test passed; desktop entry valid |
| **Overall** | **AIR-GAP VALIDATION PASSED** |

The one thing this environment cannot provide is a genuine clean virtual machine running the oldest supported distribution. That remains a documented manual release step, with a concrete checklist in [§15](#15-limitations-and-manual-clean-vm-checklist). Everything that can be proven on the build host — namespace isolation, syscall evidence, empty-environment execution, bundled-runtime independence, and repeatable installs — has been proven.

---

## 2. What "air-gap" means here

PDFPad's product promise has three parts, and Phase 6 validates each separately:

1. **No network access is required.** The application must complete every conversion with the network namespace disconnected.
2. **No network access is attempted.** Even a failed connection attempt is undesirable in a high-security environment, so the validation traces socket syscalls rather than only checking that conversions succeed.
3. **No system conversion stack is required.** Core conversion must not depend on a system Python, Qt, Poppler, Ghostscript, or LibreOffice. LibreOffice remains an optional add-on.

A fourth, operational property matters for release hygiene:

4. **Runs leave no residue.** Temporary files, staged inputs, LibreOffice profiles, and atomic-output scratch files must be cleaned up after success, failure, and cancellation.

Phase 6 is structured around these four claims.

---

## 3. Validation environment

| Item | Value |
|---|---|
| Host distribution | Linux x86_64 |
| Kernel-provided namespaces | User and network namespaces available |
| Build host glibc | 2.39 |
| Declared target glibc | ≥ 2.34 |
| Python (build/source checks) | 3.12.3 |
| Frozen release | `dist/PDFPad-0.5.0-linux-x86_64/` |
| Debian package | `dist/pdfpad_0.5.0_amd64.deb` |
| Optional LibreOffice | System LibreOffice 24.2.7.2 (not bundled) |
| Display | None; Qt `offscreen` platform |
| Isolation tool | `unshare` |
| Syscall tracer | `strace` |
| Container/VM runtime | Not available on this host |

### 3.1 Why `unshare -Urn`

On this host, `unshare -n` alone fails with `Operation not permitted` because it requires `CAP_SYS_ADMIN`. The harness therefore prefers **`unshare -Urn`**, which creates a user namespace (mapping the current user to root inside it) and a network namespace together. This works unprivileged and still gives a network namespace with no external connectivity.

The script probes in this order:

1. `unshare -Urn true` — preferred.
2. `unshare -n true` — used when running as root or with the capability.
3. Otherwise it fails with guidance and offers `--no-isolation` for diagnostics only.

`--no-isolation` explicitly labels the run as **not** an air gap; it exists for debugging on restricted hosts, not for release sign-off.

### 3.2 Namespace contents

Inside the namespace:

```
Inter-|   Receive ... | Transmit ...
 face |bytes packets ...|
    lo:     0       0 ... 0       0 ... 0
```

Only the loopback interface exists, and it is down. There is no route to a real network, no DNS, and no external interface. The harness asserts that no `eth*`, `en*`, `wl*`, `wlan*`, `docker*`, `veth*`, or `br-*` interface is present.

---

## 4. Harness architecture

```
packaging/airgap_validate.sh
│
├── locate newest dist/PDFPad-*-linux-* release and dist/pdfpad_*.deb
├── choose isolation: unshare -Urn → unshare -n → fail
├── create work tree: home/ config/ state/ tmp/ trace/
│
├── 1. namespace interface audit
├── 2. frozen --self-test under isolation
├── 2b. frozen --self-test with env -i, PATH=/nonexistent
├── 2c. ldd/RUNPATH checks for bundled Python, Qt, PDFium, QPDF
├── 3. strace -f -e trace=network → assert no AF_INET/AF_INET6
├── 4. packaging/airgap_checks.py under isolation
├── 5. pytest suite under isolation
├── 6. install → self-test → desktop validate → uninstall (×2)
├── 7. dpkg-deb --extract → self-test → desktop validate
│
└── summary: AIR-GAP VALIDATION PASSED / FAILED
```

The work tree is isolated from the user's real configuration:

```bash
HOME=$WORK_ROOT/home
XDG_CONFIG_HOME=$WORK_ROOT/config
XDG_STATE_HOME=$WORK_ROOT/state
TMPDIR=$WORK_ROOT/tmp
QT_QPA_PLATFORM=offscreen
```

This means the validation never reads or writes the developer's real PDFPad settings, logs, or documents.

### 4.1 Failure handling

The script uses `set -euo pipefail` but wraps expected-failure checks in `if` statements and tracks a `FAILURES` counter. A single failed check does not abort the run; the summary reports the count and exits non-zero. This produces a complete picture in one pass rather than stopping at the first problem.

### 4.2 Release discovery

If `--release` is omitted, the script selects the newest `dist/PDFPad-*-linux-*` directory by modification time. The `.deb` is discovered similarly. This keeps the common case a single command after a build.

---

## 5. Network isolation and evidence

### 5.1 Conversion success without a network

The frozen `--self-test` ran inside the network namespace and passed all 16 checks. That self-test exercises:

- pypdf page operations
- PDFium rendering
- pdfminer text and Markdown extraction
- pikepdf lossless and rasterize compression
- Pillow images → PDF
- AES-256 encrypted PDF reading and rejection
- Qt window construction and icon loading

None of these paths requires a network connection.

### 5.2 Syscall trace

The harness runs:

```bash
unshare -Urn strace -f -qq -e trace=network \
    -o "$WORK_ROOT/trace/network.log" \
    PDFPad/PDFPad --self-test
```

Then it asserts that the trace contains no `AF_INET` or `AF_INET6` references. The observed trace file was **empty** — zero network-family syscalls, not merely zero successful connections. That is stronger than "the conversion worked offline": the application did not even create an IP socket.

The `-f` flag follows threads and child processes, so a network attempt from a worker thread or a subprocess would also be captured. Qt runs on the offscreen platform, so no X11 socket is needed; the trace confirms no AF_UNIX socket either.

### 5.3 What this does and does not prove

It proves the frozen application, with the tested operations, makes no IP socket calls. It does not prove the absence of every possible network path in untested code (for example, a future plugin). The source has no networking imports; the trace is a runtime confirmation of that design.

---

## 6. Empty-environment and bundled-runtime evidence

### 6.1 Empty environment and no `PATH`

The harness repeats the frozen self-test with a deliberately hostile environment:

```bash
unshare -Urn /usr/bin/env -i \
    PATH=/nonexistent \
    LANG=C.UTF-8 \
    HOME=... XDG_CONFIG_HOME=... XDG_STATE_HOME=... TMPDIR=... \
    QT_QPA_PLATFORM=offscreen \
    PDFPad/PDFPad --self-test
```

It passed. This is meaningful because:

- **No `PATH`** means the app cannot find `soffice`, `python`, `gs`, `pdftoppm`, or any other system binary.
- **No inherited environment** means no `LD_LIBRARY_PATH`, `PYTHONPATH`, `QT_PLUGIN_PATH`, or `PDFPAD_LIBREOFFICE` from the developer shell.
- The frozen executable still resolves its bundled libraries and completes every check.

The only diagnostic was Qt noting that `C` is not UTF-8 and switching to `C.UTF-8`; this is a locale warning, not a failure. The harness sets `LANG=C.UTF-8` to keep the run quiet.

### 6.2 Static dependency audit

The harness checks:

| Check | Method | Result |
|---|---|---|
| Frozen executable has no unresolved libraries | `ldd` | Passed |
| Frozen executable does not link system Python or Qt | `ldd \| grep libpython\|/usr/lib…libQt6` | Passed |
| Bundled Qt core has no system Python/Qt dependency | `ldd _internal/libQt6Core.so.6` | Passed |
| Qt core is present in the bundle | file existence | Passed |
| pypdfium2 and its native module are present | file existence | Passed |
| QPDF is present | `libqpdf-*.so*` glob | Passed |
| xcb platform plugin uses a bundle-relative RUNPATH | `readelf -d` contains `$ORIGIN/../../lib` | Passed |

The executable's dynamic dependencies are limited to the base system (`libc`, `libz`, `libdl`, `libpthread`, the loader). Qt, PDFium, and QPDF come from `_internal/`.

### 6.3 Relationship to the declared glibc floor

The build host reports glibc 2.39 while the product targets glibc ≥ 2.34. The bundled components do not require symbols newer than the target, but this has **not** been proven on an actual Ubuntu 22.04 / Mint 21 machine in this environment. That is the main remaining manual step (see [§15](#15-limitations-and-manual-clean-vm-checklist)).

---

## 7. Core validation matrix

`packaging/airgap_checks.py` runs 24 checks. It creates its own fixtures, so it does not depend on the test suite's fixtures or on user files. Every check reports `ok` or `FAILED` with timing and a short detail.

### 7.1 Fixtures

| Fixture | Description |
|---|---|
| `large.pdf` | 150 blank pages with varying page sizes and metadata |
| `small.pdf` | 3 blank pages |
| `encrypted.pdf` | 4 pages, AES-256, password `correct horse` |
| `noise-0..2.jpg` | Three 1200×1600 JPEGs with deterministic noise |
| `airgap.rtf` | Minimal RTF document for the optional Office check |

The large fixture is intentionally many-paged rather than many-megabyted: page-loop correctness, progress, and cleanup are the risks being tested, not raw throughput. The image fixture provides realistic multi-megabyte inputs.

### 7.2 Check inventory

| # | Check | What it proves |
|---|---|---|
| 1 | Large PDF created | Fixture generation and metadata writing |
| 2 | Page-range grammar | `parse_ranges` handles ranges, duplicates, open ranges |
| 3 | Extract pages | `extract_pages` selects the right pages |
| 4 | Split pages | `split_pdf` produces the expected chunk count |
| 5 | Merge PDFs | `merge_pdfs` concatenates in order |
| 6 | Rotate pages | Rotation is written and readable |
| 7 | PDF → PNG pages | PDFium renders selected pages at 72 DPI |
| 8 | PDF → JPEG pages | JPEG output and quality path |
| 9 | PDF thumbnails | Thumbnail sizing and resource cleanup |
| 10 | Images → PDF (A4 contain) | Pillow composition, page size, fit |
| 11 | Images → PDF (letter cover) | Second page-size/fit path |
| 12 | PDF → text | pdfminer extraction and atomic text file |
| 13 | PDF → Markdown | Markdown extraction and atomic file |
| 14 | Compress lossless | pikepdf/QPDF rewrite preserves page count |
| 15 | Compress rasterize | Render → JPEG → rebuild path |
| 16 | Repeated run | Same operation twice succeeds with identical output |
| 17 | Encrypted: page count | AES-256 read with the correct password |
| 18 | Encrypted: extract/render/text/md/compress | Every operation accepts the password |
| 19 | Encrypted: bad password rejected | Missing and wrong passwords raise `EncryptedPdfError` |
| 20 | Cancellation leaves no output | `OperationCancelled` and no partial file |
| 21 | Atomic failure preserves input | Refuses to overwrite input; input remains valid |
| 22 | Office → PDF (optional) | System LibreOffice path, when present |
| 23 | Temporary files cleaned | Library-created temp directory is empty |
| 24 | Atomic temp files cleaned | No `.tmp`/`.txt` scratch files remain |

All 24 passed.

### 7.3 Interpreting the blank-page text results

The fixtures are blank pages, so text extraction returns whitespace (298 characters across 150 pages) and Markdown returns an empty string. These checks prove the extraction pipeline runs and writes files atomically; they do not attempt to measure OCR or layout fidelity. Text/Markdown fidelity is covered by the dedicated fixtures in `tests/test_text.py` and `tests/test_markdown.py`.

---

## 8. Encrypted PDFs

Password handling is validated at three levels:

1. **Correct password** — page count, extraction, rendering, text, Markdown, and compression all accept the password.
2. **Missing password** — `EncryptedPdfError` is raised rather than a crash or empty result.
3. **Wrong password** — `EncryptedPdfError` is raised.

The fixture uses **AES-256**, the strongest encryption pypdf supports, rather than legacy RC4. The compressed encrypted output remains readable with the same password, confirming pikepdf preserves encryption rather than silently decrypting the file.

This complements the GUI tests, which cover the password prompt and retry flow.

---

## 9. Large inputs and stress coverage

The default validation uses a **150-page** PDF. The page count is configurable:

```bash
./packaging/airgap_validate.sh --pages 500
```

The large fixture is used for:

- page count and range parsing
- extraction, splitting (25-page chunks), merging, and rotation
- rendering 5 PNG pages and 2 JPEG pages
- thumbnail generation
- text and Markdown extraction
- lossless compression

The image fixtures are 1200×1600 JPEGs; the resulting A4 PDF was about **3.35 MB**, exercising Pillow's decode, resize, composition, and JPEG encoding paths.

The validation does not claim performance benchmarking. A 150-page run completes in well under a second for most operations on this host; the goal is correctness under realistic size, not throughput claims.

---

## 10. Cancellation, atomicity, and cleanup

### 10.1 Cancellation

The harness calls `extract_pages` with `cancel=lambda: True` and asserts:

- `OperationCancelled` is raised.
- The destination file does **not** exist.
- No atomic scratch file remains.

This confirms the cooperative cancellation contract survives packaging.

### 10.2 Atomic failure

The harness attempts `compress_pdf(large, large)`, which is rejected with `PdfOperationError` before any write. It then re-opens the input and confirms:

- the file size is unchanged;
- the page count is still 150;
- the input is still a valid PDF.

### 10.3 Temporary-file cleanup

Every library-created temporary file is routed through an audited directory:

```python
os.environ["TMPDIR"] = str(scratch)
tempfile.tempdir = str(scratch)
```

After all operations, the harness asserts that the scratch directory is empty. It also scans the work tree for atomic-output leftovers (hidden files ending in `.tmp` or `.txt`). Both checks passed.

This covers:

- `TemporaryDirectory` used by rasterize compression;
- `TemporaryDirectory` used by Office staging and the LibreOffice profile;
- `atomic_output` scratch files in destination directories;
- temporary files created by the libraries themselves.

### 10.4 Repeated runs

Compression is run twice to the same destination. Both runs succeed and produce identical file sizes, confirming that a second run does not fail on an existing output and that the atomic replace path is stable.

---

## 11. Install, uninstall, and `.deb` validation

### 11.1 Two install/uninstall cycles

For each round, the harness:

1. Installs the release into a fresh prefix with `install.sh --prefix`.
2. Runs the installed `bin/pdfpad --self-test` inside the network namespace.
3. Validates the generated desktop entry with `desktop-file-validate`.
4. Uninstalls with `install.sh --prefix ... --uninstall`.
5. Asserts that the application executable and launcher are gone.

Both rounds passed. This checks idempotence and ensures the uninstaller removes what the installer created.

### 11.2 Debian package

The harness extracts the newest `.deb` with `dpkg-deb --extract` and:

- runs `/opt/pdfpad/PDFPad --self-test` inside the network namespace;
- validates `/usr/share/applications/pdfpad.desktop`.

Both passed. The package's application is the same frozen onedir tree as the tarball, so the core checks apply equally.

### 11.3 What is not installed

The validation deliberately does **not** run `apt install` or modify the host package database. It extracts the `.deb` into a temporary root and runs the application from there. This avoids requiring root and avoids changing the host.

---

## 12. Full test suite under isolation

The entire pytest suite runs inside the network namespace:

```bash
unshare -Urn .venv/bin/python -m pytest -q -p faulthandler tests
```

Result:

```
374 passed in 8.56s
```

This includes:

- all core conversion tests;
- GUI tests via Qt `offscreen`;
- Office tests with a fake `soffice`;
- packaging tests;
- the new air-gap harness tests.

Running the suite under isolation is a stronger check than running it normally: it proves the tests themselves do not depend on network access, DNS, or a system service.

---

## 13. Results summary

### 13.1 Harness results

| Check group | Passed |
|---|---|
| Namespace interface audit | 1 |
| Frozen self-test (internal checks) | 16 |
| Minimal-environment self-test | 1 |
| Bundled runtime/dependency checks | 7 |
| Network syscall trace | 1 |
| Core air-gap checks | 24 |
| Test suite under isolation | 1 (374 tests) |
| Install/uninstall cycles (2 rounds) | 10 |
| `.deb` extraction/run/desktop | 3 |
| **Total reported `ok` lines** | **66** |
| **Failures** | **0** |

### 13.2 Evidence highlights

- **Zero network-family syscalls** in the `strace` log.
- Frozen self-test passes with `PATH=/nonexistent` and an empty environment.
- `ldd` shows no system Python or Qt dependency.
- 150-page PDF processed end-to-end.
- AES-256 encrypted PDF processed by every operation.
- Cancellation and atomic failure leave no output or damage.
- Temporary and atomic scratch directories are empty after the run.
- Two install/uninstall cycles leave no application files.
- `.deb` application passes the same self-test.

### 13.3 Final verdict

```
AIR-GAP VALIDATION PASSED
```

---

## 14. Changes made in Phase 6

### 14.1 New files

| File | Purpose |
|---|---|
| `packaging/airgap_validate.sh` | End-to-end air-gap orchestrator |
| `packaging/airgap_checks.py` | 24 core validation checks |
| `tests/test_airgap.py` | 6 harness/self-test tests |
| `report/PDFPad-Phase6-Report.md` | This report |

### 14.2 Modified files

| File | Change |
|---|---|
| `gui/app.py` | `run_self_test()` expanded from 8 to 16 checks: page operations, ranges, rasterize compression, AES-256 encrypted PDFs |
| `README.md` | Phase 6 status and air-gap validation instructions |
| `/home/kvy/.opencode/plan/pdfpad-linux-plan.md` | Phase 6 marked complete |

### 14.3 Test count

| Phase | Tests |
|---|---|
| Phase 4 | 345 |
| Phase 5 | 368 |
| Phase 6 | **374** |

---

## 15. Limitations and manual clean-VM checklist

### 15.1 What this environment could not test

1. **A genuine clean VM.** No container runtime or VM was available. The validation ran on the build host, using namespaces and an empty environment to approximate isolation. This does not prove the glibc ≥ 2.34 floor on Ubuntu 22.04 / Mint 21.
2. **Interactive GUI behaviour.** The GUI is constructed and shown with Qt `offscreen`. Real window-manager integration, drag-and-drop from a file manager, and native file dialogs were not exercised in Phase 6.
3. **The bundled LibreOffice add-on.** No `office/program/soffice` tree was present, so the optional Office check used the system LibreOffice 24.2.7.2. The add-on's own portability still needs a clean-VM smoke test when the pack is assembled.
4. **Network firewalling beyond a namespace.** The namespace has no connectivity; the harness does not additionally install firewall rules or test under a hostile proxy configuration.
5. **Very large files.** The largest fixture is 150 pages and a few megabytes. Multi-hundred-megabyte scanned PDFs were not tested.
6. **Long-duration stability.** The suite is fast and repeated a few times; no soak test was run.
7. **AppImage.** Deferred by the plan; not validated.

### 15.2 Manual clean-VM checklist

Run this on a fresh Ubuntu 22.04 / Mint 21 VM with **no network adapter** and **no Python, Qt, or LibreOffice installed**:

1. Copy `PDFPad-0.5.0-linux-x86_64.tar.gz` to the VM by removable media.
2. Verify the checksum out-of-band.
3. Extract and run:
   ```bash
   tar -xzf PDFPad-0.5.0-linux-x86_64.tar.gz
   cd PDFPad-0.5.0-linux-x86_64
   QT_QPA_PLATFORM=offscreen PDFPad/PDFPad --self-test
   ```
4. Run `./install.sh` and launch PDFPad from the application menu.
5. Exercise every operation on real documents:
   - extract, split, merge, rotate
   - PDF → PNG/JPEG
   - images → PDF
   - text and Markdown export
   - lossless and rasterize compression
   - a password-protected PDF
6. Confirm Office → PDF is disabled without the add-on, then repeat with `PDFPad/office/program/soffice` present.
7. Check `~/.local/state/pdfpad/pdfpad.log` for errors.
8. Verify no unexpected files under `/tmp`, the destination folders, or the install prefix after each run.
9. Uninstall and confirm the application files are removed.
10. Repeat with `sudo apt install ./pdfpad_0.5.0_amd64.deb` and launch from the menu.

Record the distribution, glibc version, desktop environment, and any missing xcb libraries.

---

## 16. Project file map

```
pdfpad/
├── core/                         # GUI-independent conversion library
├── gui/
│   └── app.py                    # version, icon, --self-test (16 checks)
├── office/                       # optional LibreOffice add-on (README by default)
├── packaging/
│   ├── pdfpad.spec               # PyInstaller onedir spec
│   ├── entrypoint.py             # frozen entry point
│   ├── build_linux.sh            # build + frozen self-test gate + tarball
│   ├── build_deb.sh              # Debian package builder
│   ├── make_icons.py             # icon generation
│   ├── collect_licenses.py       # license bundle
│   ├── airgap_validate.sh        # Phase 6 end-to-end harness
│   ├── airgap_checks.py          # Phase 6 core checks
│   ├── licenses/
│   └── linux/                    # installer, desktop, MIME, icons
├── tests/
│   ├── test_airgap.py            # Phase 6 harness/self-test tests
│   └── test_*.py                 # core, GUI, Office, packaging
├── report/
│   ├── PDFPad-Phase1-2-Report.md
│   ├── PDFPad-Phase3-Report.md
│   ├── PDFPad-Phase4-Report.md
│   ├── PDFPad-Phase5-Report.md
│   └── PDFPad-Phase6-Report.md
├── dist/                         # build output (git-ignored)
├── pyproject.toml                # version 0.5.0
└── README.md
```

---

## Appendix A — Commands

### Run the full air-gap validation

```bash
./packaging/airgap_validate.sh
```

### Use a larger fixture

```bash
./packaging/airgap_validate.sh --pages 500
```

### Skip optional or slow parts

```bash
./packaging/airgap_validate.sh --no-office
./packaging/airgap_validate.sh --no-tests
./packaging/airgap_validate.sh --no-install
./packaging/airgap_validate.sh --keep        # keep the work tree
```

### Run only the core checks

```bash
unshare -Urn .venv/bin/python packaging/airgap_checks.py
```

### Diagnostic run without isolation (not an air gap)

```bash
./packaging/airgap_validate.sh --no-isolation
```

### Rebuild the release before validating

```bash
./packaging/build_linux.sh --deb
./packaging/airgap_validate.sh
```

---

## Appendix B — Air-gap check inventory

### Harness checks (`airgap_validate.sh`)

| Check | Pass condition |
|---|---|
| Namespace interfaces | No external interface names |
| Frozen self-test | Exit 0 under isolation |
| Minimal environment | Exit 0 with `PATH=/nonexistent` |
| Frozen executable dependencies | `ldd` clean, no system Python/Qt |
| Bundled Qt core dependencies | `ldd` clean, no system Python/Qt |
| Bundled components | Qt core, pypdfium2, pypdfium2_raw, QPDF present |
| xcb RUNPATH | Contains `$ORIGIN/../../lib` |
| Network trace | No `AF_INET`/`AF_INET6` |
| Core checks | 24/24 pass |
| Test suite | 374 pass under isolation |
| Install round 1/2 | `install.sh` exits 0 |
| Installed self-test 1/2 | Exit 0 |
| Desktop validation 1/2 | `desktop-file-validate` exits 0 |
| Uninstall 1/2 | `install.sh --uninstall` exits 0 |
| Uninstall residue 1/2 | No app executable/launcher |
| `.deb` extraction | `dpkg-deb --extract` exits 0 |
| `.deb` self-test | Exit 0 |
| `.deb` desktop entry | Validates |

### Core checks (`airgap_checks.py`)

See the 24-row inventory in [§7.2](#72-check-inventory).

---

## Appendix C — Sample validation log

The following is an abridged transcript of the successful run (timings vary):

```
PDFPad air-gap validation
  release:   .../dist/PDFPad-0.5.0-linux-x86_64
  isolation: unshare -Urn (user + network namespace)
  work:      /tmp/opencode/pdfpad-airgap

ok      network namespace has no external interfaces

== Frozen application self-test ==
ok  pypdf page count
ok  page range parser
ok  extract pages
ok  split pages
ok  merge PDFs
ok  rotate pages
ok  pypdfium2 render
ok  pdfminer text
ok  pdfminer markdown
ok  pikepdf lossless
ok  pikepdf rasterize
ok  Pillow images to PDF
ok  encrypted read with password
ok  encrypted rejects missing password
ok  Qt window
ok  Qt icon
PDFPad 0.5.0 self-test passed
ok      frozen --self-test under isolation

== Minimal environment ==
ok      frozen self-test with empty environment and no PATH

== Bundled runtime dependencies ==
ok      frozen executable resolves without system Python/Qt
ok      bundled Qt core resolves without system Python/Qt
ok      bundled: libQt6Core.so.6
ok      bundled: pypdfium2
ok      bundled: pypdfium2_raw
ok      bundled: QPDF
ok      xcb plugin uses a bundle-relative RUNPATH

== Network syscall trace ==
ok      no AF_INET/AF_INET6 socket calls

== Core conversion checks ==
ok      large PDF created                        0.00s  (150 pages)
ok      page-range grammar                       0.00s
ok      extract pages                            0.02s  (4 of 150)
ok      split pages                              0.05s  (6 chunks)
ok      merge PDFs                               0.01s  (29 pages)
ok      rotate pages                             0.06s  (rotation 180)
ok      PDF -> PNG pages                         0.09s  (5 PNGs)
ok      PDF -> JPEG pages                        0.02s  (2 JPEGs)
ok      PDF thumbnails                           0.00s  (8 thumbnails)
ok      images -> PDF (A4 contain)               0.46s  (3350 KiB)
ok      images -> PDF (letter cover)             0.27s  (letter cover)
ok      PDF -> text                              0.08s  (298 chars (blank pages))
ok      PDF -> Markdown                          0.06s  (0 chars (blank pages))
ok      compress lossless                        0.03s  (18 -> 1 KiB)
ok      compress rasterize                       0.06s  (44 KiB)
ok      repeated run                             0.00s  (identical output)
ok      encrypted: page count                    0.01s  (4 pages)
ok      encrypted: extract/render/text/md/compress   0.10s  (text 6, md 0)
ok      encrypted: bad password rejected         0.02s  (missing and wrong rejected)
ok      cancellation leaves no output            0.01s  (no output)
ok      atomic failure preserves input           0.01s  (input intact)
ok      Office -> PDF (optional backend)         1.83s  (system: LibreOffice 24.2.7.2)
ok      temporary files cleaned                  0.00s  (temporary directory empty)
ok      atomic temp files cleaned                0.00s  (no .tmp files)

All 24 air-gap checks passed.
ok      core air-gap checks

== Test suite under isolation ==
374 passed in 8.56s
ok      pytest suite under isolation

== Install/uninstall cycle ==
ok      install round 1
ok      installed app self-test round 1
ok      desktop entry validates round 1
ok      uninstall round 1
ok      uninstall removed application files round 1
ok      install round 2
ok      installed app self-test round 2
ok      desktop entry validates round 2
ok      uninstall round 2
ok      uninstall removed application files round 2

== Debian package ==
ok      extracted pdfpad_0.5.0_amd64.deb
ok      .deb application self-test under isolation
ok      .deb desktop entry validates

AIR-GAP VALIDATION PASSED
```

---

**Phase 6 verdict:** the packaged application performs all core conversions with no network namespace connectivity, makes no IP socket calls, runs without a `PATH` or system Python/Qt, leaves no temporary residue, installs and uninstalls cleanly, and passes the full test suite under isolation. A true clean-VM run on the oldest supported distribution remains the final manual release gate.
