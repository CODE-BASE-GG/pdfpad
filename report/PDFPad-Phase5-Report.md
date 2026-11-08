# PDFPad — Phase 5 Implementation Report

**Project:** PDFPad — an offline PDF conversion desktop application for Linux  
**Version:** 0.5.0  
**Report date:** 2026-11-08  
**Target platform:** Linux x86_64, glibc ≥ 2.34 (Ubuntu 22.04 / Linux Mint 21 or newer)  
**Runtime model:** fully offline, no network calls, no system binaries required for core conversion  
**Current status:** Phase 1 (core library) complete · Phase 2 (PySide6 GUI) complete · Phase 3 (compression + Office → PDF) complete · Phase 4 (Markdown export) complete · Phase 5 (packaging) complete · **368 automated tests passing**

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [What Phase 5 delivers](#2-what-phase-5-delivers)
3. [Packaging architecture](#3-packaging-architecture)
4. [The PyInstaller build](#4-the-pyinstaller-build)
5. [The release directory](#5-the-release-directory)
6. [The portable installer](#6-the-portable-installer)
7. [The Debian package](#7-the-debian-package)
8. [Desktop integration: entry, MIME, icons](#8-desktop-integration-entry-mime-icons)
9. [Licensing and compliance](#9-licensing-and-compliance)
10. [Runtime self-test and frozen-resource handling](#10-runtime-self-test-and-frozen-resource-handling)
11. [Verification performed](#11-verification-performed)
12. [Testing and quality assurance](#12-testing-and-quality-assurance)
13. [Design decisions and rationale](#13-design-decisions-and-rationale)
14. [Limitations and known issues](#14-limitations-and-known-issues)
15. [Roadmap: Phase 6](#15-roadmap-phase-6)
16. [Project file map](#16-project-file-map)
17. [Appendix A — Build and install quick reference](#appendix-a--build-and-install-quick-reference)
18. [Appendix B — Release contents](#appendix-b--release-contents)
19. [Appendix C — Test inventory](#appendix-c--test-inventory)

---

## 1. Executive summary

Phases 1–4 produced a working, offline PDF application: a GUI-independent core library, a PySide6 desktop shell, compression and optional Office conversion, and best-effort Markdown export. Everything up to that point ran from a Python virtual environment. Phase 5 turns that source tree into a **distributable Linux product**.

Phase 5 adds:

- **A reproducible PyInstaller `--onedir` build** driven by a spec file that bundles the icon, collects the native PDF engines, and excludes unused Qt modules.
- **A build orchestrator** (`packaging/build_linux.sh`) that regenerates icons, runs PyInstaller, executes a frozen `--self-test` **before** producing a release, collects licenses, writes version metadata, and creates the tarball (optionally a `.deb`).
- **A portable release layout** containing the application, a user/system installer, desktop entry, MIME definition, SVG and PNG icons, README, and the full third-party license bundle.
- **`install.sh`** supporting per-user installs (`~/.local`), system installs (`/usr/local`), arbitrary prefixes, uninstall, and optional default-handler registration.
- **An optional Debian package** that installs under `/opt/pdfpad`, adds `/usr/bin/pdfpad`, registers desktop/MIME/icons, and ships license documentation.
- **Programmatic icon generation** so the repository carries no opaque binary icon source.
- **License collection** from installed wheels plus system copies for components whose wheels omit license files.
- **A runtime `--self-test`** that exercises pypdf, PDFium, pdfminer, pikepdf, Pillow, and a headless Qt window — the same smoke test used to gate the build.

The packaged application remains faithful to the product's central promise: it makes **no network requests**, and every core conversion uses bundled libraries. LibreOffice remains an optional add-on that is simply absent from the default build.

The test suite grew from **345 to 368 passing tests**, with 23 new packaging tests. A real build, the frozen self-test, a tarball install/uninstall cycle, and a `.deb` extraction were all executed successfully.

---

## 2. What Phase 5 delivers

### 2.1 Deliverables at a glance

| Deliverable | Location | Status |
|---|---|---|
| PyInstaller spec (onedir) | `packaging/pdfpad.spec` | Implemented |
| Frozen entry point | `packaging/entrypoint.py` | Implemented |
| Main build orchestrator | `packaging/build_linux.sh` | Implemented |
| Debian package builder | `packaging/build_deb.sh` | Implemented |
| Portable installer/uninstaller | `packaging/linux/install.sh` | Implemented |
| Desktop entry template | `packaging/linux/pdfpad.desktop.in` | Implemented |
| MIME definition | `packaging/linux/pdfpad-mime.xml` | Implemented |
| Scalable icon | `packaging/linux/pdfpad.svg` | Implemented |
| Raster icons, 16–512 px | `packaging/linux/icons/hicolor/*/apps/pdfpad.png` | Generated |
| Icon generator | `packaging/make_icons.py` | Implemented |
| License collector | `packaging/collect_licenses.py` | Implemented |
| Third-party notices | `packaging/licenses/THIRD_PARTY_NOTICES.md` | Implemented |
| Runtime icon | `gui/resources/pdfpad.png` | Generated |
| Version/self-test CLI | `gui/app.py` (`--version`, `--self-test`) | Implemented |
| Packaging tests | `tests/test_packaging.py` | 23 tests |
| Portable tarball | `dist/PDFPad-0.5.0-linux-x86_64.tar.gz` | Built |
| Debian package | `dist/pdfpad_0.5.0_amd64.deb` | Built |

### 2.2 What did *not* change

Phase 5 is packaging-only. The core conversion semantics, GUI workflow, progress/cancellation model, password handling, and atomic-output guarantees are unchanged from Phase 4. The only application-code changes are:

- Version bumped to `0.5.0`.
- Application icon loading that works both from source and from a frozen bundle.
- `--version` and `--self-test` command-line flags.
- `APP_VERSION` centralised in `gui/app.py`.

This keeps the packaging work low-risk: the same tested core is shipped, just inside a self-contained runtime.

---

## 3. Packaging architecture

### 3.1 Layered design

```
Source tree
   │
   ├── packaging/make_icons.py ──────────► gui/resources/pdfpad.png
   │                                      packaging/linux/icons/hicolor/*/apps/pdfpad.png
   │
   ├── packaging/pdfpad.spec ────────────► dist/PDFPad/            (PyInstaller onedir)
   │        ▲
   │        └── packaging/entrypoint.py  (from gui.app import main)
   │
   ├── packaging/build_linux.sh ─────────► frozen --self-test gate
   │                                      license collection
   │                                      version metadata
   │                                      release directory + tarball
   │
   ├── packaging/build_deb.sh ───────────► dist/pdfpad_<version>_<arch>.deb
   │
   └── packaging/linux/install.sh ───────► $PREFIX/{bin,lib,share}
```

The build has a single entry point, `packaging/build_linux.sh`, and a strict order of operations:

1. Validate the interpreter and that PyInstaller is installed.
2. Read the version from `pyproject.toml` (single source of truth).
3. Regenerate icons so the build cannot drift from `make_icons.py`.
4. Run PyInstaller with the spec.
5. Run the **frozen** `--self-test`. A failure aborts the release.
6. Assemble the release directory and copy desktop assets.
7. Optionally bundle a LibreOffice add-on if `office/program/soffice` exists.
8. Collect licenses into `licenses/`.
9. Write `VERSION` metadata.
10. Create the tarball.
11. Optionally invoke the `.deb` builder.

Because the self-test runs against the **frozen executable**, it validates the actual native libraries that will ship, not the virtual environment.

### 3.2 Why onedir rather than onefile

The plan called for `--onedir`. It is the right trade-off here:

- **Faster startup** — no self-extraction to a temporary directory on every launch.
- **Smaller resident overhead** — Qt and PDFium are mapped from disk as needed.
- **Inspectable** — the bundled libraries and license files are visible in the release.
- **Predictable temp usage** — important on locked-down machines with small `/tmp`.
- **Easier troubleshooting** — `_internal/` can be inspected without unpacking.

The cost is a directory rather than a single file, which the tarball and `.deb` both handle naturally.

### 3.3 Version as a single source of truth

`pyproject.toml` holds `version = "0.5.0"`. The build script reads it with `tomllib`, `gui/app.py` exposes it as `APP_VERSION`, and a test asserts the two agree. Release names, the `VERSION` file, and the `.deb` filename all derive from it, so a version bump cannot leave the artifacts inconsistent.

---

## 4. The PyInstaller build

### 4.1 Spec structure

`packaging/pdfpad.spec` is a standard onedir spec:

- `Analysis([entrypoint.py])` with `pathex` set to the project root.
- `datas` bundles `gui/resources/pdfpad.png` so the window icon works when frozen.
- `hiddenimports=["pikepdf._core"]` ensures the compiled pikepdf extension is collected.
- A large `excludes` list drops unused Qt modules.
- `EXE(... exclude_binaries=True, name="PDFPad", console=False)` produces a GUI executable.
- `COLLECT(...)` produces `dist/PDFPad/`.

### 4.2 Entry point

`packaging/entrypoint.py` is deliberately tiny:

```python
from gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
```

Using a dedicated entry point keeps PyInstaller from importing the GUI package as a script, and it preserves `main()`'s exit code for the self-test gate.

### 4.3 Qt module exclusions

The spec excludes modules PDFPad never imports, including:

- 3D: `Qt3DAnimation`, `Qt3DCore`, `Qt3DExtras`, `Qt3DInput`, `Qt3DLogic`, `Qt3DRender`
- QML/Quick: `QtQml`, `QtQuick`, `QtQuickControls2`, `QtQuickTest`, `QtQuickWidgets`
- Web: `QtWebChannel`, `QtWebEngineCore`, `QtWebEngineQuick`, `QtWebEngineWidgets`, `QtWebSockets`, `QtHttpServer`
- Data/design: `QtSql`, `QtCharts`, `QtDataVisualization`, `QtGraphs`, `QtDesigner`, `QtUiTools`
- Other: `QtBluetooth`, `QtNfc`, `QtLocation`, `QtPositioning`, `QtMultimedia`, `QtMultimediaWidgets`, `QtSensors`, `QtSerialPort`, `QtTest`, `QtHelp`, `QtPdf`, `QtPdfWidgets`, `QtRemoteObjects`, `QtScxml`, `QtStateMachine`, `QtTextToSpeech`, `QtXml`, `QtSpatialAudio`, `QtNetworkAuth`

This keeps the release smaller and avoids shipping QML runtimes, database drivers, and designer plugins that are irrelevant to a PDF utility. The `tkinter` exclusion removes a second GUI toolkit entirely.

### 4.4 Bundled native components

The frozen build carries its own native engines, so the target machine needs no conversion binaries:

| Capability | Bundled component |
|---|---|
| PDF parsing/writing | `pypdf` (pure Python) |
| Rendering | `pypdfium2` + PDFium |
| Compression/rewriting | `pikepdf` + QPDF |
| Images | Pillow + its codec libraries |
| Text extraction | `pdfminer.six` + CMaps |
| GUI | PySide6 + Qt 6 + xcb platform plugin |

`ldd` inspection confirmed that the main executable and Qt core depend only on standard glibc-era libraries, while the xcb platform plugin resolves its Qt libraries through an `$ORIGIN`-relative `RUNPATH` (`$ORIGIN/../../lib`) and finds `libxcb-cursor` inside the bundle. The release therefore does not rely on a system Qt installation.

### 4.5 Build output

| Artifact | Size |
|---|---|
| `dist/PDFPad/` (onedir application) | ~219 MB |
| `dist/PDFPad-0.5.0-linux-x86_64/` (release directory) | ~220 MB |
| `dist/PDFPad-0.5.0-linux-x86_64.tar.gz` | ~88 MB |
| `dist/pdfpad_0.5.0_amd64.deb` | ~69 MB |

The `.deb` is smaller than the tarball because `dpkg-deb` compresses its data archive more aggressively than `gzip` at the default level.

---

## 5. The release directory

A build produces `dist/PDFPad-<version>-linux-<arch>/`:

```
PDFPad-0.5.0-linux-x86_64/
├── PDFPad/                  # PyInstaller onedir application
│   ├── PDFPad               # executable
│   ├── _internal/           # Python runtime, Qt, PDFium, QPDF, data
│   └── office/              # optional, only if an add-on was present
├── install.sh               # portable installer/uninstaller
├── pdfpad.desktop.in        # desktop entry template (@EXEC@ placeholder)
├── pdfpad-mime.xml          # application/pdf MIME definition
├── pdfpad.svg               # scalable icon
├── icons/
│   └── hicolor/{16..512}x{...}/apps/pdfpad.png
├── licenses/                # collected license texts + MANIFEST + notices
├── README.md
└── VERSION                  # name, version, arch, build time, python, glibc
```

The `VERSION` file records provenance:

```
name=PDFPad
version=0.5.0
arch=x86_64
built=2026-11-08T12:53:13Z
python=3.12.3
glibc=2.39
```

Recording the build host's glibc is intentional: the declared target is glibc ≥ 2.34, while the build host reports 2.39. Shipping from a newer host is only safe because the bundled components do not require symbols newer than the target; Phase 6 should validate this on an older distribution (see [§14](#14-limitations-and-known-issues)).

The tarball is created with a top-level directory, so extraction is clean:

```bash
tar -xzf PDFPad-0.5.0-linux-x86_64.tar.gz
cd PDFPad-0.5.0-linux-x86_64
```

---

## 6. The portable installer

`install.sh` installs a release into a prefix without requiring a package manager. It supports:

| Option | Effect |
|---|---|
| *(none)* | Install for the current user under `~/.local` |
| `--prefix DIR` | Install under an arbitrary prefix |
| `--system` | Install system-wide under `/usr/local` (requires root) |
| `--uninstall` | Remove the installation at the selected prefix |
| `--set-default` | Register PDFPad as the default `application/pdf` handler |
| `-h`, `--help` | Show usage |

### 6.1 Installed layout

For a prefix `$PREFIX`:

```
$PREFIX/
├── bin/pdfpad -> $PREFIX/lib/pdfpad/PDFPad
├── lib/pdfpad/                 # the full onedir application
└── share/
    ├── applications/pdfpad.desktop
    ├── icons/hicolor/{scalable,16x16,...,512x512}/apps/pdfpad.*
    └── mime/packages/pdfpad-mime.xml
```

The launcher is a symlink to the real executable, which keeps the application tree self-contained and makes uninstall a matter of removing known paths.

### 6.2 Behaviour details

- **Root check** — `--system` fails early if the effective UID is not 0, with a clear message.
- **Prefix expansion** — a leading `~` or `~/` in `--prefix` is expanded to `$HOME`.
- **Executable substitution** — the desktop template's `@EXEC@` placeholder is replaced with the absolute installed executable path, so the launcher works regardless of `PATH`.
- **Icon installation** — the scalable SVG is installed once, and every generated PNG size is copied to the matching `hicolor` directory.
- **Cache refresh** — `update-desktop-database`, `update-mime-database`, and `gtk-update-icon-cache` are invoked when available, and failures are non-fatal.
- **Default handler** — `--set-default` calls `xdg-mime default pdfpad.desktop application/pdf` and warns if `xdg-mime` is missing.
- **PATH hint** — for a `~/.local` install, the script notes when `~/.local/bin` is not on `PATH`.
- **Uninstall** — removes the application tree, launcher, desktop entry, MIME file, and all icon sizes, then refreshes caches. **User settings and logs are intentionally left untouched.**

The installer is deliberately conservative: it never deletes unrelated files and only removes paths it created.

### 6.3 Verified install cycle

The release installer was exercised against a throwaway prefix:

```bash
./dist/PDFPad-0.5.0-linux-x86_64/install.sh --prefix /tmp/opencode/pdfpad-install
desktop-file-validate /tmp/opencode/pdfpad-install/share/applications/pdfpad.desktop
/tmp/opencode/pdfpad-install/bin/pdfpad --self-test
./dist/PDFPad-0.5.0-linux-x86_64/install.sh --prefix /tmp/opencode/pdfpad-install --uninstall
```

Results:

- Install completed and created the expected `bin`, `lib`, and `share` tree.
- The generated desktop entry passed `desktop-file-validate`.
- The **installed** application passed the frozen self-test.
- Uninstall removed the application, launcher, desktop entry, MIME file, and icons.
- Only empty directories and regenerated shared caches remained — no stray application files.

---

## 7. The Debian package

`packaging/build_deb.sh <release-dir>` turns a release directory into a standard `.deb`. It is invoked automatically by `build_linux.sh --deb`.

### 7.1 Package metadata

| Field | Value |
|---|---|
| Package | `pdfpad` |
| Version | Read from the release `VERSION` file |
| Architecture | `dpkg --print-architecture` (overridable with `DEB_ARCH`) |
| Section | `utils` |
| Priority | `optional` |
| Maintainer | `PDFPad Maintainers <maintainers@pdfpad.invalid>` |
| Installed-Size | Computed with `du -sk` |

### 7.2 Dependencies

The control file declares the minimum runtime the bundled Qt/xcb stack needs:

- **Depends:** `libc6 (>= 2.34)`, `libx11-6`, `libxcb1`, `libxkbcommon0`, `libglib2.0-0`, `libfontconfig1`, `libfreetype6`, `libdbus-1-3`, `libgl1`
- **Recommends:** the xcb helper libraries (`libxcb-cursor0`, `libxcb-icccm4`, `libxcb-image0`, `libxcb-keysyms1`, `libxcb-randr0`, `libxcb-render-util0`, `libxcb-shape0`, `libxcb-sync1`, `libxcb-xfixes0`, `libxkbcommon-x11-0`) plus `libegl1` and `libopengl0`

The `libc6 (>= 2.34)` floor matches the product's stated target. `Recommends` rather than `Depends` is used for the xcb helpers because they are only needed on an X11 session and the exact set varies across distributions.

### 7.3 Installed layout

```
/opt/pdfpad/                                  # full onedir application
/usr/bin/pdfpad -> /opt/pdfpad/PDFPad         # launcher symlink
/usr/share/applications/pdfpad.desktop
/usr/share/icons/hicolor/{scalable,16..512}/apps/pdfpad.*
/usr/share/mime/packages/pdfpad-mime.xml
/usr/share/doc/pdfpad/                        # licenses, README, copyright
```

### 7.4 Maintainer scripts

- `postinst` refreshes the desktop database, MIME database, and icon cache when the tools exist.
- `postrm` performs the same refresh after removal.

Both scripts are defensive (`|| true`, `exit 0`) so a missing optional tool never fails an install.

### 7.5 Ownership and reproducibility

The package is built with `dpkg-deb --build --root-owner-group`, so files are owned by `root:root` even when the build runs as a normal user. This avoids the common "package contains files owned by uid 1000" defect.

### 7.6 Verified package

The built package was inspected and extracted:

```bash
dpkg-deb --info dist/pdfpad_0.5.0_amd64.deb
dpkg-deb --contents dist/pdfpad_0.5.0_amd64.deb
dpkg-deb --extract dist/pdfpad_0.5.0_amd64.deb /tmp/opencode/pdfpad-deb-extract
desktop-file-validate /tmp/opencode/pdfpad-deb-extract/usr/share/applications/pdfpad.desktop
/tmp/opencode/pdfpad-deb-extract/opt/pdfpad/PDFPad --self-test
```

The extracted application passed the frozen self-test and the desktop entry validated. The package includes the launcher symlink, desktop entry, MIME definition, SVG and PNG icons, and license documentation.

> **Note:** `dpkg-deb --contents … | head` can emit a broken-pipe warning. This is a shell pipeline artifact, not a package defect.

---

## 8. Desktop integration: entry, MIME, icons

### 8.1 Desktop entry

`packaging/linux/pdfpad.desktop.in` is a template because the executable path is not known until install time:

```ini
[Desktop Entry]
Version=1.0
Type=Application
Name=PDFPad
GenericName=PDF Converter
Comment=Offline PDF conversion, compression, and page tools
Exec=@EXEC@ %F
TryExec=@EXEC@
Icon=pdfpad
Terminal=false
Categories=Office;
MimeType=application/pdf;
Keywords=PDF;convert;compress;merge;split;rotate;markdown;images;
StartupNotify=true
StartupWMClass=PDFPad
```

Design points:

- `%F` passes one or more selected files to the application.
- `TryExec` lets the desktop environment hide a broken launcher.
- A **single** main category (`Office;`) avoids duplicate menu entries; `desktop-file-validate` flags multiple main categories.
- `MimeType=application/pdf` plus the MIME definition below makes PDFPad a candidate PDF handler.
- `StartupWMClass` helps window managers associate the window with the launcher.

The template is rendered by both `install.sh` and `build_deb.sh`. After substitution, `desktop-file-validate` passes cleanly. (Validating the raw `.in` file reports only that its filename lacks a `.desktop` extension.)

### 8.2 MIME definition

`packaging/linux/pdfpad-mime.xml` registers `application/pdf` with a filename glob and a magic signature:

```xml
<mime-type type="application/pdf">
  <comment>PDF document</comment>
  <glob pattern="*.pdf" weight="50"/>
  <magic priority="50">
    <match value="%PDF-" type="string" offset="0"/>
  </magic>
</mime-type>
```

Including both glob and magic matching means a PDF is recognised even when its extension is missing or wrong. The file is well-formed XML and is installed under `share/mime/packages/`.

### 8.3 Icons

Icons are generated programmatically by `packaging/make_icons.py` using Pillow. This avoids committing a binary source file and guarantees every size is consistent with the SVG.

The design is a rounded blue gradient tile containing a white page with a folded corner, three text lines, and a red band labelled **PDF**. Colours are shared with `packaging/linux/pdfpad.svg`.

Generated outputs:

- `gui/resources/pdfpad.png` — 256×256, used as the Qt window icon.
- `packaging/linux/icons/hicolor/<size>/apps/pdfpad.png` — 16, 24, 32, 48, 64, 128, 256, and 512 px.

Each raster icon is drawn on a 4× supersampled canvas and downsampled with Lanczos, which keeps edges smooth at small sizes. The script accepts `--project-root` so tests can generate into a temporary tree.

---

## 9. Licensing and compliance

### 9.1 The application's own license

The PDFPad application code **does not currently declare a license**. Both `THIRD_PARTY_NOTICES.md` and the Debian `copyright` file state this explicitly and flag that a license should be chosen before public distribution. This is a deliberate, visible gap rather than an accidental omission: the third-party obligations are documented regardless of the project's own licensing decision.

### 9.2 Third-party components

`packaging/licenses/THIRD_PARTY_NOTICES.md` summarises every shipped runtime component:

| Component | Build-time version | License |
|---|---|---|
| Python | 3.12 | PSF-2.0 |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with special exception |
| pypdf | 6.21.1 | BSD-3-Clause |
| pypdfium2 | 5.15.0 | Apache-2.0 OR BSD-3-Clause |
| PDFium | bundled | BSD-3-Clause |
| Pillow | 13.0.0 | MIT-CMU |
| pikepdf | 9.11.0 | MPL-2.0 |
| QPDF | bundled | Apache-2.0 |
| pdfminer.six | 20260107 | MIT |
| PySide6-Essentials | 6.12.0 | LGPL-3.0 / GPL-2.0 / GPL-3.0 |
| shiboken6 | 6.12.0 | LGPL-3.0 / GPL-2.0 / GPL-3.0 |
| Qt 6 | 6.12.0 | LGPL-3.0 / GPL-2.0 / GPL-3.0 |

The notices also record the **build-time-only** components (PyInstaller, pytest, DejaVu Sans) and the optional LibreOffice add-on's own licensing.

### 9.3 License collection

`packaging/collect_licenses.py` runs during the build and produces `licenses/`:

1. **Installed distributions** — for each runtime package it copies license files from the installed wheel and writes a `METADATA.txt` summary. License detection considers both the filename and any parent directory, which matters for pypdfium2's nested `BUILD_LICENSES/` tree.
2. **Python** — copies the interpreter license from the standard library or system documentation.
3. **System texts** — copies LGPL-3.0, GPL-3.0, and Apache-2.0 from `/usr/share/common-licenses/` for components whose wheels omit license files (Qt/PySide6/shiboken6 and QPDF).
4. **Notices** — copies `THIRD_PARTY_NOTICES.md`.
5. **Manifest** — writes `MANIFEST.txt` recording what was found, what was copied, and any warnings.

The verified manifest reports `ok` for pypdf, pypdfium2, Pillow, pikepdf, pdfminer.six, PyInstaller, Python, Qt LGPL/GPL, and QPDF Apache-2.0. PySide6-Essentials and shiboken6 report `no files` because their wheels genuinely ship no license text; their licenses are covered by the system Qt texts and the notices. pypdfium2's bundle includes **36 license files**, covering PDFium's own dependencies (FreeType, HarfBuzz, ICU, libjpeg-turbo, libpng, libtiff, zlib, and others).

### 9.4 Why the Qt/QPDF system copies are acceptable

Qt's and QPDF's license texts are standard, unmodified license documents. Copying them from the build host's `/usr/share/common-licenses/` is equivalent to copying them from the projects' repositories. The script records the source path in the manifest for auditability. If the system copies are unavailable, the build records a warning rather than silently omitting them.

### 9.5 Compliance caveats

- **Qt LGPL relinking:** distributing LGPL Qt requires that recipients can relink against a modified Qt. Shipping the unmodified PySide6 wheels and documenting their origin is the normal approach; anyone modifying the bundled Qt must satisfy the relinking terms.
- **PyInstaller exception:** the bootloader is GPL-2.0-or-later with an exception that explicitly permits distributing bundled applications, including proprietary ones.
- **LibreOffice add-on:** if a LibreOffice tree is bundled, its own MPL-2.0/LGPL-3.0-or-later files must travel with it. PDFPad invokes it as a separate process and does not link against it.

---

## 10. Runtime self-test and frozen-resource handling

### 10.1 `--self-test`

`gui/app.py` exposes `run_self_test()`, invoked by `PDFPad --self-test`. It performs, in a temporary directory:

| Check | Library exercised |
|---|---|
| Create and count a PDF | `pypdf` |
| Render a page to an image | `pypdfium2` / PDFium |
| Extract text | `pdfminer.six` |
| Extract Markdown | `pdfminer.six` |
| Compress losslessly | `pikepdf` / QPDF |
| Build a PDF from an image | Pillow |
| Create and show a Qt window | PySide6 |
| Load the window icon | Qt resource bundling |

The Qt portion runs with `QT_QPA_PLATFORM=offscreen`, so it works on a headless build machine and in CI. It creates a `MainWindow` with a temporary `QSettings` file, shows it, processes events, and closes it — proving the GUI can be constructed inside the frozen bundle.

The self-test prints one `ok`/`FAILED` line per check and returns a non-zero exit code on failure. The build script treats a non-zero exit as fatal, so a release cannot be produced from a broken bundle.

### 10.2 Frozen resource root

A frozen PyInstaller app does not run from the source tree. `gui/app.py` handles both cases:

```python
def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return Path(bundled)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
```

In a onedir build, `_MEIPASS` points at `_internal/`, where `gui/resources/pdfpad.png` is bundled. Running from source uses the project root. A test monkeypatches `sys.frozen` and `sys._MEIPASS` to assert the frozen branch.

### 10.3 LibreOffice discovery in a frozen app

`core.office.find_libreoffice()` already supports an explicit path, the `PDFPAD_LIBREOFFICE` environment variable, a bundled `office/program/soffice`, and a system `soffice`/`libreoffice`. Phase 5 extends the bundled lookup so a frozen executable also checks next to itself:

- `PDFPad/office/program/soffice` (release layout), and
- `PDFPad/_internal/office/program/soffice` (alternative layout).

A test creates a fake executable in `PDFPad/office/program/soffice`, fakes a frozen `sys.executable`, and asserts the bundled location is selected with source `"bundled"`. Office conversion therefore remains opt-in and correctly detected after packaging.

---

## 11. Verification performed

Phase 5 was verified end-to-end, not just by unit tests.

| Verification | Command | Result |
|---|---|---|
| Source self-test | `.venv/bin/python -m gui --self-test` | All 8 checks `ok` |
| Version flag | `.venv/bin/python -m gui --version` | `PDFPad 0.5.0` |
| Real PyInstaller build | `./packaging/build_linux.sh` | Succeeded |
| Frozen self-test | `dist/PDFPad/PDFPad --self-test` | Passed |
| Tarball creation | `build_linux.sh` | ~88 MB tarball |
| Desktop validation | `desktop-file-validate` (rendered entry) | Exit 0 |
| MIME XML parse | `xml.etree.ElementTree` | Well-formed, one `application/pdf` type |
| License collection | `collect_licenses.py` | Manifest complete, 36 pypdfium2 files |
| Portable install | `install.sh --prefix /tmp/...` | Installed |
| Installed app | `/tmp/.../bin/pdfpad --self-test` | Passed |
| Portable uninstall | `install.sh --prefix /tmp/... --uninstall` | Removed app files |
| Debian build | `build_deb.sh dist/PDFPad-0.5.0-linux-x86_64` | Built |
| Debian metadata | `dpkg-deb --info` | Correct control fields |
| Debian extract + run | `dpkg-deb --extract` then `--self-test` | Passed |
| Native dependency check | `ldd` on executable, Qt core, xcb plugin | Resolved from bundle/system base |
| Full test suite | `pytest -q -p faulthandler tests` | 368 passed |

The build was repeated after two final fixes — the desktop category change and pypdfium2 license inclusion — so `dist/` matches the current source.

---

## 12. Testing and quality assurance

### 12.1 New packaging tests

`tests/test_packaging.py` adds **23 tests** that validate packaging inputs without running a full PyInstaller build (which is slow and belongs in the build script). Coverage:

- **Version consistency** — `pyproject.toml` version equals `APP_VERSION`.
- **Icons** — runtime icon exists and is 256×256; all desktop sizes exist with correct dimensions; the SVG is well-formed with the expected viewBox; the generator writes a complete tree into a temporary project root.
- **Desktop entry** — required keys, `@EXEC@` placeholder, `%F`, MIME association, single main category; renders and passes `desktop-file-validate` when available.
- **MIME XML** — correct namespace, exactly one `application/pdf` type, glob and magic match.
- **Shell scripts** — `bash -n` parses all three scripts; installer exposes the expected options and prefix layout; build script references icons, licenses, self-test, PyInstaller, tarball, and `.deb`; `.deb` script uses `--root-owner-group`, `/opt/pdfpad`, maintainer scripts, and documentation.
- **Spec** — onedir `COLLECT`, `exclude_binaries`, bundled resources, QML/Quick exclusions, and entry-point wiring.
- **Licenses** — notices cover every runtime component and the key licenses; the collector produces a manifest, notices, Qt/QPDF texts, and pypdfium2 license files.
- **Runtime** — `--version`, source self-test, frozen resource root, and frozen LibreOffice discovery.

These tests are fast (about 3 seconds) and run headlessly with the rest of the suite.

### 12.2 Full suite

```
368 passed in 8.43s
```

The suite grew from 345 to 368 tests. It remains stable across repeated runs and uses `faulthandler` to surface native crashes from PDFium/Qt during tests.

### 12.3 What is tested where

| Layer | Tested by |
|---|---|
| Core conversions | `tests/test_*.py` (pages, render, images, text, markdown, compress, office) |
| GUI workflow | `tests/test_gui.py` via `pytest-qt` offscreen |
| Packaging inputs | `tests/test_packaging.py` |
| Frozen application | Build-time `--self-test` (manual/build gate) |
| Install/deb artifacts | Manual verification (documented in §11) |

A full PyInstaller build is intentionally **not** part of the unit suite: it takes minutes and requires the build extra. The build script itself is the integration gate.

---

## 13. Design decisions and rationale

### 13.1 Build script as the single entry point

Rather than documenting a sequence of manual commands, `build_linux.sh` encodes the correct order and fails fast. This prevents the common packaging mistake of shipping a release built before the self-test or before licenses were collected.

### 13.2 Frozen self-test before release assembly

Running the self-test against the frozen executable catches missing native libraries, broken Qt plugins, and absent data files — problems that a source-mode test cannot detect. Gating release creation on it means a broken bundle never becomes a tarball.

### 13.3 Onedir over onefile

Discussed in §3.2. The decisive factors are startup time, predictable temp usage, and inspectability on locked-down machines.

### 13.4 Generated icons

Drawing icons with Pillow keeps the repository text-only and makes every size reproducible. The SVG is hand-written but uses the same palette, so the scalable and raster icons match.

### 13.5 Template-based desktop entry

The executable path differs between user, system, and `.deb` installs. A single `@EXEC@` template rendered at install time avoids hard-coding a path that would be wrong in some layout.

### 13.6 Conservative installer

The installer only removes paths it created, leaves user settings/logs alone, and treats cache-refresh failures as non-fatal. This makes install/uninstall safe to run repeatedly and safe on minimal systems.

### 13.7 `Recommends` for xcb helpers

The exact xcb helper set varies across distributions and display servers. Making them `Recommends` keeps the hard dependency list small while still pulling them in on normal desktop installs.

### 13.8 License collection from installed wheels

Reading metadata and files from the actual installed distributions guarantees the bundled license texts match the bundled versions, rather than relying on a hand-maintained list that can drift.

### 13.9 Keep LibreOffice optional

The default release excludes LibreOffice entirely. The build copies an add-on only when `office/program/soffice` exists. This preserves the small core download, avoids licensing a large third-party suite by default, and keeps the app fully functional without it.

---

## 14. Limitations and known issues

1. **Build-host glibc is newer than the target.** The build ran on glibc 2.39 while the product targets glibc ≥ 2.34. The bundled libraries are expected to be compatible, but this has not yet been proven on an Ubuntu 22.04 / Mint 21 machine. **Phase 6 must validate on the oldest supported distribution.**
2. **No AppImage yet.** The plan defers AppImage. The tarball and `.deb` cover the current distribution paths.
3. **No code signing or repository hosting.** The `.deb` is a local artifact; there is no APT repository, signing key, or notarization.
4. **The application license is undeclared.** This must be resolved before public distribution. Third-party obligations are documented independently.
5. **Qt/PySide6 license files are sourced from the build host.** If `/usr/share/common-licenses/` is unavailable, the collector records a warning and the release may lack Qt license texts. A future improvement is to vendor canonical texts in the repository.
6. **`desktop-file-validate` on the raw `.in` template fails** solely because of the filename extension; the rendered entry validates. This is expected.
7. **The `.deb` dependency list is conservative but not exhaustive.** Unusual display stacks may require additional xcb libraries; these are `Recommends`, so `apt` installs them on normal systems but `--no-install-recommends` users may need to add them.
8. **No automated install/deb test in the unit suite.** These are verified manually and documented in §11. Automating them would require a disposable container and is a candidate for Phase 6 or CI.
9. **Large release size.** ~220 MB unpacked is inherent to bundling Qt, PDFium, and QPDF. Excluding unused Qt modules already reduces it; further trimming risks breaking plugins.
10. **Broken-pipe warning from `dpkg-deb --contents | head`.** Cosmetic; not a package defect.

---

## 15. Roadmap: Phase 6

Phase 6 is **air-gap validation**. It should prove the packaged application works on a machine with no network and no development environment:

1. **Network isolation** — run the frozen app and every operation under `unshare -n` to confirm no network syscalls are required.
2. **Clean-machine test** — install the tarball and `.deb` on a minimal VM matching the glibc ≥ 2.34 target (Ubuntu 22.04 / Mint 21), with no Python, Qt, or LibreOffice installed.
3. **Feature sweep** — exercise page operations, PDF→images, images→PDF, compression (both modes), text/Markdown export, password-protected PDFs, and Office conversion with the optional add-on.
4. **Stress inputs** — large PDFs, many-page documents, encrypted files, unusual page sizes, and filenames with spaces/Unicode.
5. **Cleanup audit** — verify temporary files and LibreOffice profiles are removed after success, failure, and cancellation.
6. **Repeated-run behaviour** — confirm settings/log rotation and that repeated installs/uninstalls leave no residue.
7. **Report** — document the validation matrix and any platform-specific fixes.

---

## 16. Project file map

```
pdfpad/
├── core/                         # GUI-independent conversion library
│   ├── compress.py               # lossless (pikepdf) + rasterize compression
│   ├── errors.py                 # shared exception types
│   ├── images.py                 # images → PDF
│   ├── io.py                     # atomic output, validation
│   ├── markdown.py               # PDF → best-effort Markdown
│   ├── office.py                 # optional LibreOffice integration
│   ├── pages.py                  # extract/split/merge/rotate
│   ├── progress.py               # progress/cancel protocol
│   ├── ranges.py                 # page-range parser
│   ├── render.py                 # PDFium rendering/thumbnails
│   └── text.py                   # text extraction
├── gui/                          # PySide6 application
│   ├── app.py                    # logging, QApplication, main(), version, self-test
│   ├── main_window.py            # main window and workflow
│   ├── operations.py             # Qt-free request building
│   ├── options_panel.py          # per-operation options
│   ├── workers.py                # background execution
│   ├── widgets/                  # drop list, preview
│   └── resources/pdfpad.png      # generated window icon
├── office/                       # optional LibreOffice add-on (README only by default)
├── packaging/
│   ├── pdfpad.spec               # PyInstaller onedir spec
│   ├── entrypoint.py             # frozen entry point
│   ├── build_linux.sh            # build orchestration + tarball + self-test
│   ├── build_deb.sh              # Debian package builder
│   ├── make_icons.py             # programmatic icon generation
│   ├── collect_licenses.py       # license bundle generator
│   ├── licenses/
│   │   └── THIRD_PARTY_NOTICES.md
│   └── linux/
│       ├── install.sh            # portable installer/uninstaller
│       ├── pdfpad.desktop.in     # desktop entry template
│       ├── pdfpad-mime.xml       # application/pdf MIME definition
│       ├── pdfpad.svg            # scalable icon
│       └── icons/hicolor/...     # generated PNG icons
├── tests/
│   ├── conftest.py               # offscreen Qt + temp config/state
│   ├── pdf_fixtures.py           # generated PDF/image fixtures
│   ├── fake_office.py            # fake soffice for Office tests
│   ├── test_packaging.py         # 23 packaging tests
│   └── test_*.py                 # core + GUI tests
├── report/                       # phase reports
├── dist/                         # build output (git-ignored)
├── pyproject.toml                # version 0.5.0, build extra, package data
├── requirements.txt              # runtime pins
├── requirements-dev.txt          # test + PyInstaller pins
└── README.md
```

---

## Appendix A — Build and install quick reference

### Build

```bash
# One-time: install build/test dependencies
.venv/bin/pip install -r requirements-dev.txt

# Portable release (onedir + tarball)
./packaging/build_linux.sh

# Portable release + Debian package
./packaging/build_linux.sh --deb

# Release directory only, no tarball
./packaging/build_linux.sh --no-tarball
```

### Smoke test

```bash
PDFPad/PDFPad --version
QT_QPA_PLATFORM=offscreen PDFPad/PDFPad --self-test
```

### Install from tarball

```bash
tar -xzf dist/PDFPad-0.5.0-linux-x86_64.tar.gz
cd PDFPad-0.5.0-linux-x86_64

./install.sh                     # ~/.local
sudo ./install.sh --system       # /usr/local
./install.sh --prefix /opt/x     # custom prefix
./install.sh --set-default       # default PDF handler
./install.sh --uninstall         # remove
```

### Install the `.deb`

```bash
sudo apt install ./dist/pdfpad_0.5.0_amd64.deb
```

### Optional LibreOffice add-on

```text
PDFPad/office/program/soffice
```

or set `PDFPAD_LIBREOFFICE=/path/to/soffice`. Office → PDF stays disabled otherwise.

---

## Appendix B — Release contents

```
PDFPad-0.5.0-linux-x86_64/
├── PDFPad/
│   ├── PDFPad                    # executable
│   ├── _internal/                # Python, Qt, PDFium, QPDF, Pillow, pdfminer
│   └── office/                   # only when an add-on was bundled
├── install.sh                    # executable
├── pdfpad.desktop.in
├── pdfpad-mime.xml
├── pdfpad.svg
├── icons/hicolor/
│   ├── 16x16/apps/pdfpad.png
│   ├── 24x24/apps/pdfpad.png
│   ├── 32x32/apps/pdfpad.png
│   ├── 48x48/apps/pdfpad.png
│   ├── 64x64/apps/pdfpad.png
│   ├── 128x128/apps/pdfpad.png
│   ├── 256x256/apps/pdfpad.png
│   └── 512x512/apps/pdfpad.png
├── licenses/
│   ├── MANIFEST.txt
│   ├── THIRD_PARTY_NOTICES.md
│   ├── pypdf-6.21.1/
│   ├── pypdfium2-5.15.0/         # includes BUILD_LICENSES (36 files)
│   ├── pillow-13.0.0/
│   ├── pikepdf-9.11.0/
│   ├── pdfminer-six-20260107/
│   ├── pyside6-essentials-6.12.0/
│   ├── shiboken6-6.12.0/
│   ├── pyinstaller-6.22.3/
│   ├── python-3.12/
│   ├── qt-lgpl-3.0/
│   ├── qt-gpl-3.0/
│   └── qpdf-apache-2.0/
├── README.md
└── VERSION
```

---

## Appendix C — Test inventory

### Packaging tests (`tests/test_packaging.py`, 23)

| Area | Tests |
|---|---|
| Version | pyproject/APP_VERSION consistency |
| Icons | runtime icon, all desktop sizes, SVG well-formedness, generator into temp tree |
| Desktop entry | required keys, validation after substitution |
| MIME | namespace, single `application/pdf`, glob, magic |
| Scripts | `bash -n` for all three; installer options/layout; build references; `.deb` structure |
| Spec | onedir, exclusions, bundled data, entry point |
| Licenses | notices coverage; collector manifest and texts |
| Runtime | `--version`, source self-test, frozen resource root, frozen LibreOffice discovery |

### Whole suite by area

| Area | File(s) |
|---|---|
| Page ranges | `test_ranges.py` |
| Page operations | `test_pages.py` |
| Rendering | `test_render.py` |
| Images → PDF | `test_images.py` |
| Text extraction | `test_text.py` |
| Markdown | `test_markdown.py` |
| Compression | `test_compress.py` |
| Office conversion | `test_office.py` |
| Atomic I/O | `test_io.py` |
| Progress/cancel | `test_progress.py` |
| Request building | `test_operations.py` |
| Background workers | `test_workers.py` |
| GUI workflow | `test_gui.py` |
| Packaging | `test_packaging.py` |

**Total: 368 passing tests.**
