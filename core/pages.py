"""PDF page operations: read, extract, split, merge and rotate."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from .errors import EncryptedPdfError, OperationCancelled, PdfOperationError
from .io import atomic_output, require_file
from .progress import CancelCallback, ProgressCallback, check_cancel, report
from .ranges import validate_indices


def open_pdf(path: str | Path, password: str | None = None) -> PdfReader:
    """Open a PDF, decrypting it when a password is supplied.

    Raises:
        UnsupportedFileError: The path does not point to a file.
        EncryptedPdfError: The PDF is encrypted and the password is missing or
            incorrect.
        PdfOperationError: The file is not a readable PDF.
    """
    source = require_file(path)
    try:
        reader = PdfReader(str(source))
    except (PdfReadError, OSError) as exc:
        raise PdfOperationError(f"Could not read PDF {source.name}: {exc}") from exc

    if reader.is_encrypted:
        if password is None:
            raise EncryptedPdfError(f"{source.name} is password-protected.")
        if reader.decrypt(password) == PasswordType.NOT_DECRYPTED:
            raise EncryptedPdfError(f"Incorrect password for {source.name}.")
    return reader


def page_count(path: str | Path, password: str | None = None) -> int:
    """Return the number of pages in *path*."""
    return len(open_pdf(path, password).pages)


def _write_writer(writer: PdfWriter, output_path: str | Path) -> None:
    with atomic_output(output_path) as tmp:
        with tmp.open("wb") as handle:
            writer.write(handle)


def extract_pages(
    input_path: str | Path,
    indices: Iterable[int],
    output_path: str | Path,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> Path:
    """Copy the selected 0-based page *indices* into a new PDF."""
    reader = open_pdf(input_path, password)
    total = len(reader.pages)
    selected = validate_indices(indices, total)

    writer = PdfWriter()
    for position, index in enumerate(selected, start=1):
        check_cancel(cancel)
        writer.add_page(reader.pages[index])
        report(progress, position, len(selected))
    _write_writer(writer, output_path)
    return Path(output_path)


def split_pdf(
    input_path: str | Path,
    output_dir: str | Path,
    chunk_size: int = 1,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> list[Path]:
    """Split a PDF into chunks of *chunk_size* pages.

    Files are named ``<stem>_pages_<first>-<last>.pdf`` in *output_dir*.
    With the default ``chunk_size=1`` each page becomes its own PDF.
    """
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise TypeError("chunk_size must be an int")
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    reader = open_pdf(input_path, password)
    total = len(reader.pages)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    stem = Path(input_path).stem
    width = len(str(total))
    starts = list(range(0, total, chunk_size))
    outputs: list[Path] = []
    created: list[Path] = []
    try:
        for position, start in enumerate(starts, start=1):
            check_cancel(cancel)
            end = min(start + chunk_size, total)
            writer = PdfWriter()
            for index in range(start, end):
                writer.add_page(reader.pages[index])

            name = f"{stem}_pages_{start + 1:0{width}d}-{end:0{width}d}.pdf"
            target = destination / name
            if not target.exists():
                created.append(target)
            _write_writer(writer, target)
            outputs.append(target)
            report(progress, position, len(starts))
    except OperationCancelled:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return outputs


def merge_pdfs(
    input_paths: Sequence[str | Path],
    output_path: str | Path,
    passwords: Sequence[str | None] | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> Path:
    """Append the pages of every input PDF, in order, into one PDF.

    ``passwords``, when given, must be the same length as ``input_paths`` and
    supplies the password for each file.
    """
    paths = [Path(path) for path in input_paths]
    if not paths:
        raise PdfOperationError("No input files to merge.")
    if passwords is not None and len(passwords) != len(paths):
        raise ValueError("passwords must match the number of input files")

    resolved_passwords = list(passwords) if passwords is not None else [None] * len(paths)
    writer = PdfWriter()
    for position, (path, password) in enumerate(
        zip(paths, resolved_passwords, strict=True), start=1
    ):
        check_cancel(cancel)
        reader = open_pdf(path, password)
        for page in reader.pages:
            writer.add_page(page)
        report(progress, position, len(paths))

    _write_writer(writer, output_path)
    return Path(output_path)


def rotate_pages(
    input_path: str | Path,
    output_path: str | Path,
    degrees: int,
    indices: Iterable[int] | None = None,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> Path:
    """Rotate selected pages clockwise by *degrees* (a multiple of 90).

    When *indices* is ``None`` every page is rotated. Rotation is cumulative
    with any rotation already stored on the page.
    """
    if isinstance(degrees, bool) or not isinstance(degrees, int):
        raise TypeError("degrees must be an int")
    if degrees % 90 != 0:
        raise ValueError("degrees must be a multiple of 90")

    reader = open_pdf(input_path, password)
    total = len(reader.pages)
    selected = (
        set(range(total)) if indices is None else set(validate_indices(indices, total))
    )

    writer = PdfWriter()
    for position, index in enumerate(range(total), start=1):
        check_cancel(cancel)
        page = writer.add_page(reader.pages[index])
        if index in selected:
            page.rotate(degrees)
        report(progress, position, total)

    _write_writer(writer, output_path)
    return Path(output_path)
