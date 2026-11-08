"""PDF compression: lossless stream recompression and rasterization.

The lossless mode rewrites the PDF with QPDF (through :mod:`pikepdf`), using
object streams and Flate recompression. It keeps text and vectors intact.

The rasterize mode renders every page to a JPEG and rebuilds the PDF from those
images. It can shrink scanned documents dramatically, but it removes the text
layer, so the output is no longer searchable. The GUI labels this mode clearly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pikepdf

from .errors import EncryptedPdfError, PdfOperationError
from .images import images_to_pdf
from .io import atomic_output, require_file
from .progress import CancelCallback, ProgressCallback, check_cancel, report
from .render import render_pages

COMPRESSION_MODES = frozenset({"lossless", "rasterize"})


def _open_pdf(path: str | Path, password: str | None) -> pikepdf.Pdf:
    """Open a PDF with pikepdf, translating password and read errors."""
    source = require_file(path)
    try:
        return pikepdf.open(str(source), password=password or "")
    except pikepdf.PasswordError as exc:
        if password is None:
            raise EncryptedPdfError(f"{source.name} is password-protected.") from exc
        raise EncryptedPdfError(f"Incorrect password for {source.name}.") from exc
    except pikepdf.PdfError as exc:
        raise PdfOperationError(f"Could not read PDF {source.name}: {exc}") from exc
    except OSError as exc:
        raise PdfOperationError(f"Could not read PDF {source.name}: {exc}") from exc


def _compress_lossless(
    input_path: str | Path,
    output_path: str | Path,
    password: str | None,
    progress: ProgressCallback | None,
    cancel: CancelCallback | None,
) -> Path:
    pdf = _open_pdf(input_path, password)
    try:
        check_cancel(cancel)
        with atomic_output(output_path, suffix=".pdf") as tmp:
            def _pikepdf_progress(value: int) -> None:
                # QPDF reports 0 and 100. Keep the GUI bar in a 1..100 range.
                report(progress, max(1, min(100, int(value))), 100)

            pdf.save(
                tmp,
                compress_streams=True,
                recompress_flate=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                linearize=False,
                qdf=False,
                progress=_pikepdf_progress,
            )
            # If cancellation arrived while QPDF was writing, discard the
            # temporary file instead of replacing the destination.
            check_cancel(cancel)
    finally:
        pdf.close()
    return Path(output_path)


def _compress_rasterize(
    input_path: str | Path,
    output_path: str | Path,
    dpi: int,
    quality: int,
    password: str | None,
    progress: ProgressCallback | None,
    cancel: CancelCallback | None,
) -> Path:
    with tempfile.TemporaryDirectory(prefix="pdfpad-raster-") as tmp:
        images_dir = Path(tmp)

        def _render_progress(current: int, total: int) -> None:
            report(progress, current, total * 2)

        image_paths = render_pages(
            input_path,
            images_dir,
            indices=None,
            dpi=dpi,
            image_format="jpeg",
            quality=quality,
            password=password,
            progress=_render_progress,
            cancel=cancel,
        )

        def _assemble_progress(current: int, total: int) -> None:
            report(progress, total + current, total * 2)

        # page_size=None keeps each page at its original physical size: the
        # rendered pixel dimensions divided by the chosen DPI.
        images_to_pdf(
            image_paths,
            output_path,
            page_size=None,
            dpi=dpi,
            quality=quality,
            progress=_assemble_progress,
            cancel=cancel,
        )
    return Path(output_path)


def compress_pdf(
    input_path: str | Path,
    output_path: str | Path,
    mode: str = "lossless",
    dpi: int = 150,
    quality: int = 75,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> Path:
    """Compress *input_path* into *output_path*.

    Args:
        input_path: Source PDF.
        output_path: Destination PDF, written atomically.
        mode: ``"lossless"`` (keep text and vectors) or ``"rasterize"``
            (rebuild every page as a JPEG; text becomes unsearchable).
        dpi: Rasterization resolution for ``"rasterize"``.
        quality: JPEG quality (1-100) for ``"rasterize"``.
        password: Password for an encrypted source PDF.

    Returns:
        The output path.

    Raises:
        ValueError: The mode, DPI, or quality is invalid.
        EncryptedPdfError: The source is encrypted and the password is missing
            or wrong.
        PdfOperationError: The source cannot be read or written.
        OperationCancelled: The caller cancelled the operation.
    """
    if mode not in COMPRESSION_MODES:
        choices = ", ".join(sorted(COMPRESSION_MODES))
        raise ValueError(f"Unknown compression mode {mode!r}; choose one of {choices}")
    if mode == "rasterize":
        if dpi <= 0:
            raise ValueError("dpi must be > 0")
        if not 0 < quality <= 100:
            raise ValueError("quality must be between 1 and 100")

    source = Path(input_path)
    target = Path(output_path)
    if source.resolve() == target.resolve():
        raise PdfOperationError("Output would overwrite the input file.")

    check_cancel(cancel)
    if mode == "lossless":
        return _compress_lossless(source, target, password, progress, cancel)
    return _compress_rasterize(
        source, target, dpi, quality, password, progress, cancel
    )
