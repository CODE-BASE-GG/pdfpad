"""Best-effort PDF to Markdown conversion built on pdfminer.six.

The conversion is heuristic, not lossless. It recognises:

* headings, by comparing a line's font size with the document's body size;
* paragraphs, by grouping lines with a small vertical gap;
* bullet and numbered lists, from common leading markers;
* simple tables, when consecutive rows share aligned columns.

Complex layouts (multi-column pages, merged table cells, text inside figures)
are flattened. The output is intended as a readable starting point, not as a
faithful reproduction of the original document.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTContainer, LTPage, LTTextLine
from pdfminer.pdfdocument import (
    PDFEncryptionError,
    PDFPasswordIncorrect,
    PDFSyntaxError,
)

from .errors import EncryptedPdfError, PdfOperationError
from .io import write_text
from .pages import open_pdf
from .progress import CancelCallback, ProgressCallback, check_cancel, report
from .ranges import validate_indices

_BULLET_RE = re.compile(
    r"^([\u2022\u00b7\u25aa\u25e6\u2023\u2219*+\-\u2013\u2014])\s+(.*\S)\s*$"
)
_NUMBER_RE = re.compile(r"^(\d{1,3})[.)]\s+(.*\S)\s*$")

_BOLD_MARKERS = ("bold", "black", "heavy", "semibold", "demi")


@dataclass(frozen=True)
class _Line:
    """A single text line with the geometry needed for layout heuristics."""

    text: str
    x0: float
    x1: float
    y0: float
    y1: float
    size: float
    bold: bool

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def _is_bold_font(fontname: str) -> bool:
    lowered = fontname.lower()
    return any(marker in lowered for marker in _BOLD_MARKERS)


def _iter_text_lines(obj: LTContainer) -> Iterator[LTTextLine]:
    if isinstance(obj, LTTextLine):
        yield obj
    elif isinstance(obj, LTContainer):
        for child in obj:
            yield from _iter_text_lines(child)


def _extract_lines(layout: LTPage) -> list[_Line]:
    """Flatten a pdfminer page into text lines, preserving position and style."""
    lines: list[_Line] = []
    for item in _iter_text_lines(layout):
        text = " ".join(item.get_text().split())
        if not text:
            continue

        chars = [child for child in item if isinstance(child, LTChar)]
        if chars:
            size = float(median(child.size for child in chars))
            bold = sum(
                1 for child in chars if _is_bold_font(child.fontname)
            ) > len(chars) / 2
        else:
            size = float(item.height)
            bold = False

        lines.append(
            _Line(
                text=text,
                x0=float(item.x0),
                x1=float(item.x1),
                y0=float(item.y0),
                y1=float(item.y1),
                size=size,
                bold=bold,
            )
        )
    return lines


def _body_size(lines: Iterable[_Line]) -> float:
    """Return the document's dominant font size, weighted by text length."""
    pairs = sorted(
        (line.size, max(1, min(len(line.text), 200))) for line in lines
    )
    if not pairs:
        return 12.0

    total = sum(weight for _size, weight in pairs)
    midpoint = total / 2
    accumulated = 0
    for size, weight in pairs:
        accumulated += weight
        if accumulated >= midpoint:
            return size
    return pairs[-1][0]


def _group_rows(lines: Iterable[_Line]) -> list[list[_Line]]:
    """Group lines that share a baseline into visual rows, top to bottom."""
    rows: list[list[_Line]] = []
    for line in sorted(lines, key=lambda item: (-item.y1, item.x0)):
        for row in rows:
            reference = row[0]
            tolerance = max(2.0, 0.15 * max(reference.height, line.height))
            if abs(line.y0 - reference.y0) <= tolerance:
                row.append(line)
                break
        else:
            rows.append([line])

    for row in rows:
        row.sort(key=lambda item: item.x0)
    return rows


def _escape_cell(text: str) -> str:
    return text.replace("|", r"\|").strip()


