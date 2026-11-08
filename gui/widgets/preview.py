"""Page thumbnail preview strip for the selected input file."""

from __future__ import annotations

import threading
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.errors import OperationCancelled, PdfPadError
from core.pages import page_count
from core.render import render_thumbnails
from gui.operations import is_image, is_pdf


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    """Convert a PIL image to a QPixmap (must be called on the GUI thread)."""
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA")
    data = image.tobytes("raw", image.mode)
    fmt = (
        QImage.Format.Format_RGBA8888
        if image.mode == "RGBA"
        else QImage.Format.Format_RGB888
    )
    qimage = QImage(
        data,
        image.width,
        image.height,
        image.width * len(image.mode),
        fmt,
    )
    # copy() detaches from the temporary Python buffer.
    return QPixmap.fromImage(qimage.copy())


class PreviewSignals(QObject):
    ready = Signal(int, object, int)  # generation, list[PIL.Image], total pages
    failed = Signal(int, str)


class PreviewWorker(QRunnable):
    """Render up to a dozen page thumbnails without blocking the UI."""

    def __init__(
        self,
        generation: int,
        path: Path,
        max_pages: int = 12,
        max_size: int = 120,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.path = path
        self.max_pages = max_pages
        self.max_size = max_size
        self.signals = PreviewSignals()
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Ask the preview to stop at its next page boundary."""
        self._cancel_event.set()

    def _cancel_cb(self) -> bool:
        return self._cancel_event.is_set()

    @Slot()
    def run(self) -> None:
        try:
            total = page_count(self.path)
            images = render_thumbnails(
                self.path,
                max_pages=self.max_pages,
                max_size=self.max_size,
                cancel=self._cancel_cb,
            )
        except OperationCancelled:
            return
        except PdfPadError as exc:
            self.signals.failed.emit(self.generation, str(exc))
        except Exception:
            self.signals.failed.emit(
                self.generation, "Could not render a preview of this PDF."
            )
        else:
            self.signals.ready.emit(self.generation, images, total)


class PreviewStrip(QWidget):
    """Horizontal strip showing thumbnails of the selected PDF or image."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._generation = 0
        self._workers: list[PreviewWorker] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel("Preview")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(165)
        self._scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._scroll)

        self._content = QWidget()
        self._row = QHBoxLayout(self._content)
        self._row.setContentsMargins(8, 8, 8, 8)
        self._row.setSpacing(10)
        self._row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._scroll.setWidget(self._content)

        self._status = QLabel("Select a file to preview.")
        self._status.setStyleSheet("color: #666;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    # -- public API ----------------------------------------------------
    def show_file(self, path: str | Path | None) -> None:
        self._cancel_pending()
        self._generation += 1
        generation = self._generation
        self._clear_thumbnails()

        if path is None:
            self._status.setText("Select a file to preview.")
            return

        source = Path(path)
        if not source.is_file():
            self._status.setText(f"File not found: {source}")
            return

        if is_image(source):
            pixmap = QPixmap(str(source))
            if pixmap.isNull():
                self._status.setText(f"Could not load image: {source.name}")
                return
            scaled = pixmap.scaledToHeight(120, Qt.TransformationMode.SmoothTransformation)
            self._add_thumbnail(scaled, source.name)
            self._status.setText(source.name)
            return

        if not is_pdf(source):
            self._status.setText("Preview is available for PDFs and images.")
            return

        self._status.setText("Rendering preview…")
        worker = PreviewWorker(generation, source)
        worker.signals.ready.connect(self._on_ready)
        worker.signals.failed.connect(self._on_failed)
        self._workers.append(worker)
        if len(self._workers) > 8:
            self._workers.pop(0)
        QThreadPool.globalInstance().start(worker)

    def clear(self) -> None:
        self._cancel_pending()
        self._generation += 1
        self._clear_thumbnails()
        self._status.setText("Select a file to preview.")

    def cancel_pending(self) -> None:
        """Cancel thumbnail work that is no longer needed."""
        self._cancel_pending()

    # -- internals -----------------------------------------------------
    def _cancel_pending(self) -> None:
        for worker in self._workers:
            worker.cancel()

    def _clear_thumbnails(self) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_thumbnail(self, pixmap: QPixmap, caption: str) -> None:
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        image_label = QLabel()
        image_label.setPixmap(pixmap)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(image_label)

        caption_label = QLabel(caption)
        caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption_label.setStyleSheet("color: #555; font-size: 10px;")
        column.addWidget(caption_label)

        self._row.addWidget(container)

    def _on_ready(self, generation: int, images, total: int) -> None:
        if generation != self._generation:
            return
        self._clear_thumbnails()
        for index, image in enumerate(images, start=1):
            self._add_thumbnail(pil_to_pixmap(image), f"Page {index}")
        if total > len(images):
            more = QLabel(f"+{total - len(images)}\nmore pages")
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            more.setStyleSheet("color: #777;")
            self._row.addWidget(more)
        self._status.setText(
            f"{total} page(s)" if total else "This PDF has no pages."
        )

    def _on_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self._clear_thumbnails()
        self._status.setText(message)
