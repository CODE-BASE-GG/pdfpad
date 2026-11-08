"""Tests for the best-effort PDF to Markdown conversion."""

from __future__ import annotations

import pytest

from core.errors import (
    EncryptedPdfError,
    OperationCancelled,
    RangeSpecError,
    UnsupportedFileError,
)
from core.markdown import extract_markdown, extract_markdown_to_file


def _cancel_after(successful_calls: int):
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


# -- structure -------------------------------------------------------------


def test_headings_and_paragraphs(rich_pdf):
    markdown = extract_markdown(rich_pdf)

    assert markdown.startswith("# Document Title\n\n## Introduction\n\n")
    assert (
        "This is the first line of a paragraph that continues onto the "
        "next line."
    ) in markdown
    assert "Second paragraph starts here." in markdown


def test_bullet_and_numbered_lists(rich_pdf):
    markdown = extract_markdown(rich_pdf)

    assert "- First bullet\n- Second bullet" in markdown
    assert "1. First step\n2. Second step" in markdown
    # The two list kinds are kept in separate blocks.
    assert "- Second bullet\n\n1. First step" in markdown


def test_simple_table(rich_pdf):
    markdown = extract_markdown(rich_pdf)

    table = (
        "| Name | Age | City |\n"
        "| --- | --- | --- |\n"
        "| Alice | 30 | Paris |\n"
        "| Bob | 25 | Berlin |"
    )
    assert table in markdown


def test_pages_are_separated_by_a_blank_line(rich_pdf):
    markdown = extract_markdown(rich_pdf)

    assert "| Bob | 25 | Berlin |\n\n# Page Two" in markdown
    assert markdown.endswith("# Page Two\n\nAnother paragraph.")


def test_page_selection_keeps_requested_order(rich_pdf):
    markdown = extract_markdown(rich_pdf, indices=[1, 0])

    assert markdown.startswith("# Page Two\n\nAnother paragraph.")
    assert "# Document Title" in markdown
    assert markdown.index("# Page Two") < markdown.index("# Document Title")


def test_duplicate_page_indices_are_repeated(rich_pdf):
    markdown = extract_markdown(rich_pdf, indices=[0, 0, 1])

    assert markdown.count("# Document Title") == 2
    assert markdown.count("# Page Two") == 1


def test_plain_text_pdf_becomes_paragraphs(text_pdf):
    assert extract_markdown(text_pdf) == "Hello one\n\nHello two\n\nHello three"


def test_blank_pages_produce_no_markdown(three_page_pdf):
    assert extract_markdown(three_page_pdf) == ""


def test_single_selected_page_is_formatted(rich_pdf):
    # Selecting only the second page should not include the first page.
    assert extract_markdown(rich_pdf, indices=[1]).startswith("# Page Two")


# -- errors ----------------------------------------------------------------


def test_bad_indices_are_rejected(rich_pdf):
    with pytest.raises(RangeSpecError):
        extract_markdown(rich_pdf, indices=[2])


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(UnsupportedFileError):
        extract_markdown(tmp_path / "missing.pdf")


def test_encrypted_pdf_requires_password(encrypted_pdf):
    with pytest.raises(EncryptedPdfError):
        extract_markdown(encrypted_pdf)
    with pytest.raises(EncryptedPdfError):
        extract_markdown(encrypted_pdf, password="wrong")
    assert extract_markdown(encrypted_pdf, password="secret") == ""


# -- output file -----------------------------------------------------------


def test_markdown_to_file_writes_utf8(rich_pdf, tmp_path):
    output = extract_markdown_to_file(rich_pdf, tmp_path / "out.md")

    assert output == tmp_path / "out.md"
    assert "# Document Title" in output.read_text(encoding="utf-8")


def test_markdown_to_file_replaces_existing_output(rich_pdf, tmp_path):
    output = tmp_path / "out.md"
    output.write_text("old", encoding="utf-8")

    extract_markdown_to_file(rich_pdf, output, indices=[1])

    assert output.read_text(encoding="utf-8").startswith("# Page Two")


# -- progress and cancellation --------------------------------------------


def test_progress_reports_every_page(rich_pdf):
    recorder = _Recorder()
    extract_markdown(rich_pdf, progress=recorder)

    assert recorder.events == [(1, 2), (2, 2)]


def test_progress_follows_selected_pages(rich_pdf):
    recorder = _Recorder()
    extract_markdown(rich_pdf, indices=[1], progress=recorder)

    assert recorder.events == [(1, 1)]


def test_cancel_before_first_page_leaves_no_output(rich_pdf, tmp_path):
    output = tmp_path / "out.md"
    with pytest.raises(OperationCancelled):
        extract_markdown_to_file(rich_pdf, output, cancel=_cancel_after(0))
    assert not output.exists()


def test_cancel_preserves_existing_output(rich_pdf, tmp_path):
    output = tmp_path / "out.md"
    output.write_text("original", encoding="utf-8")

    with pytest.raises(OperationCancelled):
        extract_markdown_to_file(rich_pdf, output, cancel=_cancel_after(1))

    assert output.read_text(encoding="utf-8") == "original"


def test_cancel_that_never_trips_still_finishes(rich_pdf):
    assert extract_markdown(rich_pdf, cancel=lambda: False).startswith(
        "# Document Title"
    )
