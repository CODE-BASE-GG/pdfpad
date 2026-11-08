from __future__ import annotations

import pytest

from core.errors import EncryptedPdfError, RangeSpecError, UnsupportedFileError
from core.text import extract_text, extract_text_per_page, extract_text_to_file


def test_extract_text_per_page(text_pdf):
    assert extract_text_per_page(text_pdf) == ["Hello one", "Hello two", "Hello three"]


def test_extract_text_joins_pages(text_pdf):
    assert extract_text(text_pdf) == "Hello one\n\nHello two\n\nHello three"


def test_extract_text_subset_in_order(text_pdf):
    assert extract_text_per_page(text_pdf, indices=[2, 0]) == ["Hello three", "Hello one"]


def test_extract_text_to_file(text_pdf, tmp_path):
    output = extract_text_to_file(text_pdf, tmp_path / "text.txt", indices=[1])
    assert output.read_text(encoding="utf-8") == "Hello two"


def test_extract_text_from_blank_pages(three_page_pdf):
    assert extract_text_per_page(three_page_pdf) == ["", "", ""]


def test_extract_text_bad_indices(text_pdf):
    with pytest.raises(RangeSpecError):
        extract_text_per_page(text_pdf, indices=[3])


def test_extract_text_encrypted(encrypted_pdf, tmp_path):
    with pytest.raises(EncryptedPdfError):
        extract_text(encrypted_pdf)
    with pytest.raises(EncryptedPdfError):
        extract_text(encrypted_pdf, password="wrong")
    assert extract_text(encrypted_pdf, password="secret") == "\n\n"


def test_extract_text_missing_file(tmp_path):
    with pytest.raises(UnsupportedFileError):
        extract_text(tmp_path / "missing.pdf")