def _table_from_rows(rows: list[list[_Line]], page_width: float) -> str | None:
    """Return Markdown for a block of aligned multi-cell rows, or ``None``."""
    if len(rows) < 2:
        return None

    counts = {len(row) for row in rows}
    if len(counts) != 1:
        return None
    column_count = counts.pop()
    if column_count < 2:
        return None

    tolerance = max(20.0, 0.05 * page_width)
    for column in range(column_count):
        starts = [row[column].x0 for row in rows]
        if max(starts) - min(starts) > tolerance:
            return None

    if any(len(cell.text) > 100 for row in rows for cell in row):
        return None

    header, *body = rows
    output = [
        "| " + " | ".join(_escape_cell(cell.text) for cell in header) + " |",
        "| " + " | ".join("---" for _ in range(column_count)) + " |",
    ]
    for row in body:
        output.append(
            "| " + " | ".join(_escape_cell(cell.text) for cell in row) + " |"
        )
    return "\n".join(output)


def _find_tables(
    rows: list[list[_Line]], page_width: float
) -> dict[int, tuple[int, str]]:
    """Map the first row index of each detected table to ``(end, markdown)``."""
    tables: dict[int, tuple[int, str]] = {}
    index = 0
    while index < len(rows):
        column_count = len(rows[index])
        if column_count < 2:
            index += 1
            continue

        # Group only rows with the same number of cells. A later row with a
        # different shape starts a new candidate instead of invalidating the
        # table that came before it.
        end = index
        while end < len(rows) and len(rows[end]) == column_count:
            end += 1

        markdown = _table_from_rows(rows[index:end], page_width)
        if markdown is not None:
            tables[index] = (end, markdown)
        index = end
    return tables


def _heading_level(line: _Line, body_size: float) -> int:
    """Return 1–3 for a heading line, or 0 for body text."""
    if not line.text or len(line.text) > 120:
        return 0

    ratio = line.size / body_size if body_size > 0 else 1.0
    if ratio >= 1.7:
        return 1
    if ratio >= 1.32:
        return 2
    if ratio >= 1.12 and line.bold:
        return 3
    return 0


def _list_item(text: str) -> tuple[str, str, str] | None:
    """Return ``(markdown_marker, content, kind)`` for a list-looking line."""
    match = _BULLET_RE.match(text)
    if match:
        return "-", match.group(2), "bullet"

    match = _NUMBER_RE.match(text)
    if match:
        return f"{match.group(1)}.", match.group(2), "number"

    return None


def _new_paragraph(previous: _Line, line: _Line) -> bool:
    gap = previous.y0 - line.y1
    if gap > 0.6 * max(previous.height, line.height):
        return True
    return abs(line.size - previous.size) > 0.5


def _join_paragraph(lines: list[_Line]) -> str:
    parts: list[str] = []
    for line in lines:
        text = line.text
        if not text:
            continue
        if parts and parts[-1].endswith("-") and text[:1].islower():
            parts[-1] = parts[-1][:-1] + text
        else:
            parts.append(text)
    return " ".join(parts)


def _format_flow(lines: list[_Line], body_size: float) -> list[str]:
    """Convert a run of non-table lines into headings, lists and paragraphs."""
    blocks: list[str] = []
    paragraph: list[_Line] = []
    list_items: list[str] = []
    list_kind: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(_join_paragraph(paragraph))
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_kind
        if list_items:
            blocks.append("\n".join(list_items))
            list_items.clear()
        list_kind = None

    index = 0
    while index < len(lines):
        line = lines[index]

        level = _heading_level(line, body_size)
        if level:
            flush_paragraph()
            flush_list()
            blocks.append("#" * level + " " + line.text)
            index += 1
            continue

        item = _list_item(line.text)
        if item is not None:
            flush_paragraph()
            marker, content, kind = item
            if list_items and kind != list_kind:
                flush_list()
            list_kind = kind

            current = f"{marker} {content}"
            item_x0 = line.x0
            previous = line
            index += 1
            while index < len(lines):
                following = lines[index]
                if _heading_level(following, body_size):
                    break
                if _list_item(following.text) is not None:
                    break
                gap = previous.y0 - following.y1
                indented = following.x0 >= item_x0 + 4
                if indented and gap <= 0.8 * max(previous.height, following.height):
                    current += " " + following.text
                    previous = following
                    index += 1
                else:
                    break

            list_items.append(current)
            continue

        flush_list()
        if paragraph and _new_paragraph(paragraph[-1], line):
            flush_paragraph()
        paragraph.append(line)
        index += 1

    flush_paragraph()
    flush_list()
    return blocks


