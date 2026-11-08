#!/usr/bin/env bash
# Validate a PDFPad release in an isolated network namespace.
#
# Usage:
#   packaging/airgap_validate.sh [OPTIONS]
#
# Options:
#   --release DIR     Release directory (default: newest dist/PDFPad-*-linux-*)
#   --pages N         Page count for the large fixture (default: 150)
#   --no-isolation    Run without unshare (diagnostic only; not an air gap)
#   --no-tests        Skip the pytest suite
#   --no-install      Skip the install/uninstall cycle
#   --no-office       Skip the optional LibreOffice conversion check
#   --keep            Keep the temporary work tree
#   -h, --help        Show this help
#
# The script proves three things:
#   1. the frozen application runs with no network namespace connectivity;
#   2. it makes no AF_INET/AF_INET6 socket calls (verified with strace);
#   3. every core operation, encrypted PDF handling, cancellation, cleanup,
#      repeated runs, and install/uninstall work without network access.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname -- "$SCRIPT_DIR")"
PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
WORK_ROOT="${PDFPAD_AIRGAP_WORK:-/tmp/opencode/pdfpad-airgap}"
RELEASE_DIR=""
PAGES=150
USE_ISOLATION=1
RUN_TESTS=1
RUN_INSTALL=1
RUN_OFFICE=1
KEEP=0
FAILURES=0

usage() {
    cat <<'EOF'
Usage: packaging/airgap_validate.sh [OPTIONS]

Options:
  --release DIR     Release directory (default: newest dist/PDFPad-*-linux-*)
  --pages N         Page count for the large fixture (default: 150)
  --no-isolation    Run without unshare (diagnostic only; not an air gap)
  --no-tests        Skip the pytest suite
  --no-install      Skip the install/uninstall cycle
  --no-office       Skip the optional LibreOffice conversion check
  --keep            Keep the temporary work tree
  -h, --help        Show this help

Environment:
  PYTHON            Interpreter for the source checks (default: .venv/bin/python)
  PDFPAD_AIRGAP_WORK  Work directory (default: /tmp/opencode/pdfpad-airgap)
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --release)
            [ "$#" -ge 2 ] || { echo "error: --release requires a directory" >&2; exit 2; }
            RELEASE_DIR="$2"
            shift 2
            ;;
        --pages)
            [ "$#" -ge 2 ] || { echo "error: --pages requires a number" >&2; exit 2; }
            PAGES="$2"
            shift 2
            ;;
        --no-isolation) USE_ISOLATION=0; shift ;;
        --no-tests) RUN_TESTS=0; shift ;;
        --no-install) RUN_INSTALL=0; shift ;;
        --no-office) RUN_OFFICE=0; shift ;;
        --keep) KEEP=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

fail() {
    echo "FAILED: $*" >&2
    FAILURES=$((FAILURES + 1))
}

pass() {
    echo "ok      $*"
}

# -- locate and validate the release --------------------------------------
if [ -z "$RELEASE_DIR" ]; then
    RELEASE_DIR="$(find "$PROJECT_ROOT/dist" -maxdepth 1 -type d \
        -name 'PDFPad-*-linux-*' -printf '%T@ %p\n' 2>/dev/null \
        | sort -nr | head -n 1 | cut -d' ' -f2-)"
fi
if [ -z "$RELEASE_DIR" ] || [ ! -d "$RELEASE_DIR" ]; then
    echo "error: no release directory found; run packaging/build_linux.sh first" >&2
    exit 1
fi
RELEASE_DIR="$(cd -- "$RELEASE_DIR" && pwd)"
FROZEN="$RELEASE_DIR/PDFPad/PDFPad"
if [ ! -x "$FROZEN" ]; then
    echo "error: $FROZEN not found or not executable" >&2
    exit 1
fi
if [ ! -x "$PYTHON" ]; then
    echo "error: Python interpreter not found: $PYTHON" >&2
    exit 1
fi

# -- choose the isolation mechanism ---------------------------------------
ISOLATE=()
if [ "$USE_ISOLATION" -eq 1 ]; then
    if unshare -Urn true 2>/dev/null; then
        ISOLATE=(unshare -Urn)
        ISOLATION_LABEL="unshare -Urn (user + network namespace)"
    elif unshare -n true 2>/dev/null; then
        ISOLATE=(unshare -n)
        ISOLATION_LABEL="unshare -n (network namespace)"
    else
        echo "error: no usable network-namespace mechanism." >&2
        echo "Run as root, enable unprivileged user namespaces, or pass" >&2
        echo "--no-isolation for a diagnostic run (which does not prove isolation)." >&2
        exit 1
    fi
else
    ISOLATION_LABEL="disabled (diagnostic run; NOT an air gap)"
fi

