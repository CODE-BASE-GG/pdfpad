"""Tests for lossless and rasterizing PDF compression."""

from __future__ import annotations

import pytest
from pypdf import PdfReader

from core.compress import COMPRESSION_MODES, compress_pdf
from core.errors import (
    EncryptedPdfError,
    OperationCancelled,
    PdfOperationError,
    UnsupportedFileError,
)
from core.text import extract_text


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[int, int]] = []

    def __call__(self, current: int, total: int) -> None:
        self.events.append((current, total))


def _cancel_after(successful_calls: int):
    calls = {"count": 0}

    def cancel() -> bool:
        calls["count"] += 1
        return calls["count"] > successful_calls

    return cancel


def test_compression_modes_are_documented():
    assert COMPRESSION_MODES == {"lossless", "rasterize"}


# -- lossless --------------------------------------------------------------


def test_lossless_keeps_pages_and_text(text_pdf, tmp_path):
    output = tmp_path / "compressed.pdf"
    result = compress_pdf(text_pdf, output, mode="lossless")

    assert result == output
    assert output.is_file()
    assert len(PdfReader(str(output)).pages) == 3
    assert extract_text(output) == "Hello one\n\nHello two\n\nHello three"


def test_lossless_is_the_default_mode(text_pdf, tmp_path):
    output = tmp_path / "compressed.pdf"
    compress_pdf(text_pdf, output)
    assert extract_text(output).startswith("Hello one")


def test_lossless_reports_bounded_progress(text_pdf, tmp_path):
    recorder = _Recorder()
    compress_pdf(text_pdf, tmp_path / "out.pdf", progress=recorder)

    assert recorder.events
    assert recorder.events[0] == (1, 100)
    assert recorder.events[-1] == (100, 100)
    assert all(1 <= current <= 100 for current, _total in recorder.events)


def test_lossless_ignores_raster_settings(text_pdf, tmp_path):
    # dpi/quality are only meaningful for rasterize; they must not be rejected.
    output = compress_pdf(
        text_pdf,
        tmp_path / "out.pdf",
        mode="lossless",
        dpi=0,
        quality=0,
    )
    assert output.is_file()


def test_lossless_replaces_an_existing_output(text_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    output.write_bytes(b"old")
    compress_pdf(text_pdf, output)
    assert len(PdfReader(str(output)).pages) == 3


def test_lossless_cancel_before_start_leaves_no_output(text_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    with pytest.raises(OperationCancelled):
        compress_pdf(text_pdf, output, cancel=_cancel_after(0))
    assert not output.exists()


def test_lossless_cancel_after_writing_preserves_existing_output(text_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    output.write_bytes(b"original")
    with pytest.raises(OperationCancelled):
        compress_pdf(text_pdf, output, cancel=_cancel_after(1))
    assert output.read_bytes() == b"original"


# -- rasterize -------------------------------------------------------------


def test_rasterize_rebuilds_every_page(three_page_pdf, tmp_path):
    output = tmp_path / "raster.pdf"
    result = compress_pdf(
        three_page_pdf,
        output,
        mode="rasterize",
        dpi=72,
        quality=70,
    )

    assert result == output
    assert len(PdfReader(str(output)).pages) == 3


def test_rasterize_removes_the_text_layer(text_pdf, tmp_path):
    output = tmp_path / "raster.pdf"
    compress_pdf(text_pdf, output, mode="rasterize", dpi=72, quality=70)

    # The page is now an image, so the extracted text is empty.
    assert extract_text(output).strip() == ""


def test_rasterize_keeps_page_dimensions(three_page_pdf, tmp_path):
    output = tmp_path / "raster.pdf"
    compress_pdf(three_page_pdf, output, mode="rasterize", dpi=72, quality=70)

    page = PdfReader(str(output)).pages[0]
    assert float(page.mediabox.width) == pytest.approx(300.0, abs=1.0)
    assert float(page.mediabox.height) == pytest.approx(400.0, abs=1.0)


def test_rasterize_reports_render_and_assembly(three_page_pdf, tmp_path):
    recorder = _Recorder()
    compress_pdf(
        three_page_pdf,
        tmp_path / "out.pdf",
        mode="rasterize",
        dpi=72,
        progress=recorder,
    )
    assert recorder.events == [
        (1, 6),
        (2, 6),
        (3, 6),
        (4, 6),
        (5, 6),
        (6, 6),
    ]


def test_rasterize_cancel_leaves_no_output(three_page_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    with pytest.raises(OperationCancelled):
        compress_pdf(
            three_page_pdf,
            output,
            mode="rasterize",
            dpi=72,
            cancel=_cancel_after(1),
        )
    assert not output.exists()


def test_rasterize_cancel_preserves_existing_output(three_page_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    output.write_bytes(b"original")
    with pytest.raises(OperationCancelled):
        compress_pdf(
            three_page_pdf,
            output,
            mode="rasterize",
            dpi=72,
            cancel=_cancel_after(2),
        )
    assert output.read_bytes() == b"original"


# -- validation ------------------------------------------------------------


def test_unknown_mode_is_rejected(three_page_pdf, tmp_path):
    with pytest.raises(ValueError, match="Unknown compression mode"):
        compress_pdf(three_page_pdf, tmp_path / "out.pdf", mode="zip")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"dpi": 0}, "dpi"),
        ({"dpi": -1}, "dpi"),
        ({"quality": 0}, "quality"),
        ({"quality": 101}, "quality"),
    ],
)
def test_invalid_raster_settings_are_rejected(
    three_page_pdf, tmp_path, overrides, message
):
    with pytest.raises(ValueError, match=message):
        compress_pdf(
            three_page_pdf,
            tmp_path / "out.pdf",
            mode="rasterize",
            **overrides,
        )


def test_missing_input_is_rejected(tmp_path):
    with pytest.raises(UnsupportedFileError, match="File not found"):
        compress_pdf(tmp_path / "missing.pdf", tmp_path / "out.pdf")


def test_corrupt_input_is_rejected(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a PDF")
    with pytest.raises(PdfOperationError):
        compress_pdf(broken, tmp_path / "out.pdf")


def test_output_may_not_overwrite_the_input(text_pdf):
    with pytest.raises(PdfOperationError, match="overwrite the input"):
        compress_pdf(text_pdf, text_pdf)


# -- encrypted PDFs --------------------------------------------------------


def test_encrypted_pdf_requires_a_password(encrypted_pdf, tmp_path):
    with pytest.raises(EncryptedPdfError, match="password-protected"):
        compress_pdf(encrypted_pdf, tmp_path / "out.pdf")


def test_encrypted_pdf_rejects_a_wrong_password(encrypted_pdf, tmp_path):
    with pytest.raises(EncryptedPdfError, match="Incorrect password"):
        compress_pdf(encrypted_pdf, tmp_path / "out.pdf", password="wrong")


def test_encrypted_pdf_accepts_the_right_password(encrypted_pdf, tmp_path):
    output = compress_pdf(
        encrypted_pdf, tmp_path / "out.pdf", password="secret"
    )
    assert len(PdfReader(str(output)).pages) == 2


def test_encrypted_rasterize_accepts_the_right_password(encrypted_pdf, tmp_path):
    output = compress_pdf(
        encrypted_pdf,
        tmp_path / "out.pdf",
        mode="rasterize",
        dpi=72,
        password="secret",
    )
    assert len(PdfReader(str(output)).pages) == 2
