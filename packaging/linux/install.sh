#!/usr/bin/env bash
# Install or remove the portable PDFPad build.
#
# Run from the extracted release directory:
#   ./install.sh                  # install for the current user (~/.local)
#   sudo ./install.sh --system    # install system-wide (/usr/local)
#   ./install.sh --prefix DIR     # install under DIR
#   ./install.sh --uninstall      # remove the user installation
#   ./install.sh --set-default    # make PDFPad the default PDF handler
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="pdfpad"
DISPLAY_NAME="PDFPad"
DEFAULT_PREFIX="${HOME}/.local"
PREFIX="${PREFIX:-$DEFAULT_PREFIX}"
UNINSTALL=0
SET_DEFAULT=0
SYSTEM=0

usage() {
    cat <<'EOF'
Usage: ./install.sh [OPTIONS]

Options:
  --prefix DIR    Install under DIR (default: ~/.local)
  --system        Install system-wide under /usr/local (requires root)
  --uninstall     Remove the installation described by --prefix
  --set-default   Register PDFPad as the default handler for application/pdf
  -h, --help      Show this help

The optional LibreOffice add-on is used automatically when an
office/program/soffice tree is present next to the PDFPad executable.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            if [ "$#" -lt 2 ]; then
                echo "error: --prefix requires a directory" >&2
                exit 2
            fi
            PREFIX="$2"
            shift 2
            ;;
        --system)
            SYSTEM=1
            PREFIX="/usr/local"
            shift
            ;;
        --uninstall)
            UNINSTALL=1
            shift
            ;;
        --set-default)
            SET_DEFAULT=1
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

# Expand a leading ~ in a user-supplied prefix.
case "$PREFIX" in
    "~") PREFIX="$HOME" ;;
    "~/"*) PREFIX="$HOME/${PREFIX#\~/}" ;;
esac

APP_DIR="$PREFIX/lib/$APP_NAME"
BIN_DIR="$PREFIX/bin"
DESKTOP_DIR="$PREFIX/share/applications"
ICON_ROOT="$PREFIX/share/icons/hicolor"
MIME_DIR="$PREFIX/share/mime/packages"

if [ "$SYSTEM" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
    echo "error: --system requires root; re-run with sudo" >&2
    exit 1
fi

refresh_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    fi
    if command -v update-mime-database >/dev/null 2>&1; then
        update-mime-database "$PREFIX/share/mime" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -d "$ICON_ROOT" ]; then
        gtk-update-icon-cache -q -t -f "$ICON_ROOT" >/dev/null 2>&1 || true
    fi
}

if [ "$UNINSTALL" -eq 1 ]; then
    rm -rf "$APP_DIR"
    rm -f "$BIN_DIR/$APP_NAME"
    rm -f "$DESKTOP_DIR/$APP_NAME.desktop"
    rm -f "$MIME_DIR/$APP_NAME-mime.xml"
    rm -f "$ICON_ROOT/scalable/apps/$APP_NAME.svg"
    if [ -d "$ICON_ROOT" ]; then
        find "$ICON_ROOT" -path "*/apps/$APP_NAME.png" -delete 2>/dev/null || true
    fi
    refresh_caches
    echo "Removed $DISPLAY_NAME from $PREFIX"
    echo "User settings and logs were left untouched."
    exit 0
fi

if [ ! -x "$SCRIPT_DIR/PDFPad/PDFPad" ]; then
    echo "error: $SCRIPT_DIR/PDFPad/PDFPad not found" >&2
    echo "Run this script from an extracted PDFPad release directory." >&2
    exit 1
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_ROOT" "$MIME_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -a "$SCRIPT_DIR/PDFPad/." "$APP_DIR/"
ln -sfn "$APP_DIR/PDFPad" "$BIN_DIR/$APP_NAME"

# Install the scalable icon and every generated PNG size.
if [ -f "$SCRIPT_DIR/pdfpad.svg" ]; then
    install -Dm644 "$SCRIPT_DIR/pdfpad.svg" \
        "$ICON_ROOT/scalable/apps/$APP_NAME.svg"
fi
shopt -s nullglob
for icon in "$SCRIPT_DIR"/icons/hicolor/*/apps/$APP_NAME.png; do
    size="$(basename "$(dirname "$(dirname "$icon")")")"
    install -Dm644 "$icon" "$ICON_ROOT/$size/apps/$APP_NAME.png"
done
shopt -u nullglob

# Generate the desktop entry with an absolute executable path. This works for
# both user and system installs without relying on the session PATH.
exec_path="$APP_DIR/PDFPad"
escaped_exec="${exec_path//&/\\&}"
sed "s|@EXEC@|$escaped_exec|g" "$SCRIPT_DIR/pdfpad.desktop.in" \
    > "$DESKTOP_DIR/$APP_NAME.desktop"
chmod 644 "$DESKTOP_DIR/$APP_NAME.desktop"

if [ -f "$SCRIPT_DIR/pdfpad-mime.xml" ]; then
    install -Dm644 "$SCRIPT_DIR/pdfpad-mime.xml" \
        "$MIME_DIR/$APP_NAME-mime.xml"
fi

refresh_caches

if [ "$SET_DEFAULT" -eq 1 ]; then
    if command -v xdg-mime >/dev/null 2>&1; then
        xdg-mime default "$APP_NAME.desktop" application/pdf
        echo "Registered $DISPLAY_NAME as the default PDF handler."
    else
        echo "warning: xdg-mime not found; default handler not changed" >&2
    fi
fi

echo "Installed $DISPLAY_NAME under $PREFIX"
echo "  application: $APP_DIR/PDFPad"
echo "  launcher:    $BIN_DIR/$APP_NAME"
if [ "$PREFIX" = "$HOME/.local" ]; then
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) echo "note: $BIN_DIR is not on PATH; add it or launch from the application menu." ;;
    esac
fi
