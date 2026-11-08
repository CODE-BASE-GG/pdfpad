"""Render PDF pages to raster images using bundled PDFium (no poppler needed)."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader

from .errors import (
    EncryptedPdfError,
    OperationCancelled,
    PdfOperationError,
    RangeSpecError,
)
from .io import atomic_output, require_file
from .progress import CancelCallback, ProgressCallback, check_cancel, report
from .ranges import validate_indices

# PDFium is not safe to use concurrently from several threads. The GUI can
# render a preview while an operation is running, so every PDFium call is
# serialised through this process-wide lock. It is re-entrant to keep nested
# helpers safe.
_PDFIUM_LOCK = threading.RLock()


def _is_encrypted(path: Path) -> bool:
    try:
        return PdfReader(str(path)).is_encrypted
    except Exception:
        return False


def _open_document(path: str | Path, password: str | None = None) -> pdfium.PdfDocument:
    source = require_file(path)
    try:
        return pdfium.PdfDocument(str(source), password=password)
    except pdfium.PdfiumError as exc:
        if _is_encrypted(source):
            if password is None:
                raise EncryptedPdfError(f"{source.name} is password-protected.") from exc
            raise EncryptedPdfError(f"Incorrect password for {source.name}.") from exc
        raise PdfOperationError(
            f"Could not read PDF {source.name}: {exc}"
        ) from exc


def _render_page(page: pdfium.PdfPage, dpi: int) -> Image.Image:
    if dpi <= 0:
        raise ValueError("dpi must be > 0")
    bitmap = page.render(scale=dpi / 72)
    try:
        # to_pil() shares memory with the bitmap buffer, so copy before closing.
        return bitmap.to_pil().copy()
    finally:
        bitmap.close()


def _render_thumbnail(page: pdfium.PdfPage, max_size: int) -> Image.Image:
    width, height = page.get_size()
    if width <= 0 or height <= 0:
        raise PdfOperationError("Page has no drawable area.")
    bitmap = page.render(scale=max_size / max(width, height))
    try:
        return bitmap.to_pil().copy()
    finally:
        bitmap.close()


def _validate_page_index(index: int, total: int) -> int:
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError("index must be an int")
    if index < 0 or index >= total:
        raise RangeSpecError(
            f"Page {index + 1} is out of range; the document has {total} page(s)."
        )
    return index


def render_page_image(
    input_path: str | Path,
    index: int,
    dpi: int = 150,
    password: str | None = None,
) -> Image.Image:
    """Render a single 0-based page and return it as a PIL image."""
    with _PDFIUM_LOCK:
        document = _open_document(input_path, password)
        try:
            total = len(document)
            _validate_page_index(index, total)
            page = document[index]
            try:
                return _render_page(page, dpi)
            finally:
                page.close()
        finally:
            document.close()


def render_thumbnail(
    input_path: str | Path,
    index: int,
    max_size: int = 256,
    password: str | None = None,
) -> Image.Image:
    """Render a page scaled so its longest side is at most *max_size* pixels."""
    if max_size <= 0:
        raise ValueError("max_size must be > 0")

    with _PDFIUM_LOCK:
        document = _open_document(input_path, password)
        try:
            total = len(document)
            _validate_page_index(index, total)
            page = document[index]
            try:
                return _render_thumbnail(page, max_size)
            finally:
                page.close()
        finally:
            document.close()


def render_thumbnails(
    input_path: str | Path,
    max_pages: int = 12,
    max_size: int = 120,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> list[Image.Image]:
    """Render the first *max_pages* pages as small PIL thumbnails."""
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    if max_size <= 0:
        raise ValueError("max_size must be > 0")

    images: list[Image.Image] = []
    try:
        with _PDFIUM_LOCK:
            document = _open_document(input_path, password)
            try:
                total = min(len(document), max_pages)
                for index in range(total):
                    check_cancel(cancel)
                    page = document[index]
                    try:
                        images.append(_render_thumbnail(page, max_size))
                    finally:
                        page.close()
                    report(progress, index + 1, total)
            finally:
                document.close()
    except OperationCancelled:
        for image in images:
            image.close()
        raise
    return images


def render_pages(
    input_path: str | Path,
    output_dir: str | Path,
    indices: Iterable[int] | None = None,
    dpi: int = 150,
    image_format: str = "png",
    quality: int = 90,
    password: str | None = None,
    prefix: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> list[Path]:
    """Render selected pages to PNG or JPEG files in *output_dir*.

    Files are named ``<prefix>_page_<number>.<ext>`` using 1-based page
    numbers. When *indices* is ``None`` every page is rendered.
    """
    fmt = image_format.lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in {"png", "jpeg"}:
        raise ValueError("image_format must be 'png' or 'jpeg'")
    if dpi <= 0:
        raise ValueError("dpi must be > 0")
    if not 0 < quality <= 100:
        raise ValueError("quality must be between 1 and 100")

    with _PDFIUM_LOCK:
        document = _open_document(input_path, password)
        try:
            total = len(document)
            selected = (
                list(range(total))
                if indices is None
                else validate_indices(indices, total)
            )

            destination = Path(output_dir)
            destination.mkdir(parents=True, exist_ok=True)
            stem = prefix or Path(input_path).stem
            width = len(str(total))
            extension = "jpg" if fmt == "jpeg" else "png"

            outputs: list[Path] = []
            created: list[Path] = []
            try:
                for position, index in enumerate(selected, start=1):
                    check_cancel(cancel)
                    page = document[index]
                    try:
                        image = _render_page(page, dpi)
                    finally:
                        page.close()

                    if fmt == "jpeg":
                        image = image.convert("RGB")

                    target = (
                        destination / f"{stem}_page_{index + 1:0{width}d}.{extension}"
                    )
                    if not target.exists():
                        created.append(target)
                    try:
                        with atomic_output(target, suffix=f".{extension}") as tmp:
                            if fmt == "jpeg":
                                image.save(
                                    tmp, "JPEG", quality=quality, optimize=True
                                )
                            else:
                                image.save(tmp, "PNG")
                    finally:
                        image.close()
                    outputs.append(target)
                    report(progress, position, len(selected))
            except OperationCancelled:
                for path in created:
                    path.unlink(missing_ok=True)
                raise
            return outputs
        finally:
            document.close()
