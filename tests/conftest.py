from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# The GUI tests must run without a display server. Set this before any test
# module imports PySide6. Keep settings and logs out of the real home directory.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TEST_HOME = Path(tempfile.mkdtemp(prefix="pdfpad-test-"))
os.environ.setdefault("XDG_CONFIG_HOME", str(_TEST_HOME / "config"))
os.environ.setdefault("XDG_STATE_HOME", str(_TEST_HOME / "state"))

from tests.pdf_fixtures import (  # noqa: E402
    make_encrypted_pdf,
    make_image,
    make_pdf,
    make_rich_pdf,
    make_text_pdf,
)


@pytest.fixture
def three_page_pdf(tmp_path):
    return make_pdf(
        tmp_path / "three.pdf",
        page_sizes=[(300.0, 400.0), (310.0, 400.0), (320.0, 400.0)],
    )


@pytest.fixture
def five_page_pdf(tmp_path):
    return make_pdf(
        tmp_path / "five.pdf",
        page_sizes=[(300.0 + index * 10, 400.0) for index in range(5)],
    )


@pytest.fixture
def text_pdf(tmp_path):
    return make_text_pdf(
        tmp_path / "text.pdf",
        ["Hello one", "Hello two", "Hello three"],
    )


@pytest.fixture
def rich_pdf(tmp_path):
    return make_rich_pdf(
        tmp_path / "rich.pdf",
        [
            [
                ("Document Title", 72, 720, 24, True),
                ("Introduction", 72, 680, 16, True),
                ("This is the first line of a paragraph that", 72, 650, 11, False),
                ("continues onto the next line.", 72, 635, 11, False),
                ("Second paragraph starts here.", 72, 600, 11, False),
                ("- First bullet", 80, 570, 11, False),
                ("- Second bullet", 80, 555, 11, False),
                ("1. First step", 80, 530, 11, False),
                ("2. Second step", 80, 515, 11, False),
                ("Name", 72, 480, 11, True),
                ("Age", 250, 480, 11, True),
                ("City", 400, 480, 11, True),
                ("Alice", 72, 465, 11, False),
                ("30", 250, 465, 11, False),
                ("Paris", 400, 465, 11, False),
                ("Bob", 72, 450, 11, False),
                ("25", 250, 450, 11, False),
                ("Berlin", 400, 450, 11, False),
            ],
            [
                ("Page Two", 72, 720, 24, True),
                ("Another paragraph.", 72, 680, 11, False),
            ],
        ],
    )


@pytest.fixture
def encrypted_pdf(tmp_path):
    return make_encrypted_pdf(tmp_path / "encrypted.pdf", "secret")


@pytest.fixture
def sample_images(tmp_path):
    first = make_image(tmp_path / "red.png", size=(200, 100), color="red")
    second = make_image(tmp_path / "green.png", size=(250, 100), color="green")
    return [first, second]