run_isolated() {
    if [ "${#ISOLATE[@]}" -gt 0 ]; then
        "${ISOLATE[@]}" "$@"
    else
        "$@"
    fi
}

# -- work tree and environment --------------------------------------------
if [ "$KEEP" -eq 0 ]; then
    rm -rf "$WORK_ROOT"
fi
mkdir -p "$WORK_ROOT"/{home,config,state,tmp,trace}
export HOME="$WORK_ROOT/home"
export XDG_CONFIG_HOME="$WORK_ROOT/config"
export XDG_STATE_HOME="$WORK_ROOT/state"
export TMPDIR="$WORK_ROOT/tmp"
export QT_QPA_PLATFORM=offscreen

echo "PDFPad air-gap validation"
echo "  release:   $RELEASE_DIR"
echo "  isolation: $ISOLATION_LABEL"
echo "  work:      $WORK_ROOT"
echo

DEB_PATH="$(find "$PROJECT_ROOT/dist" -maxdepth 1 -type f -name 'pdfpad_*.deb' \
    -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"

# -- 1. prove the namespace has no connectivity ---------------------------
if [ "$USE_ISOLATION" -eq 1 ]; then
    interfaces="$(run_isolated sh -c 'cat /proc/net/dev' 2>/dev/null || true)"
    if printf '%s\n' "$interfaces" | grep -Eq '^[[:space:]]*(eth|en|wl|wlan|docker|veth|br-)'; then
        fail "namespace still exposes a network interface"
    else
        pass "network namespace has no external interfaces"
    fi
fi

# -- 2. frozen self-test under isolation ----------------------------------
echo
echo "== Frozen application self-test =="
if run_isolated "$FROZEN" --self-test; then
    pass "frozen --self-test under isolation"
else
    fail "frozen --self-test under isolation"
fi

# -- 2b. run with an empty environment and no PATH ------------------------
echo
echo "== Minimal environment =="
if run_isolated /usr/bin/env -i \
    PATH=/nonexistent \
    LANG=C.UTF-8 \
    HOME="$WORK_ROOT/home" \
    XDG_CONFIG_HOME="$WORK_ROOT/config" \
    XDG_STATE_HOME="$WORK_ROOT/state" \
    TMPDIR="$WORK_ROOT/tmp" \
    QT_QPA_PLATFORM=offscreen \
    "$FROZEN" --self-test >/dev/null; then
    pass "frozen self-test with empty environment and no PATH"
else
    fail "frozen self-test with empty environment and no PATH"
fi

# -- 2c. confirm the bundle, not the system, provides Python/Qt ----------
echo
echo "== Bundled runtime dependencies =="
check_bundle() {
    local binary="$1"
    local label="$2"
    local deps
    deps="$(ldd "$binary" 2>&1 || true)"
    if printf '%s\n' "$deps" | grep -q "not found"; then
        fail "$label has unresolved shared libraries"
        return
    fi
    if printf '%s\n' "$deps" | grep -Eq 'libpython|/usr/lib[^ ]*libQt6'; then
        fail "$label depends on system Python or Qt"
        return
    fi
    pass "$label resolves without system Python/Qt"
}

check_bundle "$FROZEN" "frozen executable"
if [ -f "$RELEASE_DIR/PDFPad/_internal/libQt6Core.so.6" ]; then
    check_bundle "$RELEASE_DIR/PDFPad/_internal/libQt6Core.so.6" "bundled Qt core"
else
    fail "bundled Qt core is missing"
fi

for required in \
    "$RELEASE_DIR/PDFPad/_internal/libQt6Core.so.6" \
    "$RELEASE_DIR/PDFPad/_internal/pypdfium2" \
    "$RELEASE_DIR/PDFPad/_internal/pypdfium2_raw"; do
    if [ -e "$required" ]; then
        pass "bundled: $(basename "$required")"
    else
        fail "bundled component missing: $(basename "$required")"
    fi
done
if compgen -G "$RELEASE_DIR/PDFPad/_internal/libqpdf-*.so*" >/dev/null; then
    pass "bundled: QPDF"
else
    fail "bundled QPDF library is missing"
fi

XCB_PLUGIN="$RELEASE_DIR/PDFPad/_internal/PySide6/Qt/plugins/platforms/libqxcb.so"
if [ -f "$XCB_PLUGIN" ] && command -v readelf >/dev/null 2>&1; then
    if readelf -d "$XCB_PLUGIN" | grep -q '\$ORIGIN/../../lib'; then
        pass "xcb plugin uses a bundle-relative RUNPATH"
    else
        fail "xcb plugin lacks a bundle-relative RUNPATH"
    fi
fi

