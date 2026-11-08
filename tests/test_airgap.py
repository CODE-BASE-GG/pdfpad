"""Tests for the Phase 6 air-gap validation tooling.

The real air-gap run (network namespace, frozen release, install cycle) is
executed by ``packaging/airgap_validate.sh``. These tests keep the harness
honest and fast: they check the script contracts and run the core checks with a
small fixture and without the optional LibreOffice backend.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from gui.app import run_self_test

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = PROJECT_ROOT / "packaging"
VALIDATE_SCRIPT = PACKAGING / "airgap_validate.sh"
CHECKS_SCRIPT = PACKAGING / "airgap_checks.py"


def test_airgap_scripts_are_executable():
    assert VALIDATE_SCRIPT.is_file()
    assert CHECKS_SCRIPT.is_file()
    assert VALIDATE_SCRIPT.stat().st_mode & 0o111
    assert CHECKS_SCRIPT.stat().st_mode & 0o111


def test_validate_script_parses():
    subprocess.run(["bash", "-n", str(VALIDATE_SCRIPT)], check=True)


def test_validate_script_covers_the_air_gap_contract():
    text = VALIDATE_SCRIPT.read_text(encoding="utf-8")
    for token in (
        "unshare -Urn",
        "unshare -n",
        "AF_INET",
        "AF_INET6",
        "strace",
        "PATH=/nonexistent",
        "pypdfium2",
        "libqpdf",
        "$ORIGIN/../../lib",
        "install.sh",
        "--uninstall",
        "dpkg-deb",
        "AIR-GAP VALIDATION PASSED",
    ):
        assert token in text, token


def test_checks_script_supports_help():
    result = subprocess.run(
        [sys.executable, str(CHECKS_SCRIPT), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--pages" in result.stdout
    assert "--no-office" in result.stdout


def test_core_airgap_checks_pass_on_a_small_fixture(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(CHECKS_SCRIPT),
            "--project-root",
            str(PROJECT_ROOT),
            "--workdir",
            str(tmp_path / "work"),
            "--pages",
            "12",
            "--no-office",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All " in result.stdout
    assert "air-gap checks passed" in result.stdout
    assert "FAILED" not in result.stdout


def test_self_test_covers_every_feature_area(capsys):
    assert run_self_test() == 0
    output = capsys.readouterr().out
    for check in (
        "page range parser",
        "extract pages",
        "split pages",
        "merge PDFs",
        "rotate pages",
        "pypdfium2 render",
        "pdfminer text",
        "pdfminer markdown",
        "pikepdf lossless",
        "pikepdf rasterize",
        "Pillow images to PDF",
        "encrypted read with password",
        "encrypted rejects missing password",
        "Qt window",
    ):
        assert check in output, check
