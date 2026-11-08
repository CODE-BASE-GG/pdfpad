#!/usr/bin/env python3
"""Generate the PDFPad application icon at the sizes packaging needs.

The icon is drawn programmatically with Pillow so the repository does not need
to carry a binary source file. Running this script refreshes:

* ``gui/resources/pdfpad.png`` (used as the Qt window icon at runtime)
* ``packaging/linux/icons/hicolor/<size>/apps/pdfpad.png`` (desktop icons)

The matching scalable icon is ``packaging/linux/pdfpad.svg``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
SUPERSAMPLE = 4

# Palette shared with packaging/linux/pdfpad.svg.
BACKGROUND_TOP = (42, 95, 143, 255)
BACKGROUND_BOTTOM = (22, 50, 79, 255)
PAGE = (255, 255, 255, 255)
FOLD = (201, 216, 230, 255)
BAND = (217, 79, 79, 255)
TEXT_LINE = (159, 180, 200, 255)

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _background(size: int) -> Image.Image:
    """Return a vertical gradient clipped to a rounded square."""
    gradient = Image.new("RGBA", (size, size))
    pixels = gradient.load()
    for y in range(size):
        ratio = y / max(1, size - 1)
        colour = tuple(
            round(top + (bottom - top) * ratio)
            for top, bottom in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM)
        )
        for x in range(size):
            pixels[x, y] = colour

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * 0.1875), fill=255
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(gradient, (0, 0), mask)
    return canvas


def _draw_icon(size: int) -> Image.Image:
    """Draw the icon at *size* pixels using a supersampled canvas."""
    scale = SUPERSAMPLE
    canvas_size = size * scale
    image = _background(canvas_size)
    draw = ImageDraw.Draw(image)

    def s(value: float) -> int:
        return round(value * canvas_size / 256)

    # Page with a folded top-right corner.
    page_box = (s(64), s(40), s(192), s(216))
    draw.rounded_rectangle(page_box, radius=s(10), fill=PAGE)
    draw.polygon(
        [(s(158), s(40)), (s(182), s(40)), (s(192), s(50)), (s(192), s(74))],
        fill=FOLD,
    )

    # Three text lines above the red band.
    for index, width in enumerate((88, 64, 76)):
        y = s(92 + index * 20)
        draw.rounded_rectangle(
            (s(84), y, s(84 + width), y + s(9)),
            radius=s(4.5),
            fill=TEXT_LINE,
        )

    # Red band with the PDF label.
    draw.rectangle((s(64), s(150), s(192), s(192)), fill=BAND)
    font = _load_font(s(30))
    label = "PDF"
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    draw.text(
        (
            s(128) - (right - left) / 2 - left,
            s(171) - (bottom - top) / 2 - top,
        ),
        label,
        font=font,
        fill=PAGE,
    )

    return image.resize((size, size), Image.LANCZOS)


def generate(project_root: Path = PROJECT_ROOT) -> list[Path]:
    """Write all icon files and return the paths that were written."""
    written: list[Path] = []

    runtime_icon = project_root / "gui" / "resources" / "pdfpad.png"
    runtime_icon.parent.mkdir(parents=True, exist_ok=True)
    _draw_icon(256).save(runtime_icon, format="PNG", optimize=True)
    written.append(runtime_icon)

    for size in SIZES:
        target = (
            project_root
            / "packaging"
            / "linux"
            / "icons"
            / "hicolor"
            / f"{size}x{size}"
            / "apps"
            / "pdfpad.png"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        _draw_icon(size).save(target, format="PNG", optimize=True)
        written.append(target)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="PDFPad source tree (default: the repository containing this script)",
    )
    args = parser.parse_args(argv)

    for path in generate(args.project_root.resolve()):
        print(path.relative_to(args.project_root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
