"""Progress reporting and cooperative cancellation across the core operations."""

from __future__ import annotations

import pytest
from pypdf import PdfReader

from core.errors import OperationCancelled
from core.compress import compress_pdf
from core.images import images_to_pdf
from core.markdown import extract_markdown, extract_markdown_to_file
from core.pages import extract_pages, split_pdf
from core.render import render_pages
from core.text import extract_text_per_page, extract_text_to_file


def _cancel_after(successful_calls: int):
    """Return a cancel predicate that trips on call number *successful_calls + 1*."""
    calls = {"count": 0}

    def cancel() -> bool:
        calls["count"] += 1
        return calls["count"] > successful_calls

    return cancel


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[int, int]] = []

    def __call__(self, current: int, total: int) -> None:
        self.events.append((current, total))


# -- progress reporting ----------------------------------------------------


def test_extract_reports_every_page(three_page_pdf, tmp_path):
    recorder = _Recorder()
    extract_pages(
        three_page_pdf, [0, 1, 2], tmp_path / "out.pdf", progress=recorder
    )
    assert recorder.events == [(1, 3), (2, 3), (3, 3)]


def test_split_reports_every_chunk(five_page_pdf, tmp_path):
    recorder = _Recorder()
    split_pdf(five_page_pdf, tmp_path / "split", chunk_size=2, progress=recorder)
    assert recorder.events == [(1, 3), (2, 3), (3, 3)]


def test_render_reports_selected_pages(five_page_pdf, tmp_path):
    recorder = _Recorder()
    render_pages(
        five_page_pdf,
        tmp_path / "out",
        indices=[4, 0],
        dpi=72,
        progress=recorder,
    )
    assert recorder.events == [(1, 2), (2, 2)]


def test_images_to_pdf_reports_every_image(sample_images, tmp_path):
    recorder = _Recorder()
    images_to_pdf(sample_images, tmp_path / "out.pdf", progress=recorder)
    assert recorder.events == [(1, 2), (2, 2)]


def test_text_reports_every_page(text_pdf):
    recorder = _Recorder()
    extract_text_per_page(text_pdf, indices=[2, 0], progress=recorder)
    assert recorder.events == [(1, 2), (2, 2)]


def test_markdown_reports_every_page(rich_pdf):
    recorder = _Recorder()
    extract_markdown(rich_pdf, progress=recorder)
    assert recorder.events == [(1, 2), (2, 2)]


def test_progress_is_optional(three_page_pdf, tmp_path):
    # No callback must be a valid call; the operation still succeeds.
    output = extract_pages(three_page_pdf, [0], tmp_path / "out.pdf")
    assert output.is_file()


# -- cancellation ----------------------------------------------------------


def test_extract_cancel_leaves_no_output(three_page_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    with pytest.raises(OperationCancelled):
        extract_pages(
            three_page_pdf,
            [0, 1, 2],
            output,
            cancel=_cancel_after(1),
        )
    assert not output.exists()


def test_extract_cancel_does_not_replace_existing_output(three_page_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    output.write_bytes(b"original")
    with pytest.raises(OperationCancelled):
        extract_pages(
            three_page_pdf,
            [0, 1, 2],
            output,
            cancel=_cancel_after(1),
        )
    assert output.read_bytes() == b"original"


def test_split_cancel_removes_partial_files(five_page_pdf, tmp_path):
    destination = tmp_path / "split"
    with pytest.raises(OperationCancelled):
        split_pdf(
            five_page_pdf,
            destination,
            chunk_size=1,
            cancel=_cancel_after(2),
        )
    assert list(destination.glob("*.pdf")) == []


def test_split_cancel_removes_only_files_created_by_the_run(
    five_page_pdf, tmp_path
):
    destination = tmp_path / "split"
    destination.mkdir()
    unrelated = destination / "keep.pdf"
    unrelated.write_bytes(b"keep me")

    with pytest.raises(OperationCancelled):
        split_pdf(
            five_page_pdf,
            destination,
            chunk_size=1,
            cancel=_cancel_after(2),
        )

    # Only files created by this run are removed; other files survive.
    assert unrelated.read_bytes() == b"keep me"
    assert [path.name for path in destination.iterdir()] == [unrelated.name]


def test_render_cancel_removes_partial_files(five_page_pdf, tmp_path):
    destination = tmp_path / "images"
    with pytest.raises(OperationCancelled):
        render_pages(
            five_page_pdf,
            destination,
            dpi=72,
            cancel=_cancel_after(2),
        )
    assert list(destination.glob("*")) == []


def test_images_to_pdf_cancel_leaves_no_output(sample_images, tmp_path):
    output = tmp_path / "out.pdf"
    with pytest.raises(OperationCancelled):
        images_to_pdf(sample_images, output, cancel=_cancel_after(1))
    assert not output.exists()


def test_text_cancel_stops_extraction(text_pdf):
    with pytest.raises(OperationCancelled):
        extract_text_per_page(text_pdf, cancel=_cancel_after(1))


def test_text_to_file_cancel_leaves_no_output(text_pdf, tmp_path):
    output = tmp_path / "out.txt"
    with pytest.raises(OperationCancelled):
        extract_text_to_file(
            text_pdf, output, cancel=_cancel_after(1)
        )
    assert not output.exists()


def test_markdown_cancel_stops_extraction(rich_pdf):
    with pytest.raises(OperationCancelled):
        extract_markdown(rich_pdf, cancel=_cancel_after(1))


def test_markdown_to_file_cancel_leaves_no_output(rich_pdf, tmp_path):
    output = tmp_path / "out.md"
    with pytest.raises(OperationCancelled):
        extract_markdown_to_file(rich_pdf, output, cancel=_cancel_after(1))
    assert not output.exists()


def test_cancel_that_never_trips_still_finishes(three_page_pdf, tmp_path):
    output = extract_pages(
        three_page_pdf,
        [0, 1, 2],
        tmp_path / "out.pdf",
        cancel=lambda: False,
    )
    assert len(PdfReader(str(output)).pages) == 3


def test_lossless_compress_reports_progress(text_pdf, tmp_path):
    recorder = _Recorder()
    compress_pdf(text_pdf, tmp_path / "out.pdf", progress=recorder)

    assert recorder.events[0] == (1, 100)
    assert recorder.events[-1] == (100, 100)
    assert all(1 <= current <= 100 for current, _total in recorder.events)


def test_rasterize_compress_reports_render_and_assembly(three_page_pdf, tmp_path):
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


def test_lossless_compress_cancel_leaves_no_output(text_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    with pytest.raises(OperationCancelled):
        compress_pdf(text_pdf, output, cancel=_cancel_after(0))
    assert not output.exists()


def test_rasterize_compress_cancel_preserves_existing_output(three_page_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    output.write_bytes(b"original")
    with pytest.raises(OperationCancelled):
        compress_pdf(
            three_page_pdf,
            output,
            mode="rasterize",
            dpi=72,
            cancel=_cancel_after(1),
        )
    assert output.read_bytes() == b"original"
