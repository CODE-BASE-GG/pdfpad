"""Optional LibreOffice integration for Office document conversion.

PDFPad itself never requires LibreOffice. Office conversion is enabled when a
bundled add-on pack is present, when ``PDFPAD_LIBREOFFICE`` points at an
executable, or when a system LibreOffice is available. The converter runs
headless with a private ``UserInstallation`` profile and copies each input into
a temporary working directory first, so it never leaves lock files next to the
user's documents.

The expected add-on layout is::

    office/
      program/soffice
      share/...
      LICENSE...

Extract an official LibreOffice tarball so that ``program/soffice`` exists
under the project's ``office/`` directory. See ``office/README.md``.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    OfficeUnavailableError,
    OperationCancelled,
    PdfOperationError,
    UnsupportedFileError,
)
from .io import require_file
from .progress import CancelCallback, ProgressCallback, check_cancel, report

OFFICE_SUFFIXES = frozenset(
    {
        ".doc",
        ".docm",
        ".docx",
        ".dot",
        ".dotx",
        ".odt",
        ".ott",
        ".rtf",
        ".xls",
        ".xlsm",
        ".xlsx",
        ".ods",
        ".ots",
        ".ppt",
        ".pptm",
        ".pptx",
        ".odp",
        ".otp",
    }
)

_ENV_VAR = "PDFPAD_LIBREOFFICE"
_BUNDLE_SUBDIR = "office"
_CANDIDATE_NAMES = ("program/soffice", "program/soffice.bin", "soffice")
_POLL_INTERVAL = 0.1
_TERMINATE_TIMEOUT = 5.0


@dataclass(frozen=True)
class OfficeInfo:
    """Capability information for the optional LibreOffice add-on."""

    available: bool
    binary: Path | None
    source: str | None
    version: str | None


def _bundle_dirs() -> list[Path]:
    dirs = [Path(__file__).resolve().parent.parent / _BUNDLE_SUBDIR]
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent / _BUNDLE_SUBDIR)
    return dirs


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def find_libreoffice(
    binary: str | Path | None = None,
    bundle_dir: str | Path | None = None,
) -> tuple[Path, str] | None:
    """Locate a LibreOffice executable.

    Search order: an explicit *binary*, the ``PDFPAD_LIBREOFFICE`` environment
    variable, the bundled add-on directory, then ``soffice``/``libreoffice`` on
    ``PATH``.

    Returns:
        ``(path, source)`` where source is ``"explicit"``, ``"environment"``,
        ``"bundled"``, or ``"system"``; or ``None`` when nothing is found.

    Raises:
        OfficeUnavailableError: An explicitly requested binary or the
            environment variable points at a missing/non-executable file.
    """
    if binary is not None:
        path = Path(binary)
        if _is_executable(path):
            return path, "explicit"
        raise OfficeUnavailableError(f"LibreOffice executable not found: {path}")

    configured = os.environ.get(_ENV_VAR)
    if configured:
        path = Path(configured)
        if _is_executable(path):
            return path, "environment"
        raise OfficeUnavailableError(
            f"{_ENV_VAR} points to a missing or non-executable file: {path}"
        )

    directories = [Path(bundle_dir)] if bundle_dir is not None else _bundle_dirs()
    for directory in directories:
        for name in _CANDIDATE_NAMES:
            candidate = directory / name
            if _is_executable(candidate):
                return candidate, "bundled"

    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return Path(found), "system"
    return None


def office_available() -> bool:
    """Return whether an Office conversion backend can be found."""
    try:
        return find_libreoffice() is not None
    except OfficeUnavailableError:
        return False


def _read_version(binary: Path, timeout: float = 10.0) -> str | None:
    try:
        completed = subprocess.run(
            [str(binary), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (completed.stdout or completed.stderr or "").strip()
    return text.splitlines()[0] if text else None


def office_info(
    binary: str | Path | None = None,
    bundle_dir: str | Path | None = None,
) -> OfficeInfo:
    """Return availability, path, source, and version of the converter."""
    try:
        found = find_libreoffice(binary=binary, bundle_dir=bundle_dir)
    except OfficeUnavailableError:
        return OfficeInfo(False, None, None, None)
    if found is None:
        return OfficeInfo(False, None, None, None)
    path, source = found
    return OfficeInfo(True, path, source, _read_version(path))


def _terminate(process: subprocess.Popen) -> None:
    """Terminate a converter process group, escalating to SIGKILL."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            process.terminate()
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=_TERMINATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()


