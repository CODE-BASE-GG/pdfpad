"""Operation metadata and request building for the GUI.

This module contains no Qt code, which keeps validation and the mapping from
UI options to core calls testable without a display server.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.compress import compress_pdf
from core.images import images_to_pdf
from core.markdown import extract_markdown_to_file
from core.office import OFFICE_SUFFIXES, find_libreoffice, office_to_pdf
from core.pages import (
    extract_pages,
    merge_pdfs,
    page_count,
    rotate_pages,
    split_pdf,
)
from core.render import render_pages
from core.ranges import parse_ranges
from core.text import extract_text_to_file

PDF_SUFFIXES = frozenset({".pdf"})
IMAGE_SUFFIXES = frozenset(
    {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)
SUPPORTED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES | OFFICE_SUFFIXES

PAGE_SIZE_OPTIONS = ("A4", "A5", "A3", "Letter", "Legal", "Original size")
_PAGE_SIZE_MAP: dict[str, str | None] = {
    "A4": "a4",
    "A5": "a5",
    "A3": "a3",
    "Letter": "letter",
    "Legal": "legal",
    "Original size": None,
}
FIT_OPTIONS = ("Contain", "Cover", "Stretch")
_FIT_MAP = {"Contain": "contain", "Cover": "cover", "Stretch": "stretch"}
FORMAT_OPTIONS = ("PNG", "JPEG")
_FORMAT_MAP = {"PNG": "png", "JPEG": "jpeg"}


class RequestError(Exception):
    """A user-facing validation error raised before an operation starts."""


@dataclass(frozen=True)
class OperationSpec:
    key: str
    label: str
    inputs: str  # "pdf", "pdfs", "images" or "office"
    output: str  # "file" or "dir"
    default_suffix: str
    description: str


OPERATIONS: tuple[OperationSpec, ...] = (
    OperationSpec(
        "extract",
        "Extract pages",
        "pdf",
        "file",
        "_extracted.pdf",
        "Copy selected pages into a new PDF.",
    ),
    OperationSpec(
        "split",
        "Split PDF",
        "pdf",
        "dir",
        "_pages",
        "Split a PDF into one file per page or into chunks.",
    ),
    OperationSpec(
        "merge",
        "Merge PDFs",
        "pdfs",
        "file",
        "_merged.pdf",
        "Combine several PDFs into one, in list order.",
    ),
    OperationSpec(
        "rotate",
        "Rotate pages",
        "pdf",
        "file",
        "_rotated.pdf",
        "Rotate all pages or a selected page range.",
    ),
    OperationSpec(
        "render",
        "PDF to images",
        "pdf",
        "dir",
        "_images",
        "Render pages to PNG or JPEG at a chosen DPI.",
    ),
    OperationSpec(
        "images_to_pdf",
        "Images to PDF",
        "images",
        "file",
        "_images.pdf",
        "Combine images into a PDF, in list order.",
    ),
    OperationSpec(
        "text",
        "Extract text",
        "pdf",
        "file",
        ".txt",
        "Save the text of selected pages as UTF-8.",
    ),
    OperationSpec(
        "markdown",
        "Extract Markdown",
        "pdf",
        "file",
        ".md",
        "Save selected pages as best-effort Markdown.",
    ),
    OperationSpec(
        "compress",
        "Compress PDF",
        "pdf",
        "file",
        "_compressed.pdf",
        "Shrink a PDF losslessly or by rasterizing its pages.",
    ),
    OperationSpec(
        "office",
        "Office to PDF",
        "office",
        "dir",
        "_office",
        "Convert Office documents with the optional LibreOffice add-on.",
    ),
)
OPERATIONS_BY_KEY: dict[str, OperationSpec] = {spec.key: spec for spec in OPERATIONS}

_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "extract": extract_pages,
    "split": split_pdf,
    "merge": merge_pdfs,
    "rotate": rotate_pages,
    "render": render_pages,
    "images_to_pdf": images_to_pdf,
    "text": extract_text_to_file,
    "markdown": extract_markdown_to_file,
    "compress": compress_pdf,
    "office": office_to_pdf,
}


@dataclass
class OperationOptions:
    page_range: str = ""
    chunk_size: int = 1
    degrees: int = 90
    dpi: int = 150
    image_format: str = "png"
    quality: int = 90
    page_size: str = "A4"
    fit: str = "contain"
    compression_mode: str = "lossless"
    output: Path | None = None


@dataclass(frozen=True)
class OperationRequest:
    spec: OperationSpec
    func: Callable[..., Any]
    kwargs: dict[str, Any] = field(default_factory=dict)
    output: Path = Path()


def is_pdf(path: str | Path) -> bool:
    return Path(path).suffix.lower() in PDF_SUFFIXES


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def is_office(path: str | Path) -> bool:
    return Path(path).suffix.lower() in OFFICE_SUFFIXES


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def default_output(key: str, files: Sequence[str | Path]) -> Path | None:
    """Return a sensible default output path for *key* and the input files."""
    if not files:
        return None
    first = Path(files[0])
    stem = first.stem
    parent = first.parent
    if key == "extract":
        return parent / f"{stem}_extracted.pdf"
    if key == "split":
        return parent / f"{stem}_pages"
    if key == "merge":
        return parent / f"{stem}_merged.pdf"
    if key == "rotate":
        return parent / f"{stem}_rotated.pdf"
    if key == "render":
        return parent / f"{stem}_images"
    if key == "images_to_pdf":
        return parent / f"{stem}_images.pdf"
    if key == "text":
        return parent / f"{stem}.txt"
    if key == "markdown":
        return parent / f"{stem}.md"
    if key == "compress":
        return parent / f"{stem}_compressed.pdf"
    if key == "office":
        return parent / f"{stem}_office"
    return None


def _validate_inputs(spec: OperationSpec, paths: Sequence[Path]) -> None:
    if not paths:
        raise RequestError("Add at least one input file.")

    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise RequestError(f"File not found: {missing[0]}")

    if spec.inputs == "pdf":
        if len(paths) != 1:
            raise RequestError(f"{spec.label} needs exactly one PDF file.")
        if not is_pdf(paths[0]):
            raise RequestError(f"{spec.label} needs a PDF file.")
        return

    if spec.inputs == "pdfs":
        if len(paths) < 2:
            raise RequestError("Merge needs at least two PDF files.")
        not_pdf = [path for path in paths if not is_pdf(path)]
        if not_pdf:
            raise RequestError(f"Not a PDF file: {not_pdf[0].name}")
        return

    if spec.inputs == "images":
        not_image = [path for path in paths if not is_image(path)]
        if not_image:
            raise RequestError(f"Not a supported image: {not_image[0].name}")
        return

    if spec.inputs == "office":
        not_office = [path for path in paths if not is_office(path)]
        if not_office:
            raise RequestError(
                f"Not a supported Office document: {not_office[0].name}"
            )


def _normalise_output(spec: OperationSpec, output: Path) -> Path:
    if spec.output == "file" and output.suffix == "":
        return output.with_name(output.name + spec.default_suffix)
    return output


def _validate_output(spec: OperationSpec, output: Path, inputs: Sequence[Path]) -> None:
    resolved = output.resolve()
    for path in inputs:
        if resolved == path.resolve():
            raise RequestError(f"Output would overwrite the input file: {path.name}")

    if spec.output == "dir" and output.exists() and not output.is_dir():
        raise RequestError(f"Output is not a folder: {output}")


def _page_indices(spec: str, total: int) -> list[int] | None:
    if not spec.strip():
        return None
    return parse_ranges(spec, total)


def _page_counts(paths: Sequence[Path], passwords: Mapping[Path, str]) -> list[int]:
    return [page_count(path, password=passwords.get(path)) for path in paths]


def build_request(
    key: str,
    files: Sequence[str | Path],
    options: OperationOptions,
    passwords: Mapping[Path, str] | None = None,
) -> OperationRequest:
    """Validate inputs and options, then build a callable core request.

    Raises:
        RequestError: The selection of files, output, or options is invalid.
        PdfPadError: A PDF cannot be read (missing password, corrupt file, ...).
    """
    spec = OPERATIONS_BY_KEY.get(key)
    if spec is None:
        raise RequestError(f"Unknown operation: {key}")

    paths = [Path(path) for path in files]
    _validate_inputs(spec, paths)
    resolved_passwords = dict(passwords or {})

    chosen_output = options.output or default_output(key, paths)
    if chosen_output is None:
        raise RequestError("Choose an output location.")
    output = _normalise_output(spec, Path(chosen_output))
    _validate_output(spec, output, paths)

    kwargs: dict[str, Any] = {}
    counts: list[int] = []
    if spec.inputs in {"pdf", "pdfs"}:
        counts = _page_counts(paths, resolved_passwords)

    if spec.key == "extract":
        indices = _page_indices(options.page_range, counts[0])
        if indices is None:
            indices = list(range(counts[0]))
        kwargs = {
            "input_path": paths[0],
            "indices": indices,
            "output_path": output,
            "password": resolved_passwords.get(paths[0]),
        }

    elif spec.key == "split":
        if options.chunk_size < 1:
            raise RequestError("Chunk size must be at least 1.")
        kwargs = {
            "input_path": paths[0],
            "output_dir": output,
            "chunk_size": options.chunk_size,
            "password": resolved_passwords.get(paths[0]),
        }

    elif spec.key == "merge":
        kwargs = {
            "input_paths": paths,
            "output_path": output,
            "passwords": [resolved_passwords.get(path) for path in paths],
        }

    elif spec.key == "rotate":
        if options.degrees % 90 != 0:
            raise RequestError("Rotation must be a multiple of 90 degrees.")
        kwargs = {
            "input_path": paths[0],
            "output_path": output,
            "degrees": options.degrees,
            "indices": _page_indices(options.page_range, counts[0]),
            "password": resolved_passwords.get(paths[0]),
        }

    elif spec.key == "render":
        if options.dpi <= 0:
            raise RequestError("DPI must be greater than 0.")
        if not 0 < options.quality <= 100:
            raise RequestError("Quality must be between 1 and 100.")
        if options.image_format not in {"png", "jpeg"}:
            raise RequestError("Image format must be PNG or JPEG.")
        kwargs = {
            "input_path": paths[0],
            "output_dir": output,
            "indices": _page_indices(options.page_range, counts[0]),
            "dpi": options.dpi,
            "image_format": options.image_format,
            "quality": options.quality,
            "password": resolved_passwords.get(paths[0]),
        }

    elif spec.key == "images_to_pdf":
        page_size = _PAGE_SIZE_MAP.get(options.page_size)
        if options.page_size not in _PAGE_SIZE_MAP:
            raise RequestError(f"Unknown page size: {options.page_size}")
        if options.fit not in {"contain", "cover", "stretch"}:
            raise RequestError(f"Unknown fit mode: {options.fit}")
        if options.dpi <= 0:
            raise RequestError("DPI must be greater than 0.")
        if not 0 < options.quality <= 100:
            raise RequestError("Quality must be between 1 and 100.")
        kwargs = {
            "image_paths": paths,
            "output_path": output,
            "page_size": page_size,
            "fit": options.fit,
            "dpi": options.dpi,
            "quality": options.quality,
        }

    elif spec.key == "text":
        kwargs = {
            "input_path": paths[0],
            "output_path": output,
            "indices": _page_indices(options.page_range, counts[0]),
            "password": resolved_passwords.get(paths[0]),
        }

    elif spec.key == "markdown":
        kwargs = {
            "input_path": paths[0],
            "output_path": output,
            "indices": _page_indices(options.page_range, counts[0]),
            "password": resolved_passwords.get(paths[0]),
        }

    elif spec.key == "compress":
        if options.compression_mode not in {"lossless", "rasterize"}:
            raise RequestError(
                f"Unknown compression mode: {options.compression_mode}"
            )
        if options.compression_mode == "rasterize":
            if options.dpi <= 0:
                raise RequestError("DPI must be greater than 0.")
            if not 0 < options.quality <= 100:
                raise RequestError("Quality must be between 1 and 100.")
        kwargs = {
            "input_path": paths[0],
            "output_path": output,
            "mode": options.compression_mode,
            "dpi": options.dpi,
            "quality": options.quality,
            "password": resolved_passwords.get(paths[0]),
        }

    elif spec.key == "office":
        found = find_libreoffice()
        if found is None:
            raise RequestError(
                "The optional LibreOffice add-on is not installed. "
                "Install the add-on pack to convert Office documents."
            )
        binary, _source = found
        kwargs = {
            "input_paths": paths,
            "output_dir": output,
            "binary": binary,
        }

    return OperationRequest(
        spec=spec,
        func=_FUNCTIONS[spec.key],
        kwargs=kwargs,
        output=output,
    )
