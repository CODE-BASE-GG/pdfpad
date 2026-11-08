"""Text extraction from PDF pages."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .io import write_text
from .pages import open_pdf
from .progress import CancelCallback, ProgressCallback, check_cancel, report
from .ranges import validate_indices


def extract_text_per_page(
    input_path: str | Path,
    indices: Iterable[int] | None = None,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> list[str]:
    """Return the extracted text of each selected page, in selection order.

    When *indices* is ``None`` every page is included. Pages with no text
    produce an empty string.
    """
    reader = open_pdf(input_path, password)
    total = len(reader.pages)
    selected = (
        list(range(total)) if indices is None else validate_indices(indices, total)
    )
    pages: list[str] = []
    for position, index in enumerate(selected, start=1):
        check_cancel(cancel)
        pages.append((reader.pages[index].extract_text() or "").strip())
        report(progress, position, len(selected))
    return pages


def extract_text(
    input_path: str | Path,
    indices: Iterable[int] | None = None,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> str:
    """Return selected pages as one string, with a blank line between pages."""
    return "\n\n".join(
        extract_text_per_page(
            input_path,
            indices=indices,
            password=password,
            progress=progress,
            cancel=cancel,
        )
    )


def extract_text_to_file(
    input_path: str | Path,
    output_path: str | Path,
    indices: Iterable[int] | None = None,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> Path:
    """Extract text and write it to *output_path* as UTF-8, atomically."""
    text = extract_text(
        input_path,
        indices=indices,
        password=password,
        progress=progress,
        cancel=cancel,
    )
    return write_text(output_path, text)
