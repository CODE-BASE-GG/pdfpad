"""Tests for the Qt-free GUI request builder and operation metadata."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from core.errors import EncryptedPdfError
from core.images import images_to_pdf
from core.markdown import extract_markdown_to_file
from core.pages import extract_pages, merge_pdfs, rotate_pages, split_pdf
from core.render import render_pages
from core.text import extract_text_to_file
from gui.operations import (
    OPERATIONS,
    OPERATIONS_BY_KEY,
    OperationOptions,
    RequestError,
    build_request,
    default_output,
    is_image,
    is_office,
    is_pdf,
    is_supported,
)
from tests.pdf_fixtures import make_image


# -- metadata and suffix helpers -------------------------------------------


def test_every_operation_is_indexed():
    assert set(OPERATIONS_BY_KEY) == {spec.key for spec in OPERATIONS}
    assert len(OPERATIONS_BY_KEY) == len(OPERATIONS)


@pytest.mark.parametrize(
    ("path", "pdf", "image", "supported"),
    [
        ("a.pdf", True, False, True),
        ("a.PDF", True, False, True),
        ("a.PNG", False, True, True),
        ("a.jpeg", False, True, True),
        ("a.txt", False, False, False),
        ("a", False, False, False),
    ],
)
def test_suffix_helpers(path, pdf, image, supported):
    assert is_pdf(path) is pdf
    assert is_image(path) is image
    assert is_supported(path) is supported


@pytest.mark.parametrize(
    ("path", "office"),
    [
        ("a.docx", True),
        ("a.ODT", True),
        ("a.xls", True),
        ("a.pdf", False),
        ("a.txt", False),
    ],
)
def test_is_office(path, office):
    assert is_office(path) is office


# -- default output --------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("extract", "report_extracted.pdf"),
        ("split", "report_pages"),
        ("merge", "report_merged.pdf"),
        ("rotate", "report_rotated.pdf"),
        ("render", "report_images"),
        ("images_to_pdf", "report_images.pdf"),
        ("text", "report.txt"),
        ("markdown", "report.md"),
        ("compress", "report_compressed.pdf"),
        ("office", "report_office"),
    ],
)
def test_default_output_names(tmp_path, key, expected):
    source = tmp_path / "report.pdf"
    assert default_output(key, [source]) == tmp_path / expected


def test_default_output_without_files():
    assert default_output("extract", []) is None


def test_default_output_unknown_operation(tmp_path):
    assert default_output("nope", [tmp_path / "a.pdf"]) is None


# -- request building ------------------------------------------------------


def _options(**overrides) -> OperationOptions:
    return OperationOptions(**overrides)


def test_build_extract_request(five_page_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    request = build_request(
        "extract",
        [five_page_pdf],
        _options(page_range="2-3", output=output),
    )
    assert request.spec.key == "extract"
    assert request.func is extract_pages
    assert request.output == output
    assert request.kwargs == {
        "input_path": Path(five_page_pdf),
        "indices": [1, 2],
        "output_path": output,
        "password": None,
    }


def test_build_extract_defaults_to_all_pages(five_page_pdf, tmp_path):
    request = build_request(
        "extract",
        [five_page_pdf],
        _options(output=tmp_path / "out.pdf"),
    )
    assert request.kwargs["indices"] == [0, 1, 2, 3, 4]


def test_build_extract_keeps_selection_order(five_page_pdf, tmp_path):
    request = build_request(
        "extract",
        [five_page_pdf],
        _options(page_range="5,1-2", output=tmp_path / "out.pdf"),
    )
    assert request.kwargs["indices"] == [4, 0, 1]


def test_build_split_request(five_page_pdf, tmp_path):
    output = tmp_path / "chunks"
    request = build_request(
        "split",
        [five_page_pdf],
        _options(chunk_size=2, output=output),
    )
    assert request.func is split_pdf
    assert request.kwargs == {
        "input_path": Path(five_page_pdf),
        "output_dir": output,
        "chunk_size": 2,
        "password": None,
    }


def test_build_merge_request(three_page_pdf, five_page_pdf, tmp_path):
    output = tmp_path / "merged.pdf"
    request = build_request(
        "merge",
        [five_page_pdf, three_page_pdf],
        _options(output=output),
    )
    assert request.func is merge_pdfs
    assert request.kwargs == {
        "input_paths": [Path(five_page_pdf), Path(three_page_pdf)],
        "output_path": output,
        "passwords": [None, None],
    }


def test_build_rotate_request(three_page_pdf, tmp_path):
    output = tmp_path / "rotated.pdf"
    request = build_request(
        "rotate",
        [three_page_pdf],
        _options(degrees=270, page_range="1", output=output),
    )
    assert request.func is rotate_pages
    assert request.kwargs == {
        "input_path": Path(three_page_pdf),
        "output_path": output,
        "degrees": 270,
        "indices": [0],
        "password": None,
    }


def test_build_rotate_all_pages(five_page_pdf, tmp_path):
    request = build_request(
        "rotate",
        [five_page_pdf],
        _options(degrees=180, output=tmp_path / "rotated.pdf"),
    )
    assert request.kwargs["indices"] is None


def test_build_render_request(five_page_pdf, tmp_path):
    output = tmp_path / "images"
    request = build_request(
        "render",
        [five_page_pdf],
        _options(
            page_range="1,3-4",
            dpi=144,
            image_format="jpeg",
            quality=80,
            output=output,
        ),
    )
    assert request.func is render_pages
    assert request.kwargs == {
        "input_path": Path(five_page_pdf),
        "output_dir": output,
        "indices": [0, 2, 3],
        "dpi": 144,
        "image_format": "jpeg",
        "quality": 80,
        "password": None,
    }


@pytest.mark.parametrize(
    ("page_size", "expected"),
    [
        ("A4", "a4"),
        ("A5", "a5"),
        ("A3", "a3"),
        ("Letter", "letter"),
        ("Legal", "legal"),
        ("Original size", None),
    ],
)
def test_build_images_to_pdf_page_size_mapping(
    sample_images, tmp_path, page_size, expected
):
    request = build_request(
        "images_to_pdf",
        sample_images,
        _options(page_size=page_size, output=tmp_path / "out.pdf"),
    )
    assert request.kwargs["page_size"] == expected


def test_build_images_to_pdf_fit_and_dpi(sample_images, tmp_path):
    request = build_request(
        "images_to_pdf",
        sample_images,
        _options(
            fit="cover",
            dpi=200,
            quality=75,
            page_size="Letter",
            output=tmp_path / "out.pdf",
        ),
    )
    assert request.func is images_to_pdf
    assert request.kwargs == {
        "image_paths": [Path(path) for path in sample_images],
        "output_path": tmp_path / "out.pdf",
        "page_size": "letter",
        "fit": "cover",
        "dpi": 200,
        "quality": 75,
    }


def test_build_text_request(text_pdf, tmp_path):
    output = tmp_path / "out.txt"
    request = build_request(
        "text",
        [text_pdf],
        _options(page_range="2", output=output),
    )
    assert request.func is extract_text_to_file
    assert request.kwargs == {
        "input_path": Path(text_pdf),
        "output_path": output,
        "indices": [1],
        "password": None,
    }


def test_build_text_defaults_to_all_pages(text_pdf, tmp_path):
    request = build_request(
        "text",
        [text_pdf],
        _options(output=tmp_path / "out.txt"),
    )
    assert request.kwargs["indices"] is None


def test_build_markdown_request(rich_pdf, tmp_path):
    output = tmp_path / "out.md"
    request = build_request(
        "markdown",
        [rich_pdf],
        _options(page_range="2", output=output),
    )
    assert request.func is extract_markdown_to_file
    assert request.kwargs == {
        "input_path": Path(rich_pdf),
        "output_path": output,
        "indices": [1],
        "password": None,
    }


def test_build_markdown_defaults_to_all_pages(rich_pdf, tmp_path):
    request = build_request(
        "markdown",
        [rich_pdf],
        _options(output=tmp_path / "out.md"),
    )
    assert request.kwargs["indices"] is None


def test_build_compress_request_lossless(three_page_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    request = build_request(
        "compress",
        [three_page_pdf],
        _options(compression_mode="lossless", output=output),
    )
    assert request.func.__name__ == "compress_pdf"
    assert request.kwargs == {
        "input_path": Path(three_page_pdf),
        "output_path": output,
        "mode": "lossless",
        "dpi": 150,
        "quality": 90,
        "password": None,
    }


def test_build_compress_request_rasterize(three_page_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    request = build_request(
        "compress",
        [three_page_pdf],
        _options(
            compression_mode="rasterize",
            dpi=144,
            quality=70,
            output=output,
        ),
    )
    assert request.kwargs == {
        "input_path": Path(three_page_pdf),
        "output_path": output,
        "mode": "rasterize",
        "dpi": 144,
        "quality": 70,
        "password": None,
    }


def test_build_compress_invalid_mode_is_rejected(three_page_pdf, tmp_path):
    with pytest.raises(RequestError, match="compression mode"):
        build_request(
            "compress",
            [three_page_pdf],
            _options(compression_mode="zip", output=tmp_path / "out.pdf"),
        )


def test_build_compress_invalid_raster_settings_rejected(three_page_pdf, tmp_path):
    with pytest.raises(RequestError, match="DPI"):
        build_request(
            "compress",
            [three_page_pdf],
            _options(compression_mode="rasterize", dpi=0, output=tmp_path / "out.pdf"),
        )
    with pytest.raises(RequestError, match="Quality"):
        build_request(
            "compress",
            [three_page_pdf],
            _options(
                compression_mode="rasterize", quality=0, output=tmp_path / "out.pdf"
            ),
        )


def test_build_compress_requires_one_pdf(five_page_pdf, sample_images, tmp_path):
    with pytest.raises(RequestError, match="exactly one"):
        build_request(
            "compress",
            [five_page_pdf, sample_images[0]],
            _options(output=tmp_path / "out.pdf"),
        )


def test_build_office_request_uses_found_binary(monkeypatch, tmp_path, three_page_pdf):
    from tests.fake_office import make_fake_office

    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    source = tmp_path / "report.docx"
    source.write_bytes(b"%fake%")
    output = tmp_path / "out"
    request = build_request(
        "office",
        [source],
        _options(output=output),
    )
    assert request.func.__name__ == "office_to_pdf"
    assert request.kwargs["input_paths"] == [source]
    assert request.kwargs["output_dir"] == output
    assert request.kwargs["binary"] == fake


def test_build_office_request_unavailable_when_no_backend(
    monkeypatch, tmp_path, three_page_pdf
):
    monkeypatch.delenv("PDFPAD_LIBREOFFICE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "no-bin"))

    source = tmp_path / "report.docx"
    source.write_bytes(b"%fake%")
    with pytest.raises(RequestError, match="add-on"):
        build_request(
            "office",
            [source],
            _options(output=tmp_path / "out"),
        )


def test_build_office_rejects_non_office(tmp_path, monkeypatch):
    from tests.fake_office import make_fake_office

    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(make_fake_office(tmp_path / "bin")))
    not_office = tmp_path / "notes.txt"
    not_office.write_text("x")
    with pytest.raises(RequestError, match="Office document"):
        build_request(
            "office",
            [not_office],
            _options(output=tmp_path / "out"),
        )


# -- output handling -------------------------------------------------------


def test_output_without_suffix_gets_operation_suffix(three_page_pdf, tmp_path):
    request = build_request(
        "extract",
        [three_page_pdf],
        _options(output=tmp_path / "result"),
    )
    assert request.output.name == "result_extracted.pdf"


def test_text_output_without_suffix_gets_txt(text_pdf, tmp_path):
    request = build_request(
        "text",
        [text_pdf],
        _options(output=tmp_path / "notes"),
    )
    assert request.output.name == "notes.txt"


def test_markdown_output_without_suffix_gets_md(rich_pdf, tmp_path):
    request = build_request(
        "markdown",
        [rich_pdf],
        _options(output=tmp_path / "notes"),
    )
    assert request.output.name == "notes.md"


def test_default_output_used_when_none_given(three_page_pdf):
    request = build_request(
        "extract",
        [three_page_pdf],
        _options(),
    )
    assert request.output == Path(three_page_pdf).parent / "three_extracted.pdf"


def test_output_may_not_overwrite_input(three_page_pdf):
    with pytest.raises(RequestError, match="overwrite the input"):
        build_request(
            "extract",
            [three_page_pdf],
            _options(output=three_page_pdf),
        )


def test_output_may_not_overwrite_any_merge_input(three_page_pdf, five_page_pdf):
    with pytest.raises(RequestError, match="overwrite the input"):
        build_request(
            "merge",
            [three_page_pdf, five_page_pdf],
            _options(output=five_page_pdf),
        )


def test_directory_output_may_not_be_a_file(three_page_pdf, tmp_path):
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x")
    with pytest.raises(RequestError, match="not a folder"):
        build_request(
            "split",
            [three_page_pdf],
            _options(output=not_a_dir),
        )


# -- validation errors -----------------------------------------------------


def test_unknown_operation(tmp_path):
    with pytest.raises(RequestError, match="Unknown operation"):
        build_request("nope", [tmp_path / "a.pdf"], _options())


def test_requires_at_least_one_file(tmp_path):
    with pytest.raises(RequestError, match="at least one input file"):
        build_request("extract", [], _options(output=tmp_path / "out.pdf"))


def test_missing_input_file(tmp_path):
    with pytest.raises(RequestError, match="File not found"):
        build_request(
            "extract",
            [tmp_path / "missing.pdf"],
            _options(output=tmp_path / "out.pdf"),
        )


def test_extract_requires_exactly_one_pdf(three_page_pdf, five_page_pdf, tmp_path):
    with pytest.raises(RequestError, match="exactly one"):
        build_request(
            "extract",
            [three_page_pdf, five_page_pdf],
            _options(output=tmp_path / "out.pdf"),
        )


def test_extract_rejects_non_pdf_input(sample_images, tmp_path):
    with pytest.raises(RequestError, match="needs a PDF file"):
        build_request(
            "extract",
            [sample_images[0]],
            _options(output=tmp_path / "out.pdf"),
        )


def test_merge_requires_two_pdfs(three_page_pdf, tmp_path):
    with pytest.raises(RequestError, match="at least two"):
        build_request(
            "merge",
            [three_page_pdf],
            _options(output=tmp_path / "out.pdf"),
        )


def test_merge_rejects_non_pdf(three_page_pdf, sample_images, tmp_path):
    with pytest.raises(RequestError, match="Not a PDF file"):
        build_request(
            "merge",
            [three_page_pdf, sample_images[0]],
            _options(output=tmp_path / "out.pdf"),
        )


def test_images_to_pdf_rejects_non_image(three_page_pdf, tmp_path):
    with pytest.raises(RequestError, match="Not a supported image"):
        build_request(
            "images_to_pdf",
            [three_page_pdf],
            _options(output=tmp_path / "out.pdf"),
        )


@pytest.mark.parametrize(
    ("key", "overrides", "message"),
    [
        ("split", {"chunk_size": 0}, "Chunk size"),
        ("rotate", {"degrees": 45}, "multiple of 90"),
        ("render", {"dpi": 0}, "DPI"),
        ("render", {"quality": 0}, "Quality"),
        ("render", {"quality": 101}, "Quality"),
        ("render", {"image_format": "gif"}, "Image format"),
        ("images_to_pdf", {"page_size": "A9"}, "Unknown page size"),
        ("images_to_pdf", {"fit": "squish"}, "Unknown fit"),
        ("images_to_pdf", {"dpi": 0}, "DPI"),
        ("images_to_pdf", {"quality": 0}, "Quality"),
    ],
)
def test_invalid_options_are_rejected(
    three_page_pdf, sample_images, tmp_path, key, overrides, message
):
    files = sample_images if key == "images_to_pdf" else [three_page_pdf]
    output = (
        tmp_path / "out.pdf"
        if OPERATIONS_BY_KEY[key].output == "file"
        else tmp_path / "out"
    )
    with pytest.raises(RequestError, match=message):
        build_request(key, files, _options(output=output, **overrides))


def test_invalid_page_range_is_rejected(three_page_pdf, tmp_path):
    with pytest.raises(ValueError):
        build_request(
            "extract",
            [three_page_pdf],
            _options(page_range="9", output=tmp_path / "out.pdf"),
        )


# -- encrypted PDFs --------------------------------------------------------


def test_encrypted_pdf_requires_password(encrypted_pdf, tmp_path):
    with pytest.raises(EncryptedPdfError):
        build_request(
            "extract",
            [encrypted_pdf],
            _options(output=tmp_path / "out.pdf"),
        )


def test_encrypted_pdf_password_is_forwarded(encrypted_pdf, tmp_path):
    request = build_request(
        "extract",
        [encrypted_pdf],
        _options(output=tmp_path / "out.pdf"),
        passwords={Path(encrypted_pdf): "secret"},
    )
    assert request.kwargs["password"] == "secret"


def test_merge_forwards_per_file_passwords(
    encrypted_pdf, three_page_pdf, tmp_path
):
    request = build_request(
        "merge",
        [encrypted_pdf, three_page_pdf],
        _options(output=tmp_path / "merged.pdf"),
        passwords={Path(encrypted_pdf): "secret"},
    )
    assert request.kwargs["passwords"] == ["secret", None]


def test_wrong_merge_password_raises(encrypted_pdf, three_page_pdf, tmp_path):
    with pytest.raises(EncryptedPdfError):
        build_request(
            "merge",
            [encrypted_pdf, three_page_pdf],
            _options(output=tmp_path / "merged.pdf"),
            passwords={Path(encrypted_pdf): "wrong"},
        )


# -- execute the built requests (GUI mapping end to end) -------------------


def test_extract_request_executes(five_page_pdf, tmp_path):
    request = build_request(
        "extract",
        [five_page_pdf],
        _options(page_range="2-4", output=tmp_path / "out.pdf"),
    )
    result = request.func(**request.kwargs)
    assert result == tmp_path / "out.pdf"
    assert len(PdfReader(str(result)).pages) == 3


def test_split_request_executes(five_page_pdf, tmp_path):
    request = build_request(
        "split",
        [five_page_pdf],
        _options(chunk_size=2, output=tmp_path / "split"),
    )
    results = request.func(**request.kwargs)
    assert [len(PdfReader(str(path)).pages) for path in results] == [2, 2, 1]


def test_merge_request_executes(three_page_pdf, five_page_pdf, tmp_path):
    request = build_request(
        "merge",
        [three_page_pdf, five_page_pdf],
        _options(output=tmp_path / "merged.pdf"),
    )
    result = request.func(**request.kwargs)
    assert len(PdfReader(str(result)).pages) == 8


def test_rotate_request_executes(three_page_pdf, tmp_path):
    request = build_request(
        "rotate",
        [three_page_pdf],
        _options(degrees=90, page_range="1", output=tmp_path / "rotated.pdf"),
    )
    result = request.func(**request.kwargs)
    reader = PdfReader(str(result))
    assert [page.rotation for page in reader.pages] == [90, 0, 0]


def test_render_request_executes(three_page_pdf, tmp_path):
    request = build_request(
        "render",
        [three_page_pdf],
        _options(page_range="1", dpi=72, output=tmp_path / "images"),
    )
    results = request.func(**request.kwargs)
    assert [path.name for path in results] == ["three_page_1.png"]


def test_images_request_executes(tmp_path):
    first = make_image(tmp_path / "one.png", size=(100, 100), color="red")
    second = make_image(tmp_path / "two.png", size=(100, 100), color="blue")
    request = build_request(
        "images_to_pdf",
        [first, second],
        _options(page_size="A5", fit="contain", output=tmp_path / "out.pdf"),
    )
    result = request.func(**request.kwargs)
    assert len(PdfReader(str(result)).pages) == 2


def test_text_request_executes(text_pdf, tmp_path):
    request = build_request(
        "text",
        [text_pdf],
        _options(page_range="1,3", output=tmp_path / "out.txt"),
    )
    result = request.func(**request.kwargs)
    assert result.read_text(encoding="utf-8") == "Hello one\n\nHello three"


def test_markdown_request_executes(rich_pdf, tmp_path):
    request = build_request(
        "markdown",
        [rich_pdf],
        _options(page_range="2", output=tmp_path / "out.md"),
    )
    result = request.func(**request.kwargs)
    assert result.read_text(encoding="utf-8").startswith("# Page Two")