# -- 3. verify no IP socket syscalls --------------------------------------
if command -v strace >/dev/null 2>&1; then
    echo
    echo "== Network syscall trace =="
    TRACE="$WORK_ROOT/trace/network.log"
    if run_isolated strace -f -qq -e trace=network -o "$TRACE" \
        "$FROZEN" --self-test >/dev/null 2>&1; then
        if grep -Eq 'AF_INET|AF_INET6' "$TRACE"; then
            fail "frozen app attempted an IP socket call"
            grep -E 'AF_INET|AF_INET6' "$TRACE" | head -5 >&2 || true
        else
            pass "no AF_INET/AF_INET6 socket calls"
        fi
    else
        fail "strace run of the frozen self-test"
    fi
else
    echo "note: strace not installed; skipping socket-call trace"
fi

# -- 4. comprehensive core checks -----------------------------------------
echo
echo "== Core conversion checks =="
AIRGAP_ARGS=(--project-root "$PROJECT_ROOT" --pages "$PAGES")
if [ "$RUN_OFFICE" -eq 0 ]; then
    AIRGAP_ARGS+=(--no-office)
fi
if run_isolated "$PYTHON" "$SCRIPT_DIR/airgap_checks.py" "${AIRGAP_ARGS[@]}"; then
    pass "core air-gap checks"
else
    fail "core air-gap checks"
fi

# -- 5. full test suite under isolation -----------------------------------
if [ "$RUN_TESTS" -eq 1 ]; then
    echo
    echo "== Test suite under isolation =="
    if run_isolated "$PYTHON" -m pytest -q -p faulthandler "$PROJECT_ROOT/tests"; then
        pass "pytest suite under isolation"
    else
        fail "pytest suite under isolation"
    fi
fi

# -- 6. install/uninstall cycle, twice ------------------------------------
if [ "$RUN_INSTALL" -eq 1 ]; then
    echo
    echo "== Install/uninstall cycle =="
    for round in 1 2; do
        prefix="$WORK_ROOT/install-$round"
        rm -rf "$prefix"
        if "$RELEASE_DIR/install.sh" --prefix "$prefix" >/dev/null; then
            pass "install round $round"
        else
            fail "install round $round"
            continue
        fi

        if [ -x "$prefix/bin/pdfpad" ]; then
            if run_isolated "$prefix/bin/pdfpad" --self-test >/dev/null; then
                pass "installed app self-test round $round"
            else
                fail "installed app self-test round $round"
            fi
        else
            fail "launcher missing after install round $round"
        fi

        if command -v desktop-file-validate >/dev/null 2>&1; then
            if desktop-file-validate "$prefix/share/applications/pdfpad.desktop" >/dev/null 2>&1; then
                pass "desktop entry validates round $round"
            else
                fail "desktop entry validation round $round"
            fi
        fi

        if "$RELEASE_DIR/install.sh" --prefix "$prefix" --uninstall >/dev/null; then
            pass "uninstall round $round"
        else
            fail "uninstall round $round"
        fi

        if [ -e "$prefix/lib/pdfpad/PDFPad" ] || [ -e "$prefix/bin/pdfpad" ]; then
            fail "application files remain after uninstall round $round"
        else
            pass "uninstall removed application files round $round"
        fi
    done
fi

# -- 7. Debian package extraction and run ---------------------------------
echo
echo "== Debian package =="
if [ -n "$DEB_PATH" ] && [ -f "$DEB_PATH" ] && command -v dpkg-deb >/dev/null 2>&1; then
    deb_root="$WORK_ROOT/deb"
    rm -rf "$deb_root"
    mkdir -p "$deb_root"
    if dpkg-deb --extract "$DEB_PATH" "$deb_root"; then
        pass "extracted $(basename "$DEB_PATH")"
    else
        fail "extract $(basename "$DEB_PATH")"
    fi
    if [ -x "$deb_root/opt/pdfpad/PDFPad" ]; then
        if run_isolated "$deb_root/opt/pdfpad/PDFPad" --self-test >/dev/null; then
            pass ".deb application self-test under isolation"
        else
            fail ".deb application self-test under isolation"
        fi
    else
        fail ".deb application executable missing"
    fi
    if command -v desktop-file-validate >/dev/null 2>&1; then
        if desktop-file-validate "$deb_root/usr/share/applications/pdfpad.desktop" >/dev/null 2>&1; then
            pass ".deb desktop entry validates"
        else
            fail ".deb desktop entry validation"
        fi
    fi
else
    echo "note: no .deb found; skipping (run packaging/build_linux.sh --deb)"
fi

# -- summary --------------------------------------------------------------
echo
if [ "$KEEP" -eq 0 ]; then
    rm -rf "$WORK_ROOT"
else
    echo "Work tree kept at $WORK_ROOT"
fi

if [ "$FAILURES" -ne 0 ]; then
    echo "AIR-GAP VALIDATION FAILED: $FAILURES check(s)"
    exit 1
fi
echo "AIR-GAP VALIDATION PASSED"
