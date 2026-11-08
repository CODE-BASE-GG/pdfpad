"""A list widget that accepts PDFs and images dragged from the file manager."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from gui.operations import is_supported


class FileDropList(QListWidget):
    """Ordered list of input files with drag-and-drop and duplicate filtering."""

    filesChanged = Signal()
    rejected = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(150)
        self._known: set[Path] = set()

    # -- drag and drop -------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt API)
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.add_files(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    # -- public API ----------------------------------------------------
    def add_files(self, paths: Iterable[str | Path]) -> int:
        """Add supported files, skipping duplicates. Returns the number added."""
        added = 0
        rejected: list[str] = []
        for raw in paths:
            path = Path(raw)
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if not is_supported(path) or not path.is_file():
                rejected.append(str(path))
                continue
            if resolved in self._known:
                continue

            self._known.add(resolved)
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.addItem(item)
            added += 1

        if rejected:
            self.rejected.emit(rejected)
        if added:
            if self.currentRow() < 0:
                self.setCurrentRow(0)
            self.filesChanged.emit()
        return added

    def files(self) -> list[Path]:
        return [
            Path(self.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.count())
        ]

    def remove_selected(self) -> None:
        rows = sorted(
            {self.row(item) for item in self.selectedItems()}, reverse=True
        )
        if not rows:
            return
        for row in rows:
            item = self.takeItem(row)
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            try:
                self._known.discard(path.resolve())
            except OSError:
                self._known.discard(path)
            del item
        self.filesChanged.emit()

    def clear_files(self) -> None:
        if not self.count():
            return
        self.clear()
        self._known.clear()
        self.filesChanged.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected()
            event.accept()
            return
        super().keyPressEvent(event)
