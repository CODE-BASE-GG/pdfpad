#!/usr/bin/env bash
# Build a Debian package from a release directory produced by build_linux.sh.
#
# Usage:
#   packaging/build_deb.sh dist/PDFPad-0.5.0-linux-x86_64
#
# The package installs the application under /opt/pdfpad and adds a launcher,
# desktop entry, icons, MIME definition, and the collected license texts.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname -- "$SCRIPT_DIR")"
PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

if [ "$#" -ne 1 ]; then
    echo "usage: packaging/build_deb.sh <release-directory>" >&2
    exit 2
fi

RELEASE_DIR="$(cd -- "$1" && pwd)"
if [ ! -x "$RELEASE_DIR/PDFPad/PDFPad" ]; then
    echo "error: $RELEASE_DIR/PDFPad/PDFPad not found" >&2
    exit 1
fi
if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "error: dpkg-deb is required to build a .deb" >&2
    exit 1
fi

VERSION="$(sed -n 's/^version=//p' "$RELEASE_DIR/VERSION" | head -n 1)"
if [ -z "$VERSION" ]; then
    echo "error: could not read the version from $RELEASE_DIR/VERSION" >&2
    exit 1
fi
DEB_ARCH="${DEB_ARCH:-$(dpkg --print-architecture)}"
PKG_ROOT="$PROJECT_ROOT/build/deb/pdfpad_${VERSION}_${DEB_ARCH}"

rm -rf "$PKG_ROOT"
install -d \
    "$PKG_ROOT/DEBIAN" \
    "$PKG_ROOT/opt/pdfpad" \
    "$PKG_ROOT/usr/bin" \
    "$PKG_ROOT/usr/share/applications" \
    "$PKG_ROOT/usr/share/icons/hicolor" \
    "$PKG_ROOT/usr/share/mime/packages" \
    "$PKG_ROOT/usr/share/doc/pdfpad"

cp -a "$RELEASE_DIR/PDFPad/." "$PKG_ROOT/opt/pdfpad/"
ln -s /opt/pdfpad/PDFPad "$PKG_ROOT/usr/bin/pdfpad"

sed "s|@EXEC@|/opt/pdfpad/PDFPad|g" "$RELEASE_DIR/pdfpad.desktop.in" \
    > "$PKG_ROOT/usr/share/applications/pdfpad.desktop"
chmod 644 "$PKG_ROOT/usr/share/applications/pdfpad.desktop"

if [ -d "$RELEASE_DIR/icons/hicolor" ]; then
    cp -a "$RELEASE_DIR/icons/hicolor/." "$PKG_ROOT/usr/share/icons/hicolor/"
fi
install -Dm644 "$RELEASE_DIR/pdfpad.svg" \
    "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps/pdfpad.svg"
install -Dm644 "$RELEASE_DIR/pdfpad-mime.xml" \
    "$PKG_ROOT/usr/share/mime/packages/pdfpad-mime.xml"

cp -a "$RELEASE_DIR/licenses/." "$PKG_ROOT/usr/share/doc/pdfpad/"
cp "$RELEASE_DIR/README.md" "$PKG_ROOT/usr/share/doc/pdfpad/README.md"
cp "$RELEASE_DIR/LICENSE" "$PKG_ROOT/usr/share/doc/pdfpad/LICENSE"

cat > "$PKG_ROOT/usr/share/doc/pdfpad/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: PDFPad
Source: local build

Files: *
Copyright: 2026 Rainiel Dejito
License: GPL-3.0-or-later
 This program is free software: you can redistribute it and/or modify it
 under the terms of the GNU General Public License as published by the Free
 Software Foundation, either version 3 of the License, or (at your option)
 any later version.
 .
 This program is distributed in the hope that it will be useful, but
 WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
 Public License for more details.
 .
 On Debian systems the complete GPL-3 text is available at
 /usr/share/common-licenses/GPL-3. A copy is also installed as
 /usr/share/doc/pdfpad/LICENSE.
 .
 The bundled third-party components retain their own licenses. See
 THIRD_PARTY_NOTICES.md and the collected license texts in this directory.
EOF

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: pdfpad
Version: $VERSION
Architecture: $DEB_ARCH
Installed-Size: $(du -sk "$PKG_ROOT" | cut -f1)
Maintainer: PDFPad Maintainers <maintainers@pdfpad.invalid>
Section: utils
Priority: optional
Depends: libc6 (>= 2.34), libx11-6, libxcb1, libxkbcommon0, libglib2.0-0, libfontconfig1, libfreetype6, libdbus-1-3, libgl1
Recommends: libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-sync1, libxcb-xfixes0, libxkbcommon-x11-0, libegl1, libopengl0
Description: offline PDF conversion desktop application
 PDFPad converts, compresses, and manipulates PDF files without network
 access. It bundles its own PDF engine and supports an optional LibreOffice
 add-on pack for Office document conversion.
EOF

cat > "$PKG_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database /usr/share/mime || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF

cat > "$PKG_ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database /usr/share/mime || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF

chmod 755 "$PKG_ROOT/DEBIAN/postinst" "$PKG_ROOT/DEBIAN/postrm"

DEB_PATH="$PROJECT_ROOT/dist/pdfpad_${VERSION}_${DEB_ARCH}.deb"
rm -f "$DEB_PATH"
mkdir -p "$PROJECT_ROOT/dist"
dpkg-deb --build --root-owner-group "$PKG_ROOT" "$DEB_PATH"

echo "Built $DEB_PATH"
dpkg-deb --info "$DEB_PATH"
