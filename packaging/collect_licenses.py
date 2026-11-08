#!/usr/bin/env python3
"""Collect license texts for everything shipped in a PDFPad release.

The script reads the installed distributions in the build environment, copies
their license files into the release, and adds license texts for components
whose wheels do not carry one (Qt/PySide6, QPDF, Python, the PyInstaller
bootloader). It never downloads anything.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import sysconfig
from datetime import date
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "build" / "licenses"

# Distributions that are part of the frozen application (or its bootloader).
PACKAGES = (
    "pypdf",
    "pypdfium2",
    "Pillow",
    "pikepdf",
    "pdfminer.six",
    "PySide6-Essentials",
    "shiboken6",
    "pyinstaller",
)

# Extra license texts copied from the build machine. These components are
# bundled inside the wheels or the executable but do not ship a license file in
# the wheel itself.
SYSTEM_LICENSES = (
    ("qt-lgpl-3.0", "/usr/share/common-licenses/LGPL-3", "LGPL-3.0.txt"),
    ("qt-gpl-3.0", "/usr/share/common-licenses/GPL-3", "GPL-3.0.txt"),
    ("qpdf-apache-2.0", "/usr/share/common-licenses/Apache-2.0", "Apache-2.0.txt"),
)

_LICENSE_MARKERS = ("LICENSE", "COPYING", "NOTICE", "COPYRIGHT", "AUTHORS")


def _normalise_name(name: str) -> str:
    return name.replace("_", "-").replace(".", "-").lower()


def _license_files(files) -> list[Path]:
    selected: list[Path] = []
    for item in files or ():
        path = Path(str(item))
        # Include a file when its name *or any parent directory* marks it as a
        # license file. pypdfium2, for example, ships files such as
        # ``licenses/BUILD_LICENSES/freetype.txt``.
        if any(
            marker in part.upper()
            for part in path.parts
            for marker in _LICENSE_MARKERS
        ):
            selected.append(path)
    return selected


def _relative_license_path(path: Path) -> Path:
    parts = path.parts
    if "licenses" in parts:
        return Path(*parts[parts.index("licenses") + 1 :])
    return Path(path.name)


def _copy_distribution(name: str, output: Path, manifest: list[str]) -> None:
    try:
        dist = distribution(name)
    except PackageNotFoundError:
        manifest.append(f"MISSING  {name} is not installed in this environment")
        return

    package_dir = output / f"{_normalise_name(dist.metadata['Name'])}-{dist.version}"
    package_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for path in _license_files(dist.files):
        relative = _relative_license_path(path)
        target = package_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dist.locate_file(path), target)
        copied.append(str(relative))

    metadata = dist.metadata
    licence = (metadata.get("License-Expression") or metadata.get("License") or "").strip()
    summary = [
        f"Name: {metadata['Name']}",
        f"Version: {dist.version}",
        f"License: {licence or 'see license files'}",
        f"Home-page: {metadata.get('Home-page') or metadata.get('Project-URL') or ''}",
        f"License files: {', '.join(copied) if copied else 'none in wheel'}",
    ]
    (package_dir / "METADATA.txt").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )
    status = "ok" if copied else "no files"
    manifest.append(
        f"{status:8} {metadata['Name']} {dist.version}"
        f" ({licence or 'unknown license'})"
    )


def _copy_python_license(output: Path, manifest: list[str]) -> None:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidates = (
        Path(sysconfig.get_path("stdlib")).parent / "LICENSE.txt",
        Path(f"/usr/lib/python{version}/LICENSE.txt"),
        Path("/usr/share/doc/python3/copyright"),
    )
    target_dir = output / f"python-{version}"
    target_dir.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        if candidate.is_file():
            shutil.copyfile(candidate, target_dir / "LICENSE.txt")
            manifest.append(f"ok       Python {version} ({candidate})")
            return
    manifest.append(f"WARNING  Python {version} license file not found")


def _copy_system_licenses(output: Path, manifest: list[str]) -> None:
    for folder, source, filename in SYSTEM_LICENSES:
        path = Path(source)
        target_dir = output / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            shutil.copyfile(path, target_dir / filename)
            manifest.append(f"ok       {folder} ({source})")
        else:
            manifest.append(f"WARNING  {folder} license not found at {source}")


def collect(output: Path = DEFAULT_OUTPUT, project_root: Path = PROJECT_ROOT) -> Path:
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    manifest: list[str] = [
        "PDFPad third-party license manifest",
        f"Generated: {date.today().isoformat()}",
        "",
        "Installed distributions:",
    ]
    for name in PACKAGES:
        _copy_distribution(name, output, manifest)

    manifest.extend(["", "Additional license texts:"])
    _copy_python_license(output, manifest)
    _copy_system_licenses(output, manifest)

    notices = project_root / "packaging" / "licenses" / "THIRD_PARTY_NOTICES.md"
    if notices.is_file():
        shutil.copyfile(notices, output / "THIRD_PARTY_NOTICES.md")
        manifest.extend(["", "See THIRD_PARTY_NOTICES.md for the component summary."])

    project_license = project_root / "LICENSE"
    if project_license.is_file():
        shutil.copyfile(project_license, output / "PDFPad-LICENSE.txt")
        manifest.extend(
            [
                "",
                "PDFPad application license: GPL-3.0-or-later "
                "(see PDFPad-LICENSE.txt).",
            ]
        )
    else:
        manifest.extend(["", "WARNING  PDFPad LICENSE file not found"])

    (output / "MANIFEST.txt").write_text(
        "\n".join(manifest) + "\n", encoding="utf-8"
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"destination directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="PDFPad source tree",
    )
    args = parser.parse_args(argv)

    output = collect(args.output, args.project_root.resolve())
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
