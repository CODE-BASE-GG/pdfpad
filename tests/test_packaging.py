"""Tests for the packaging artifacts and build/install scripts.

These tests do not run a full PyInstaller build. They validate the static
packaging inputs, the generated icons, the desktop/MIME metadata, the license
collection, and the source-mode self-test. A real build is exercised manually
and by ``packaging/build_linux.sh`` (which runs the frozen self-test).
"""

from __future__ import annotations

import configparser
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from core.office import find_libreoffice
from gui.app import APP_VERSION, _resource_root, main, run_self_test

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = PROJECT_ROOT / "packaging"
LINUX = PACKAGING / "linux"
DESKTOP_TEMPLATE = LINUX / "pdfpad.desktop.in"
MIME_XML = LINUX / "pdfpad-mime.xml"
INSTALL_SCRIPT = LINUX / "install.sh"
BUILD_SCRIPT = PACKAGING / "build_linux.sh"
DEB_SCRIPT = PACKAGING / "build_deb.sh"
SPEC = PACKAGING / "pdfpad.spec"
NOTICES = PACKAGING / "licenses" / "THIRD_PARTY_NOTICES.md"

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
MIME_NS = "{http://www.freedesktop.org/standards/shared-mime-info}"


# -- versions and source layout -------------------------------------------


def test_version_matches_pyproject():
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["version"] == APP_VERSION


def test_runtime_icon_is_generated():
    icon = PROJECT_ROOT / "gui" / "resources" / "pdfpad.png"
    assert icon.is_file()
    with Image.open(icon) as image:
        assert image.format == "PNG"
        assert image.size == (256, 256)


def test_desktop_icons_cover_all_sizes():
    for size in ICON_SIZES:
        path = (
            LINUX / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "pdfpad.png"
        )
        assert path.is_file(), path
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == (size, size)


def test_scalable_icon_is_well_formed_svg():
    root = ET.parse(LINUX / "pdfpad.svg").getroot()
    assert root.tag.endswith("svg")
    assert root.attrib["viewBox"] == "0 0 256 256"


