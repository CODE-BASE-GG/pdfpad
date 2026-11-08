"""Helpers that build small PDFs and images for the test suite."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _add_text(writer: PdfWriter, page, text: str) -> None:
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )

    stream = DecodedStreamObject()
    escaped = _escape_pdf_text(text)
    stream.set_data(f"BT /F1 12 Tf 20 100 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def make_pdf(
    path: str | Path,
    page_sizes: list[tuple[float, float]] | None = None,
    texts: list[str] | None = None,
) -> Path:
    """Create a PDF whose pages have distinct sizes (useful for order checks)."""
    sizes = page_sizes or [(300.0, 400.0)] * 3
    if texts is not None and len(texts) > len(sizes):
        raise ValueError("more texts than pages")

    writer = PdfWriter()
    for width, height in sizes:
        writer.add_blank_page(width=width, height=height)
    for index, text in enumerate(texts or []):
        _add_text(writer, writer.pages[index], text)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def make_text_pdf(
    path: str | Path,
    texts: list[str],
    page_size: tuple[float, float] = (300.0, 400.0),
) -> Path:
    return make_pdf(path, [page_size] * len(texts), texts)


def make_rich_pdf(
    path: str | Path,
    pages: list[list[tuple[str, float, float, float, bool]]],
    page_size: tuple[float, float] = (612.0, 792.0),
) -> Path:
    """Create a PDF with positioned, styled text blocks.

    Each page is a list of ``(text, x, y, size, bold)`` tuples. Text is drawn
    at the given baseline, which lets tests exercise heading, list and table
    heuristics without needing a real document.
    """
    writer = PdfWriter()

    regular_font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    bold_font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
        }
    )
    regular_ref = writer._add_object(regular_font)
    bold_ref = writer._add_object(bold_font)

    for blocks in pages:
        page = writer.add_blank_page(width=page_size[0], height=page_size[1])
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): regular_ref,
                        NameObject("/F2"): bold_ref,
                    }
                )
            }
        )

        commands = []
        for text, x, y, size, bold in blocks:
            font = "F2" if bold else "F1"
            escaped = _escape_pdf_text(text)
            commands.append(
                f"BT /{font} {size} Tf {x} {y} Td ({escaped}) Tj ET"
            )
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def make_encrypted_pdf(
    path: str | Path,
    password: str,
    page_count: int = 2,
    page_size: tuple[float, float] = (300.0, 400.0),
) -> Path:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=page_size[0], height=page_size[1])
    writer.encrypt(password)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def make_image(
    path: str | Path,
    size: tuple[int, int] = (200, 100),
    color="red",
    mode: str = "RGB",
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color).save(target)
    return target
