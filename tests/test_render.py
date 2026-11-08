from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from core.errors import EncryptedPdfError, RangeSpecError
from core.render import render_page_image, render_pages, render_thumbnail


def _open(path):
    image = Image.open(path)
    image.load()
    return image


def test_render_all_pages_as_png(three_page_pdf, tmp_path):
    outputs = render_pages(three_page_pdf, tmp_path / "out", dpi=72)
    assert [path.name for path in outputs] == [
        "three_page_1.png",
        "three_page_2.png",
        "three_page_3.png",
    ]
    assert [_open(path).size for path in outputs] == [(300, 400), (310, 400), (320, 400)]


def test_render_subset_in_selection_order(five_page_pdf, tmp_path):
    outputs = render_pages(five_page_pdf, tmp_path / "out", indices=[2, 0], dpi=72)
    assert [path.name for path in outputs] == ["five_page_3.png", "five_page_1.png"]
    assert [_open(path).size for path in outputs] == [(320, 400), (300, 400)]


def test_render_respects_dpi(three_page_pdf, tmp_path):
    outputs = render_pages(three_page_pdf, tmp_path / "out", indices=[0], dpi=144)
    assert _open(outputs[0]).size == (600, 800)


def test_render_jpeg(three_page_pdf, tmp_path):
    outputs = render_pages(
        three_page_pdf,
        tmp_path / "out",
        indices=[0],
        dpi=72,
        image_format="jpeg",
        quality=80,
    )
    image = _open(outputs[0])
    assert outputs[0].suffix == ".jpg"
    assert image.format == "JPEG"
    assert image.mode == "RGB"


def test_render_custom_prefix(three_page_pdf, tmp_path):
    outputs = render_pages(
        three_page_pdf, tmp_path / "out", indices=[0], prefix="preview"
    )
    assert outputs[0].name == "preview_page_1.png"


def test_render_page_image(three_page_pdf):
    image = render_page_image(three_page_pdf, 1, dpi=72)
    assert image.size == (310, 400)


def test_render_thumbnail_limits_longest_side(three_page_pdf):
    image = render_thumbnail(three_page_pdf, 0, max_size=100)
    assert max(image.size) == 100
    assert image.size == (75, 100)


def test_render_page_index_out_of_range(three_page_pdf):
    with pytest.raises(RangeSpecError):
        render_page_image(three_page_pdf, 3)
    with pytest.raises(RangeSpecError):
        render_thumbnail(three_page_pdf, -1)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"image_format": "gif"}, ValueError),
        ({"dpi": 0}, ValueError),
        ({"quality": 0}, ValueError),
        ({"quality": 101}, ValueError),
    ],
)
def test_render_rejects_bad_options(three_page_pdf, tmp_path, kwargs, error):
    with pytest.raises(error):
        render_pages(three_page_pdf, tmp_path / "out", indices=[0], **kwargs)


def test_render_rejects_bad_indices(three_page_pdf, tmp_path):
    with pytest.raises(RangeSpecError):
        render_pages(three_page_pdf, tmp_path / "out", indices=[5])


def test_render_encrypted_pdf(encrypted_pdf, tmp_path):
    with pytest.raises(EncryptedPdfError):
        render_pages(encrypted_pdf, tmp_path / "out")
    with pytest.raises(EncryptedPdfError):
        render_pages(encrypted_pdf, tmp_path / "out", password="wrong")

    outputs = render_pages(
        encrypted_pdf, tmp_path / "out", password="secret", dpi=72
    )
    assert len(outputs) == 2


def test_render_creates_output_directory(three_page_pdf, tmp_path):
    outputs = render_pages(
        three_page_pdf, tmp_path / "a" / "b" / "c", indices=[0], dpi=72
    )
    assert outputs[0].is_file()


def test_concurrent_rendering_is_serialised(three_page_pdf):
    # PDFium is not thread-safe. Preview and operation threads can overlap in
    # the GUI, so the core must serialise access without corrupting results.
    expected = [(30, 40), (31, 40), (32, 40)]

    def render(index):
        image = render_thumbnail(three_page_pdf, index % 3, max_size=40)
        try:
            return image.size
        finally:
            image.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(render, range(9)))

    assert results == expected * 3
