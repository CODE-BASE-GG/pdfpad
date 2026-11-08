"""Main application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.errors import EncryptedPdfError, PdfPadError
from core.pages import page_count
from gui.operations import (
    OPERATIONS_BY_KEY,
    RequestError,
    build_request,
    is_pdf,
)
from gui.options_panel import OptionsPanel
from gui.widgets.drop_list import FileDropList
from gui.widgets.preview import PreviewStrip
from gui.workers import OperationWorker

_OFFICE_PATTERNS = (
    "*.doc *.docx *.odt *.rtf *.xls *.xlsx *.ods *.ppt *.pptx *.odp"
)
_FILE_FILTER = (
    "Supported files "
    f"(*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif "
    f"{_OFFICE_PATTERNS});;"
    "PDF files (*.pdf);;"
    "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif);;"
    f"Office documents ({_OFFICE_PATTERNS})"
)


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings or QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            "pdfpad",
            "pdfpad",
        )
        self.threadpool = QThreadPool.globalInstance()
        self._active_worker: OperationWorker | None = None
        self._last_output: Path | None = None
        self._last_operation_key: str | None = None
        self._last_input_size: int | None = None
        self._last_dir = str(Path.home())

        self.setWindowTitle("PDFPad — Offline PDF Toolkit")
        self.resize(1120, 760)
        self.setMinimumSize(880, 620)

        self._build_ui()
        self._connect()
        self._restore_settings()

    # -- construction --------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_input_panel())
        splitter.addWidget(self._build_operation_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([430, 690])
        outer.addWidget(splitter)

        self.statusBar().showMessage("Ready.")

    def _build_input_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Input files")
        group_layout = QVBoxLayout(group)

        self.file_list = FileDropList()
        group_layout.addWidget(self.file_list)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add files…")
        self.remove_button = QPushButton("Remove selected")
        self.clear_button = QPushButton("Clear")
        self.add_button.setShortcut(QKeySequence.StandardKey.Open)
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.remove_button)
        button_row.addWidget(self.clear_button)
        group_layout.addLayout(button_row)

        self.preview = PreviewStrip()
        group_layout.addWidget(self.preview)

        layout.addWidget(group)
        return panel

    def _build_operation_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.options_panel = OptionsPanel()
        layout.addWidget(self.options_panel)

        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Add files to begin.")
        self.status_label.setWordWrap(True)
        progress_layout.addWidget(self.status_label)

        action_row = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.open_button = QPushButton("Open output folder")
        self.open_button.setVisible(False)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.open_button)
        action_row.addStretch(1)
        progress_layout.addLayout(action_row)

        layout.addWidget(progress_group)
        layout.addStretch(1)
        return panel

    def _connect(self) -> None:
        self.add_button.clicked.connect(self._add_files)
        self.remove_button.clicked.connect(self.file_list.remove_selected)
        self.clear_button.clicked.connect(self.file_list.clear_files)
        self.file_list.filesChanged.connect(self._on_files_changed)
        self.file_list.rejected.connect(self._on_rejected)
        self.file_list.currentItemChanged.connect(self._on_current_item_changed)
        self.options_panel.runRequested.connect(self._run)
        self.options_panel.operationChanged.connect(self._on_operation_changed)
        self.cancel_button.clicked.connect(self._cancel)
        self.open_button.clicked.connect(self._open_output)

    # -- settings ------------------------------------------------------
    def _restore_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self._last_dir = str(
            self.settings.value("files/last_dir", str(Path.home()))
        )
        self.options_panel.set_operation(
            str(self.settings.value("operation/last", "extract"))
        )

    def _save_settings(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("files/last_dir", self._last_dir)
        self.settings.setValue("operation/last", self.options_panel.current_key())
        self.settings.sync()

    # -- input handling ------------------------------------------------
    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add files", self._last_dir, _FILE_FILTER
        )
        if not paths:
            return
        self._last_dir = str(Path(paths[0]).parent)
        self.file_list.add_files(paths)

    def _on_files_changed(self) -> None:
        files = self.file_list.files()
        self.options_panel.set_files(files)
        if files:
            self.status_label.setText(f"{len(files)} file(s) ready.")
        else:
            self.status_label.setText("Add files to begin.")

        current = self.file_list.currentItem()
        if current is not None:
            self.preview.show_file(current.data(Qt.ItemDataRole.UserRole))
        else:
            self.preview.clear()

    def _on_rejected(self, paths: list[str]) -> None:
        names = ", ".join(Path(path).name for path in paths[:3])
        if len(paths) > 3:
            names += f", +{len(paths) - 3} more"
        self.status_label.setText(f"Ignored unsupported or missing file(s): {names}")

    def _on_current_item_changed(self, current, _previous) -> None:
        if current is None:
            self.preview.clear()
        else:
            self.preview.show_file(current.data(Qt.ItemDataRole.UserRole))

    def _on_operation_changed(self, key: str) -> None:
        spec = OPERATIONS_BY_KEY[key]
        self.statusBar().showMessage(f"{spec.label}: {spec.description}", 5000)

    # -- running -------------------------------------------------------
    def _resolve_passwords(self, files: list[Path]) -> dict[Path, str] | None:
        """Prompt for passwords on encrypted PDFs. Returns None if cancelled."""
        passwords: dict[Path, str] = {}
        for path in files:
            if not is_pdf(path):
                continue
            password: str | None = None
            for _attempt in range(3):
                try:
                    page_count(path, password=password)
                    break
                except EncryptedPdfError:
                    entered, ok = QInputDialog.getText(
                        self,
                        "Password required",
                        f"Enter the password for:\n{path.name}",
                        QLineEdit.EchoMode.Password,
                    )
                    if not ok:
                        return None
                    password = entered
                except PdfPadError as exc:
                    QMessageBox.critical(self, "Cannot read PDF", str(exc))
                    return None
            else:
                QMessageBox.critical(
                    self,
                    "Cannot read PDF",
                    f"Too many incorrect passwords for {path.name}.",
                )
                return None
            if password is not None:
                passwords[path] = password
        return passwords

    def _run(self) -> None:
        if self._active_worker is not None:
            return

        files = self.file_list.files()
        if not files:
            QMessageBox.warning(self, "No input files", "Add files before running.")
            return

        options = self.options_panel.collect_options()
        passwords = self._resolve_passwords(files)
        if passwords is None:
            self.status_label.setText("Cancelled.")
            return

        try:
            request = build_request(
                self.options_panel.current_key(),
                files,
                options,
                passwords=passwords,
            )
        except RequestError as exc:
            QMessageBox.critical(self, "Cannot start", str(exc))
            return
        except PdfPadError as exc:
            QMessageBox.critical(self, "Cannot start", str(exc))
            return

        worker = OperationWorker(request.func, **request.kwargs)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.cancelled.connect(self._on_cancelled)

        self._active_worker = worker
        self._last_output = request.output
        self._last_operation_key = request.spec.key
        self._last_input_size = (
            sum(path.stat().st_size for path in files if path.is_file())
            if request.spec.key == "compress"
            else None
        )
        self._set_running(True)
        self.status_label.setText(f"Running: {request.spec.label}…")
        self.threadpool.start(worker)

    def _set_running(self, running: bool) -> None:
        self.options_panel.set_running(running)
        self.file_list.setEnabled(not running)
        self.add_button.setEnabled(not running)
        self.remove_button.setEnabled(not running)
        self.clear_button.setEnabled(not running)
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(running)
        self.progress_bar.setVisible(running)
        if running:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setValue(0)

    def _cancel(self) -> None:
        if self._active_worker is not None:
            self._active_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling…")

    def _on_progress(self, current: int, total: int) -> None:
        if total <= 0:
            return
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Working… {current}/{total}")

    def _on_finished(self, result) -> None:
        self._active_worker = None
        self._set_running(False)

        if isinstance(result, list):
            count = len(result)
            directory = result[0].parent if result else self._last_output
            self._last_output = directory
            message = f"Done — created {count} file(s) in {directory}."
        elif isinstance(result, Path):
            self._last_output = result.parent
            message = f"Done — saved {result}."
            if self._last_operation_key == "compress":
                message += self._compression_summary(result)
        else:
            message = "Done."

        self.status_label.setText(message)
        self.open_button.setVisible(self._last_output is not None)
        self.statusBar().showMessage(message, 10000)

    def _compression_summary(self, output: Path) -> str:
        if self._last_input_size is None or not output.is_file():
            return ""
        new_size = output.stat().st_size
        before = _format_bytes(self._last_input_size)
        after = _format_bytes(new_size)
        if new_size < self._last_input_size and self._last_input_size > 0:
            percent = 100 * (1 - new_size / self._last_input_size)
            return f" Size: {before} → {after} ({percent:.0f}% smaller)."
        return f" Size: {before} → {after}."

    def _on_failed(self, message: str, details: str) -> None:
        self._active_worker = None
        self._set_running(False)
        self.status_label.setText("Failed.")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Operation failed")
        box.setText(message)
        if details:
            box.setDetailedText(details)
        box.exec()

    def _on_cancelled(self) -> None:
        self._active_worker = None
        self._set_running(False)
        self.status_label.setText("Cancelled.")

    def _open_output(self) -> None:
        if self._last_output is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output)))

    # -- window lifecycle ---------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._save_settings()
        self.preview.cancel_pending()
        if self._active_worker is not None:
            self._active_worker.cancel()
        super().closeEvent(event)
