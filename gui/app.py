"""Application bootstrap: logging, QApplication, and the main window."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow

APP_VERSION = "0.5.0"


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    return Path(base) if base else Path.home() / ".local" / "state"


def _resource_root() -> Path:
    """Return the directory that contains bundled resources.

    PyInstaller stores data under ``sys._MEIPASS`` (``_internal`` in a onedir
    build); running from source uses the project root.
    """
    if getattr(sys, "frozen", False):
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return Path(bundled)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _application_icon() -> QIcon:
    path = _resource_root() / "gui" / "resources" / "pdfpad.png"
    return QIcon(str(path)) if path.is_file() else QIcon()


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure a rotating log file under ``$XDG_STATE_HOME/pdfpad``."""
    logger = logging.getLogger("pdfpad")
    logger.setLevel(level)
    if logger.handlers:
        return logger

    log_dir = _state_dir() / "pdfpad"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "pdfpad.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    return logger


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setOrganizationName("pdfpad")
    app.setApplicationName("PDFPad")
    app.setApplicationVersion(APP_VERSION)
    icon = _application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    return app


def run_self_test() -> int:
    """Exercise every bundled conversion path and the GUI without a display.

    This is used by the packaging build to prove that a frozen build can load
    its native dependencies. It covers all six feature areas plus encrypted
    PDFs and never touches the user's documents.
    """
    from PIL import Image
    from pypdf import PdfReader, PdfWriter

    from core.compress import compress_pdf
    from core.errors import EncryptedPdfError
    from core.images import images_to_pdf
    from core.markdown import extract_markdown
    from core.pages import (
        extract_pages,
        merge_pdfs,
        page_count,
        rotate_pages,
        split_pdf,
    )
    from core.ranges import parse_ranges
    from core.render import render_page_image
    from core.text import extract_text

    checks: list[tuple[str, bool]] = []

    with tempfile.TemporaryDirectory(prefix="pdfpad-self-test-") as temporary:
        root = Path(temporary)

        def make_pdf(name: str, pages: int, password: str | None = None) -> Path:
            path = root / name
            writer = PdfWriter()
            for _ in range(pages):
                writer.add_blank_page(width=200, height=200)
            if password is not None:
                writer.encrypt(password, algorithm="AES-256")
            with path.open("wb") as handle:
                writer.write(handle)
            return path

        sample = make_pdf("sample.pdf", 3)
        checks.append(("pypdf page count", page_count(sample) == 3))
        checks.append(("page range parser", parse_ranges("1-2,3,2", 3) == [0, 1, 2]))

        extracted = extract_pages(sample, [0, 2], root / "extracted.pdf")
        checks.append(("extract pages", page_count(extracted) == 2))

        chunks = split_pdf(sample, root / "split", chunk_size=1)
        checks.append(
            (
                "split pages",
                len(chunks) == 3 and all(page_count(chunk) == 1 for chunk in chunks),
            )
        )

        merged = merge_pdfs([extracted, chunks[0]], root / "merged.pdf")
        checks.append(("merge PDFs", page_count(merged) == 3))

        rotated = rotate_pages(sample, root / "rotated.pdf", 90, indices=[0])
        rotation = PdfReader(str(rotated)).pages[0].rotation
        checks.append(("rotate pages", rotation % 360 == 90))

        rendered = render_page_image(sample, 0, dpi=72)
        checks.append(("pypdfium2 render", rendered.width > 0 and rendered.height > 0))

        checks.append(("pdfminer text", extract_text(sample).strip() == ""))
        checks.append(("pdfminer markdown", extract_markdown(sample).strip() == ""))

        compressed = compress_pdf(sample, root / "compressed.pdf")
        checks.append(("pikepdf lossless", compressed.is_file()))

        rasterized = compress_pdf(
            sample,
            root / "rasterized.pdf",
            mode="rasterize",
            dpi=72,
            quality=80,
        )
        checks.append(("pikepdf rasterize", page_count(rasterized) == 3))

        source_image = root / "source.png"
        Image.new("RGB", (32, 32), "white").save(source_image)
        images_pdf = images_to_pdf([source_image], root / "images.pdf")
        checks.append(("Pillow images to PDF", images_pdf.is_file()))

        encrypted = make_pdf("encrypted.pdf", 1, password="secret")
        checks.append(
            ("encrypted read with password", page_count(encrypted, "secret") == 1)
        )
        try:
            page_count(encrypted)
        except EncryptedPdfError:
            rejected = True
        else:
            rejected = False
        checks.append(("encrypted rejects missing password", rejected))

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = create_application(["pdfpad-self-test"])
        settings = QSettings(
            str(root / "settings.ini"), QSettings.Format.IniFormat
        )
        window = MainWindow(settings=settings)
        window.show()
        app.processEvents()
        checks.append(("Qt window", window.isVisible()))
        checks.append(("Qt icon", not app.windowIcon().isNull()))
        window.preview.cancel_pending()
        window.close()

    failed = [name for name, passed in checks if not passed]
    for name, passed in checks:
        print(f"{'ok' if passed else 'FAILED'}  {name}")
    if failed:
        print(f"PDFPad self-test failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"PDFPad {APP_VERSION} self-test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if "--version" in args:
        print(f"PDFPad {APP_VERSION}")
        return 0
    if "--self-test" in args:
        return run_self_test()

    logger = setup_logging()
    logger.info("Starting PDFPad %s", APP_VERSION)
    app = create_application(args)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
