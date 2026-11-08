from __future__ import annotations

import pytest
from pypdf import PdfReader

from core.errors import EncryptedPdfError, PdfOperationError, RangeSpecError, UnsupportedFileError
from core.pages import (
    extract_pages,
    merge_pdfs,
    page_count,
    rotate_pages,
    split_pdf,
)


def _widths(path):
    reader = PdfReader(str(path))
    return [round(float(page.mediabox.width)) for page in reader.pages]


def _rotations(path):
    reader = PdfReader(str(path))
    return [page.rotation for page in reader.pages]


def test_page_count(five_page_pdf):
    assert page_count(five_page_pdf) == 5


def test_extract_preserves_selection_order(five_page_pdf, tmp_path):
    output = extract_pages(five_page_pdf, [2, 0, 4], tmp_path / "extract.pdf")
    assert _widths(output) == [320, 300, 340]


def test_extract_keeps_duplicate_indices(three_page_pdf, tmp_path):
    output = extract_pages(three_page_pdf, [0, 0], tmp_path / "dupes.pdf")
    assert _widths(output) == [300, 300]


def test_extract_creates_parent_directories(three_page_pdf, tmp_path):
    output = extract_pages(
        three_page_pdf, [1], tmp_path / "nested" / "deeper" / "one.pdf"
    )
    assert output.is_file()


@pytest.mark.parametrize("indices", [[], [3], [-1]])
def test_extract_rejects_bad_indices(three_page_pdf, tmp_path, indices):
    with pytest.raises(RangeSpecError):
        extract_pages(three_page_pdf, indices, tmp_path / "bad.pdf")


def test_extract_rejects_non_integer_indices(three_page_pdf, tmp_path):
    with pytest.raises(TypeError):
        extract_pages(three_page_pdf, ["0"], tmp_path / "bad.pdf")


def test_merge_preserves_input_order(three_page_pdf, five_page_pdf, tmp_path):
    output = merge_pdfs([five_page_pdf, three_page_pdf], tmp_path / "merged.pdf")
    assert _widths(output) == [300, 310, 320, 330, 340, 300, 310, 320]


def test_merge_requires_inputs(tmp_path):
    with pytest.raises(PdfOperationError):
        merge_pdfs([], tmp_path / "empty.pdf")


def test_merge_password_sequence_length_mismatch(three_page_pdf, tmp_path):
    with pytest.raises(ValueError):
        merge_pdfs([three_page_pdf], tmp_path / "x.pdf", passwords=["a", "b"])


def test_split_every_page(five_page_pdf, tmp_path):
    outputs = split_pdf(five_page_pdf, tmp_path / "split", chunk_size=1)
    assert [path.name for path in outputs] == [
        "five_pages_1-1.pdf",
        "five_pages_2-2.pdf",
        "five_pages_3-3.pdf",
        "five_pages_4-4.pdf",
        "five_pages_5-5.pdf",
    ]
    assert [_widths(path) for path in outputs] == [[300], [310], [320], [330], [340]]


def test_split_in_chunks(five_page_pdf, tmp_path):
    outputs = split_pdf(five_page_pdf, tmp_path / "split", chunk_size=2)
    assert [path.name for path in outputs] == [
        "five_pages_1-2.pdf",
        "five_pages_3-4.pdf",
        "five_pages_5-5.pdf",
    ]
    assert [len(PdfReader(str(path)).pages) for path in outputs] == [2, 2, 1]


def test_split_rejects_bad_chunk_size(five_page_pdf, tmp_path):
    with pytest.raises(ValueError):
        split_pdf(five_page_pdf, tmp_path / "split", chunk_size=0)
    with pytest.raises(TypeError):
        split_pdf(five_page_pdf, tmp_path / "split", chunk_size=1.5)


def test_rotate_selected_pages(three_page_pdf, tmp_path):
    output = rotate_pages(three_page_pdf, tmp_path / "rotated.pdf", 90, indices=[0])
    assert _rotations(output) == [90, 0, 0]


def test_rotate_all_pages(three_page_pdf, tmp_path):
    output = rotate_pages(three_page_pdf, tmp_path / "rotated.pdf", 180)
    assert _rotations(output) == [180, 180, 180]


def test_rotate_is_cumulative(three_page_pdf, tmp_path):
    first = rotate_pages(three_page_pdf, tmp_path / "once.pdf", 90, indices=[0])
    second = rotate_pages(first, tmp_path / "twice.pdf", 90, indices=[0])
    assert _rotations(second) == [180, 0, 0]


def test_rotate_rejects_non_multiple_of_90(three_page_pdf, tmp_path):
    with pytest.raises(ValueError):
        rotate_pages(three_page_pdf, tmp_path / "bad.pdf", 45)


def test_encrypted_pdf_requires_password(encrypted_pdf):
    with pytest.raises(EncryptedPdfError):
        page_count(encrypted_pdf)
    with pytest.raises(EncryptedPdfError):
        page_count(encrypted_pdf, password="wrong")
    assert page_count(encrypted_pdf, password="secret") == 2


def test_extract_from_encrypted_pdf(encrypted_pdf, tmp_path):
    output = extract_pages(
        encrypted_pdf, [1], tmp_path / "one.pdf", password="secret"
    )
    assert len(PdfReader(str(output)).pages) == 1


def test_merge_with_passwords(encrypted_pdf, three_page_pdf, tmp_path):
    output = merge_pdfs(
        [encrypted_pdf, three_page_pdf],
        tmp_path / "merged.pdf",
        passwords=["secret", None],
    )
    assert len(PdfReader(str(output)).pages) == 5


def test_missing_file(tmp_path):
    with pytest.raises(UnsupportedFileError):
        page_count(tmp_path / "does-not-exist.pdf")


def test_non_pdf_input(tmp_path):
    bogus = tmp_path / "not.pdf"
    bogus.write_text("this is not a PDF")
    with pytest.raises(PdfOperationError):
        page_count(bogus)


def test_rotating_encrypted_pdf(encrypted_pdf, tmp_path):
    output = rotate_pages(
        encrypted_pdf, tmp_path / "rotated.pdf", 90, password="secret"
    )
    assert _rotations(output) == [90, 90]


def test_merge_rejects_wrong_password(encrypted_pdf, tmp_path):
    with pytest.raises(EncryptedPdfError):
        merge_pdfs(
            [encrypted_pdf], tmp_path / "x.pdf", passwords=["nope"]
        )