def _page_to_markdown(
    lines: list[_Line], body_size: float, page_width: float
) -> str:
    rows = _group_rows(lines)
    tables = _find_tables(rows, page_width)

    blocks: list[str] = []
    index = 0
    while index < len(rows):
        table = tables.get(index)
        if table is not None:
            end, markdown = table
            blocks.append(markdown)
            index = end
            continue

        end = index
        while end < len(rows) and end not in tables:
            end += 1

        flow = [line for row in rows[index:end] for line in row]
        blocks.extend(_format_flow(flow, body_size))
        index = end

    return "\n\n".join(block for block in blocks if block.strip())


def extract_markdown(
    input_path: str | Path,
    indices: Iterable[int] | None = None,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> str:
    """Return selected pages as best-effort Markdown.

    When *indices* is ``None`` every page is included. Page order follows the
    selection order, like :func:`core.text.extract_text_per_page`. Blank pages
    contribute nothing.
    """
    reader = open_pdf(input_path, password)
    total = len(reader.pages)
    selected = (
        list(range(total)) if indices is None else validate_indices(indices, total)
    )
    if not selected:
        return ""

    source = Path(input_path)
    # ``validate_indices`` preserves duplicates and order. Parse each unique
    # page once, then emit pages in the requested order (duplicates included).
    unique_pages = list(dict.fromkeys(selected))
    ordered = sorted(unique_pages)
    layouts: dict[int, tuple[LTPage, list[_Line]]] = {}
    parsed = 0

    try:
        pages = extract_pages(
            str(source),
            password=password or "",
            page_numbers=set(ordered),
            laparams=LAParams(),
        )
        for page_index, layout in zip(ordered, pages):
            check_cancel(cancel)
            layouts[page_index] = (layout, _extract_lines(layout))
            parsed += 1
            report(progress, parsed, len(unique_pages))
    except PDFPasswordIncorrect as exc:
        raise EncryptedPdfError(f"Incorrect password for {source.name}.") from exc
    except PDFEncryptionError as exc:
        raise EncryptedPdfError(f"{source.name} is password-protected.") from exc
    except (PDFSyntaxError, OSError) as exc:
        raise PdfOperationError(
            f"Could not read PDF {source.name}: {exc}"
        ) from exc

    if parsed != len(unique_pages):
        raise PdfOperationError(f"Could not read all pages from {source.name}.")

    all_lines = [line for _layout, lines in layouts.values() for line in lines]
    body_size = _body_size(all_lines)

    chunks: list[str] = []
    for page_index in selected:
        check_cancel(cancel)
        layout, lines = layouts[page_index]
        markdown = _page_to_markdown(lines, body_size, float(layout.width))
        if markdown.strip():
            chunks.append(markdown)
    return "\n\n".join(chunks)


def extract_markdown_to_file(
    input_path: str | Path,
    output_path: str | Path,
    indices: Iterable[int] | None = None,
    password: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> Path:
    """Convert selected pages to Markdown and write them atomically as UTF-8."""
    markdown = extract_markdown(
        input_path,
        indices=indices,
        password=password,
        progress=progress,
        cancel=cancel,
    )
    return write_text(output_path, markdown)