def _run_converter(
    binary: Path,
    staged_input: Path,
    output_dir: Path,
    profile_uri: str,
    timeout: float,
    cancel: CancelCallback | None,
) -> tuple[int, str, str]:
    """Run one headless conversion and return (exit code, stdout, stderr)."""
    command = [
        str(binary),
        "--headless",
        "--norestore",
        "--nodefault",
        "--nolockcheck",
        "--nologo",
        "--invisible",
        f"-env:UserInstallation={profile_uri}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(staged_input),
    ]

    with (
        tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", errors="replace"
        ) as stdout_file,
        tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", errors="replace"
        ) as stderr_file,
    ):
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
            )
        except OSError as exc:
            raise OfficeUnavailableError(
                f"Could not start LibreOffice: {exc}"
            ) from exc

        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    process.wait(timeout=_POLL_INTERVAL)
                    break
                except subprocess.TimeoutExpired:
                    check_cancel(cancel)
                    if time.monotonic() >= deadline:
                        _terminate(process)
                        raise PdfOperationError(
                            "LibreOffice timed out after "
                            f"{timeout:g} seconds converting {staged_input.name}."
                        )
        finally:
            if process.poll() is None:
                _terminate(process)

        stdout_file.seek(0)
        stderr_file.seek(0)
        return process.returncode, stdout_file.read(), stderr_file.read()


def _unique_target(destination: Path, stem: str, planned: set[str]) -> Path:
    name = f"{stem}.pdf"
    counter = 2
    while name.casefold() in planned:
        name = f"{stem}-{counter}.pdf"
        counter += 1
    planned.add(name.casefold())
    return destination / name


def office_to_pdf(
    input_paths: list[str | Path],
    output_dir: str | Path,
    binary: str | Path | None = None,
    bundle_dir: str | Path | None = None,
    timeout: float = 120.0,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> list[Path]:
    """Convert Office documents to PDFs in *output_dir*.

    Args:
        input_paths: Documents to convert, in output order.
        output_dir: Destination folder; created when missing.
        binary: Optional explicit LibreOffice executable.
        bundle_dir: Optional directory to search for the bundled add-on.
        timeout: Maximum seconds allowed per document.

    Returns:
        The converted PDF paths, in input order.

    Raises:
        OfficeUnavailableError: No LibreOffice backend can be found.
        UnsupportedFileError: An input is missing or not a supported document.
        PdfOperationError: LibreOffice failed, timed out, or produced no PDF.
        OperationCancelled: The caller cancelled the operation.
    """
    if timeout <= 0:
        raise ValueError("timeout must be > 0")

    sources: list[Path] = []
    for path in input_paths:
        source = require_file(path)
        if source.suffix.lower() not in OFFICE_SUFFIXES:
            raise UnsupportedFileError(
                f"Unsupported Office document: {source.name}"
            )
        sources.append(source)
    if not sources:
        raise PdfOperationError("No Office documents provided.")

    found = find_libreoffice(binary=binary, bundle_dir=bundle_dir)
    if found is None:
        raise OfficeUnavailableError(
            "The optional LibreOffice add-on is not installed. "
            "Install the add-on pack or set PDFPAD_LIBREOFFICE."
        )
    executable, _source = found

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    planned: set[str] = set()
    targets = [
        _unique_target(destination, source.stem, planned) for source in sources
    ]

    created: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(
            prefix="pdfpad-office-profile-"
        ) as profile:
            profile_uri = Path(profile).as_uri()
            for position, (source, target) in enumerate(
                zip(sources, targets, strict=True), start=1
            ):
                check_cancel(cancel)

                # Convert inside a hidden temporary directory in the
                # destination so the final move is an atomic same-filesystem
                # rename and the input folder is never written to.
                with tempfile.TemporaryDirectory(
                    prefix=".pdfpad-office-", dir=destination
                ) as work:
                    work_dir = Path(work)
                    input_dir = work_dir / "in"
                    converted_dir = work_dir / "out"
                    input_dir.mkdir()
                    converted_dir.mkdir()
                    staged = input_dir / source.name
                    try:
                        shutil.copy2(source, staged)
                    except OSError as exc:
                        raise PdfOperationError(
                            f"Could not read {source.name}: {exc}"
                        ) from exc

                    code, stdout, stderr = _run_converter(
                        executable,
                        staged,
                        converted_dir,
                        profile_uri,
                        timeout,
                        cancel,
                    )
                    details = (stderr or stdout).strip()
                    if code != 0:
                        suffix = f" {details}" if details else ""
                        raise PdfOperationError(
                            "LibreOffice could not convert "
                            f"{source.name} (exit code {code}).{suffix}"
                        )

                    produced = converted_dir / f"{staged.stem}.pdf"
                    if not produced.is_file():
                        candidates = sorted(converted_dir.glob("*.pdf"))
                        if len(candidates) == 1:
                            produced = candidates[0]
                        elif not candidates:
                            suffix = f" {details}" if details else ""
                            raise PdfOperationError(
                                f"LibreOffice produced no PDF for {source.name}."
                                f"{suffix}"
                            )
                        else:
                            raise PdfOperationError(
                                "LibreOffice produced several PDFs for "
                                f"{source.name}."
                            )

                    if not target.exists():
                        created.append(target)
                    try:
                        os.replace(produced, target)
                    except OSError as exc:
                        raise PdfOperationError(
                            f"Could not save {target.name}: {exc}"
                        ) from exc

                report(progress, position, len(sources))
    except OperationCancelled:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return targets
