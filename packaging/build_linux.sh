#!/usr/bin/env bash
# Build a portable PDFPad release with PyInstaller.
#
# Usage:
#   packaging/build_linux.sh              # onedir + tarball
#   packaging/build_linux.sh --deb        # also build a .deb
#   packaging/build_linux.sh --no-tarball # skip the tarball
#
# The build is self-contained: it never downloads anything. Install the build
# dependencies first with:
#   .venv/bin/pip install -r requirements-dev.txt
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname -- "$SCRIPT_DIR")"
PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

BUILD_DEB=0
MAKE_TARBALL=1

usage() {
    cat <<'EOF'
Usage: packaging/build_linux.sh [OPTIONS]

Options:
  --deb          Also build a Debian package with packaging/build_deb.sh
  --no-tarball   Do not create the portable .tar.gz
  -h, --help     Show this help

Environment:
  PYTHON         Python interpreter to use (default: .venv/bin/python)
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --deb)
            BUILD_DEB=1
            shift
            ;;
        --no-tarball)
            MAKE_TARBALL=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ ! -x "$PYTHON" ]; then
    echo "error: Python interpreter not found: $PYTHON" >&2
    exit 1
fi
if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "error: PyInstaller is not installed for $PYTHON" >&2
    echo "Install it with: $PYTHON -m pip install -r requirements-dev.txt" >&2
    exit 1
fi

VERSION="$("$PYTHON" - "$PROJECT_ROOT/pyproject.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle)["project"]["version"])
PY
)"
ARCH="$(uname -m)"
RELEASE_NAME="PDFPad-${VERSION}-linux-${ARCH}"
DIST_DIR="$PROJECT_ROOT/dist"
BUILD_DIR="$PROJECT_ROOT/build"
WORK_DIR="$BUILD_DIR/pyinstaller"
RELEASE_DIR="$DIST_DIR/$RELEASE_NAME"

echo "Building PDFPad $VERSION for linux-$ARCH"
echo "  python:  $PYTHON"
echo "  release: $RELEASE_DIR"

# Refresh the generated icons so the build always matches make_icons.py.
"$PYTHON" "$SCRIPT_DIR/make_icons.py" >/dev/null

rm -rf "$WORK_DIR" "$DIST_DIR/PDFPad" "$RELEASE_DIR"
mkdir -p "$DIST_DIR"

"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    "$SCRIPT_DIR/pdfpad.spec"

# Prove that the frozen application can load its native dependencies and build
# the Qt window without a display server.
echo "Running frozen self-test..."
QT_QPA_PLATFORM=offscreen "$DIST_DIR/PDFPad/PDFPad" --self-test

mkdir -p "$RELEASE_DIR"
cp -a "$DIST_DIR/PDFPad" "$RELEASE_DIR/PDFPad"

cp "$SCRIPT_DIR/linux/install.sh" "$RELEASE_DIR/install.sh"
chmod +x "$RELEASE_DIR/install.sh"
cp "$SCRIPT_DIR/linux/pdfpad.desktop.in" "$RELEASE_DIR/pdfpad.desktop.in"
cp "$SCRIPT_DIR/linux/pdfpad-mime.xml" "$RELEASE_DIR/pdfpad-mime.xml"
cp "$SCRIPT_DIR/linux/pdfpad.svg" "$RELEASE_DIR/pdfpad.svg"
cp -a "$SCRIPT_DIR/linux/icons" "$RELEASE_DIR/icons"
cp "$PROJECT_ROOT/README.md" "$RELEASE_DIR/README.md"
cp "$PROJECT_ROOT/LICENSE" "$RELEASE_DIR/LICENSE"

# Optional LibreOffice add-on: copy it next to the executable only when a real
# soffice tree is present. The application still works without it.
if [ -x "$PROJECT_ROOT/office/program/soffice" ]; then
    rm -rf "$RELEASE_DIR/PDFPad/office"
    cp -a "$PROJECT_ROOT/office" "$RELEASE_DIR/PDFPad/office"
    echo "Bundled LibreOffice add-on from office/"
else
    echo "No LibreOffice add-on found (optional); Office conversion will be disabled."
fi

"$PYTHON" "$SCRIPT_DIR/collect_licenses.py" \
    --output "$RELEASE_DIR/licenses" \
    --project-root "$PROJECT_ROOT" >/dev/null

{
    echo "name=PDFPad"
    echo "version=$VERSION"
    echo "arch=$ARCH"
    echo "built=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "python=$("$PYTHON" -c 'import platform; print(platform.python_version())')"
    echo "glibc=$("$PYTHON" -c 'import platform; print(platform.libc_ver()[1])')"
} > "$RELEASE_DIR/VERSION"

if [ "$MAKE_TARBALL" -eq 1 ]; then
    echo "Creating tarball..."
    tar -C "$DIST_DIR" -czf "$DIST_DIR/$RELEASE_NAME.tar.gz" "$RELEASE_NAME"
fi

if [ "$BUILD_DEB" -eq 1 ]; then
    "$SCRIPT_DIR/build_deb.sh" "$RELEASE_DIR"
fi

echo
echo "Done."
echo "  application: $RELEASE_DIR/PDFPad/PDFPad"
if [ "$MAKE_TARBALL" -eq 1 ]; then
    echo "  tarball:     $DIST_DIR/$RELEASE_NAME.tar.gz"
fi
if [ "$BUILD_DEB" -eq 1 ]; then
    echo "  package:     $DIST_DIR/pdfpad_${VERSION}_$(dpkg --print-architecture).deb"
fi