def test_icon_generator_writes_into_a_fresh_tree(tmp_path):
    result = subprocess.run(
        [sys.executable, str(PACKAGING / "make_icons.py"), "--project-root", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "gui/resources/pdfpad.png" in result.stdout
    assert (tmp_path / "gui" / "resources" / "pdfpad.png").is_file()
    for size in ICON_SIZES:
        assert (
            tmp_path
            / "packaging"
            / "linux"
            / "icons"
            / "hicolor"
            / f"{size}x{size}"
            / "apps"
            / "pdfpad.png"
        ).is_file()


# -- desktop entry and MIME type ------------------------------------------


def _desktop_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(DESKTOP_TEMPLATE.read_text(encoding="utf-8"))
    return parser


def test_desktop_entry_has_required_keys():
    entry = _desktop_parser()["Desktop Entry"]
    assert entry["Type"] == "Application"
    assert entry["Name"] == "PDFPad"
    assert entry["Exec"].startswith("@EXEC@")
    assert entry["Exec"].endswith("%F")
    assert entry["TryExec"] == "@EXEC@"
    assert entry["Icon"] == "pdfpad"
    assert entry["Terminal"] == "false"
    assert "application/pdf" in entry["MimeType"].split(";")
    assert entry["Categories"].count(";") == 1


def test_desktop_entry_validates_after_substitution(tmp_path):
    validator = shutil.which("desktop-file-validate")
    if validator is None:
        pytest.skip("desktop-file-validate is not installed")

    rendered = tmp_path / "pdfpad.desktop"
    rendered.write_text(
        DESKTOP_TEMPLATE.read_text(encoding="utf-8").replace(
            "@EXEC@", "/opt/pdfpad/PDFPad"
        ),
        encoding="utf-8",
    )
    subprocess.run([validator, str(rendered)], check=True)


def test_mime_xml_registers_pdf_documents():
    root = ET.parse(MIME_XML).getroot()
    assert root.tag == f"{MIME_NS}mime-info"

    mime_types = root.findall(f"{MIME_NS}mime-type")
    assert len(mime_types) == 1
    pdf = mime_types[0]
    assert pdf.attrib["type"] == "application/pdf"
    assert any(
        glob.attrib["pattern"] == "*.pdf"
        for glob in pdf.findall(f"{MIME_NS}glob")
    )
    magic = pdf.find(f"{MIME_NS}magic")
    assert magic is not None
    assert magic.find(f"{MIME_NS}match").attrib["value"] == "%PDF-"


# -- install and build scripts --------------------------------------------


@pytest.mark.parametrize(
    "script", [INSTALL_SCRIPT, BUILD_SCRIPT, DEB_SCRIPT], ids=lambda p: p.name
)
def test_shell_scripts_parse(script):
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_install_script_supports_user_system_and_uninstall():
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    for option in ("--prefix", "--system", "--uninstall", "--set-default"):
        assert option in text
    assert "s|@EXEC@|$escaped_exec|g" in text
    assert "refresh_caches" in text
    assert "update-desktop-database" in text
    assert "update-mime-database" in text
    assert "gtk-update-icon-cache" in text
    assert "scalable/apps/$APP_NAME.svg" in text


def test_install_script_uses_a_prefix_layout():
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert 'APP_DIR="$PREFIX/lib/$APP_NAME"' in text
    assert 'BIN_DIR="$PREFIX/bin"' in text
    assert 'DESKTOP_DIR="$PREFIX/share/applications"' in text
    assert 'ICON_ROOT="$PREFIX/share/icons/hicolor"' in text
    assert 'MIME_DIR="$PREFIX/share/mime/packages"' in text


def test_build_script_runs_icons_licenses_and_frozen_self_test():
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "make_icons.py" in text
    assert "collect_licenses.py" in text
    assert "--self-test" in text
    assert "PyInstaller" in text
    assert "pdfpad.spec" in text
    assert "tar -C" in text
    assert "build_deb.sh" in text


def test_deb_script_builds_a_root_owned_package():
    text = DEB_SCRIPT.read_text(encoding="utf-8")
    assert "dpkg-deb" in text
    assert "--root-owner-group" in text
    assert "/opt/pdfpad" in text
    assert "DEBIAN/control" in text
    assert "DEBIAN/postinst" in text
    assert "usr/share/doc/pdfpad" in text
    assert "copyright" in text


def test_pyinstaller_spec_is_onedir_and_excludes_qml():
    text = SPEC.read_text(encoding="utf-8")
    assert "entrypoint.py" in text
    assert 'name="PDFPad"' in text
    assert "COLLECT(" in text
    assert "exclude_binaries=True" in text
    assert "gui/resources" in text
    assert "PySide6.QtQml" in text
    assert "PySide6.QtQuick" in text


def test_entrypoint_calls_gui_main():
    text = (PACKAGING / "entrypoint.py").read_text(encoding="utf-8")
    assert "from gui.app import main" in text
    assert "raise SystemExit(main())" in text


# -- licenses --------------------------------------------------------------


def test_notices_cover_runtime_components():
    text = NOTICES.read_text(encoding="utf-8")
    for component in (
        "Python",
        "PyInstaller",
        "pypdf",
        "pypdfium2",
        "PDFium",
        "Pillow",
        "pikepdf",
        "QPDF",
        "pdfminer.six",
        "PySide6-Essentials",
        "shiboken6",
        "Qt 6",
    ):
        assert component in text
    assert "LGPL-3.0" in text
    assert "MPL-2.0" in text
    assert "Apache-2.0" in text


def test_project_declares_gpl_3_0_or_later():
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3" in license_text
    assert "Rainiel Dejito" in license_text
    assert "GPL-3.0-or-later" in license_text

    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["license"] == "GPL-3.0-or-later"
    assert "LICENSE" in project["project"]["license-files"]
    assert project["project"]["authors"] == [{"name": "Rainiel Dejito"}]

    notices = NOTICES.read_text(encoding="utf-8")
    assert "GPL-3.0-or-later" in notices
    assert "Rainiel Dejito" in notices
    assert "does **not** currently declare" not in notices

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "GPL-3.0-or-later" in readme
    assert "does not currently declare a license" not in readme

    deb = DEB_SCRIPT.read_text(encoding="utf-8")
    assert "License: GPL-3.0-or-later" in deb
    assert "Copyright: 2026 Rainiel Dejito" in deb
    assert "all-rights-reserved" not in deb


def test_collect_licenses_produces_a_manifest_and_texts(tmp_path):
    output = tmp_path / "licenses"
    subprocess.run(
        [
            sys.executable,
            str(PACKAGING / "collect_licenses.py"),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = (output / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "pypdf" in manifest
    assert "pypdfium2" in manifest
    assert "pdfminer.six" in manifest
    assert "PySide6_Essentials" in manifest
    assert "Python 3." in manifest
    assert "GPL-3.0-or-later" in manifest
    assert (output / "PDFPad-LICENSE.txt").is_file()
    assert "qt-lgpl-3.0" in manifest
    assert "qpdf-apache-2.0" in manifest

    assert (output / "THIRD_PARTY_NOTICES.md").is_file()
    assert (output / "qt-lgpl-3.0" / "LGPL-3.0.txt").is_file()
    assert (output / "qpdf-apache-2.0" / "Apache-2.0.txt").is_file()
    pypdfium2 = output / "pypdfium2-5.15.0"
    if pypdfium2.is_dir():
        assert list(pypdfium2.rglob("*.txt"))


# -- runtime behaviour -----------------------------------------------------


def test_version_flag_prints_the_version(capsys):
    assert main(["--version"]) == 0
    assert APP_VERSION in capsys.readouterr().out


def test_source_self_test_passes(capsys):
    assert run_self_test() == 0
    assert "self-test passed" in capsys.readouterr().out


def test_resource_root_uses_pyinstaller_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert _resource_root() == tmp_path


def test_frozen_app_finds_office_next_to_executable(monkeypatch, tmp_path):
    monkeypatch.delenv("PDFPAD_LIBREOFFICE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    executable = tmp_path / "PDFPad"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(executable))

    soffice = tmp_path / "office" / "program" / "soffice"
    soffice.parent.mkdir(parents=True)
    soffice.write_text("#!/bin/sh\n", encoding="utf-8")
    soffice.chmod(0o755)

    assert find_libreoffice() == (soffice, "bundled")
