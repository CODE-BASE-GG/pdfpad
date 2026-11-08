"""Build a PDF from an ordered list of images."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import PdfOperationError, UnsupportedFileError
from .io import atomic_output, require_file
from .progress import CancelCallback, ProgressCallback, check_cancel, report

# Page dimensions in PostScript points (1/72 inch).
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a3": (841.89, 1190.55),
    "a4": (595.28, 841.89),
    "a5": (419.53, 595.28),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
}

_FIT_MODES = frozenset({"contain", "cover", "stretch"})


def _parse_background(background: str | tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(background, str):
        key = background.strip().lower()
        if key == "white":
            return (255, 255, 255)
        if key == "black":
            return (0, 0, 0)
        raise ValueError("background must be 'white', 'black', or an RGB tuple")
    try:
        red, green, blue = background
    except (TypeError, ValueError) as exc:
        raise ValueError("background must be 'white', 'black', or an RGB tuple") from exc
    values = (red, green, blue)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("background RGB values must be integers")
    if any(value < 0 or value > 255 for value in values):
        raise ValueError("background RGB values must be between 0 and 255")
    return values


def _resolve_page_size(
    page_size: str | tuple[float, float] | None,
) -> tuple[float, float] | None:
    if page_size is None:
        return None
    if isinstance(page_size, str):
        key = page_size.strip().lower()
        if key not in PAGE_SIZES:
            choices = ", ".join(sorted(PAGE_SIZES))
            raise ValueError(f"Unknown page size {page_size!r}; choose one of {choices}")
        return PAGE_SIZES[key]
    try:
        width, height = page_size
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "page_size must be a preset name, a (width, height) tuple, or None"
        ) from exc
    if width <= 0 or height <= 0:
        raise ValueError("page dimensions must be > 0")
    return float(width), float(height)


def _load_image(path: str | Path) -> Image.Image:
    source = require_file(path)
    try:
        image = Image.open(source)
        image.load()
    except UnidentifiedImageError as exc:
        raise UnsupportedFileError(f"Unsupported image: {source}") from exc

    image = ImageOps.exif_transpose(image)
    # Work in RGBA when there is transparency so it can be composited onto the
    # chosen background; otherwise normalise to RGB.
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        return image.convert("RGBA")
    return image.convert("RGB")


def _flatten(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    if image.mode != "RGBA":
        return image.convert("RGB")
    canvas = Image.new("RGB", image.size, background)
    canvas.paste(image, mask=image.getchannel("A"))
    return canvas


def _fit_to_page(
    image: Image.Image,
    page_width: int,
    page_height: int,
    fit: str,
    background: tuple[int, int, int],
) -> Image.Image:
    if fit == "stretch":
        return image.resize((page_width, page_height), Image.Resampling.LANCZOS)

    image_width, image_height = image.size
    if fit == "contain":
        scale = min(page_width / image_width, page_height / image_height)
    else:  # cover
        scale = max(page_width / image_width, page_height / image_height)

    new_size = (
        max(1, round(image_width * scale)),
        max(1, round(image_height * scale)),
    )
    resized = image.resize(new_size, Image.Resampling.LANCZOS)

    if fit == "contain":
        canvas = Image.new("RGB", (page_width, page_height), background)
        offset = ((page_width - new_size[0]) // 2, (page_height - new_size[1]) // 2)
        canvas.paste(resized, offset)
        return canvas

    left = (new_size[0] - page_width) // 2
    top = (new_size[1] - page_height) // 2
    return resized.crop((left, top, left + page_width, top + page_height))


def images_to_pdf(
    image_paths: Sequence[str | Path],
    output_path: str | Path,
    page_size: str | tuple[float, float] | None = "a4",
    fit: str = "contain",
    dpi: int = 150,
    background: str | tuple[int, int, int] = "white",
    quality: int = 90,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> Path:
    """Combine images into a single PDF, preserving input order.

    Args:
        image_paths: Images to include, in page order.
        output_path: Destination PDF.
        page_size: Preset name (``"a4"``, ``"a5"``, ``"a3"``, ``"letter"``,
            ``"legal"``), an explicit ``(width, height)`` in points, or
            ``None`` to size each page from the image pixels at *dpi*.
        fit: ``"contain"`` (letterbox), ``"cover"`` (center-crop), or
            ``"stretch"``.
        dpi: Rendering resolution used to lay images onto page-sized pages and
            stored in the PDF.
        background: Colour used for transparency and letterboxing.
        quality: JPEG quality (1-100) for the embedded images.

    Returns:
        The output path.
    """
    paths = [Path(path) for path in image_paths]
    if not paths:
        raise PdfOperationError("No images provided.")
    if fit not in _FIT_MODES:
        choices = ", ".join(sorted(_FIT_MODES))
        raise ValueError(f"fit must be one of {choices}")
    if dpi <= 0:
        raise ValueError("dpi must be > 0")
    if not 0 < quality <= 100:
        raise ValueError("quality must be between 1 and 100")

    size = _resolve_page_size(page_size)
    colour = _parse_background(background)

    pages: list[Image.Image] = []
    for position, path in enumerate(paths, start=1):
        check_cancel(cancel)
        image = _flatten(_load_image(path), colour)
        if size is not None:
            width = max(1, round(size[0] * dpi / 72))
            height = max(1, round(size[1] * dpi / 72))
            image = _fit_to_page(image, width, height, fit, colour)
        pages.append(image)
        report(progress, position, len(paths))

    first, rest = pages[0], pages[1:]
    try:
        with atomic_output(output_path, suffix=".pdf") as tmp:
            first.save(
                tmp,
                "PDF",
                save_all=True,
                append_images=rest,
                resolution=dpi,
                quality=quality,
            )
    finally:
        for image in pages:
            image.close()
    return Path(output_path)
