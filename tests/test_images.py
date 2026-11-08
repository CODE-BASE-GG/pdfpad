from __future__ import annotations

import pytest
from pypdf import PdfReader

from core.errors import PdfOperationError, UnsupportedFileError
from core.images import images_to_pdf
from tests.pdf_fixtures import make_image


def _page_sizes(path):
    reader = PdfReader(str(path))
    return [
        (round(float(page.mediabox.width), 1), round(float(page.mediabox.height), 1))
        for page in reader.pages
    ]


def test_images_to_pdf_defaults_to_a4(sample_images, tmp_path):
    output = images_to_pdf(sample_images, tmp_path / "out.pdf")
    sizes = _page_sizes(output)
    assert len(sizes) == 2
    for width, height in sizes:
        assert width == pytest.approx(595.3, abs=0.2)
        assert height == pytest.approx(841.9, abs=0.2)


def test_images_to_pdf_preserves_order_and_original_size(sample_images, tmp_path):
    output = images_to_pdf(
        sample_images, tmp_path / "out.pdf", page_size=None, dpi=72
    )
    assert _page_sizes(output) == [(200.0, 100.0), (250.0, 100.0)]


def test_images_to_pdf_custom_page_size(sample_images, tmp_path):
    output = images_to_pdf(
        sample_images, tmp_path / "out.pdf", page_size=(400, 600), dpi=72
    )
    assert _page_sizes(output) == [(400.0, 600.0), (400.0, 600.0)]


@pytest.mark.parametrize("fit", ["contain", "cover", "stretch"])
def test_images_to_pdf_fit_modes(sample_images, tmp_path, fit):
    output = images_to_pdf(
        sample_images, tmp_path / f"{fit}.pdf", fit=fit, page_size="letter"
    )
    assert _page_sizes(output) == [(612.0, 792.0), (612.0, 792.0)]


def test_images_to_pdf_handles_transparency(tmp_path):
    transparent = make_image(
        tmp_path / "alpha.png", size=(100, 100), color=(255, 0, 0, 0), mode="RGBA"
    )
    output = images_to_pdf([transparent], tmp_path / "out.pdf", page_size="a5")
    assert len(PdfReader(str(output)).pages) == 1


def test_images_to_pdf_requires_images(tmp_path):
    with pytest.raises(PdfOperationError):
        images_to_pdf([], tmp_path / "out.pdf")


def test_images_to_pdf_missing_file(tmp_path):
    with pytest.raises(UnsupportedFileError):
        images_to_pdf([tmp_path / "missing.png"], tmp_path / "out.pdf")


def test_images_to_pdf_rejects_non_image(tmp_path):
    bogus = tmp_path / "not-an-image.txt"
    bogus.write_text("hello")
    with pytest.raises(UnsupportedFileError):
        images_to_pdf([bogus], tmp_path / "out.pdf")


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"page_size": "a9"}, ValueError),
        ({"page_size": (0, 100)}, ValueError),
        ({"fit": "squish"}, ValueError),
        ({"dpi": 0}, ValueError),
        ({"quality": 0}, ValueError),
        ({"background": "pink"}, ValueError),
        ({"background": (0, 0, 300)}, ValueError),
    ],
)
def test_images_to_pdf_rejects_bad_options(sample_images, tmp_path, kwargs, error):
    with pytest.raises(error):
        images_to_pdf(sample_images, tmp_path / "out.pdf", **kwargs)


def test_images_to_pdf_accepts_background_tuple(sample_images, tmp_path):
    output = images_to_pdf(
        sample_images,
        tmp_path / "out.pdf",
        background=(10, 20, 30),
        page_size="a5",
    )
    assert output.is_file()
    assert len(PdfReader(str(output)).pages) == 2
