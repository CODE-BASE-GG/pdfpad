"""Operation selector, per-operation option forms, and output picker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.errors import OfficeUnavailableError
from core.office import find_libreoffice
from gui.operations import (
    FIT_OPTIONS,
    FORMAT_OPTIONS,
    OPERATIONS,
    OPERATIONS_BY_KEY,
    PAGE_SIZE_OPTIONS,
    OperationOptions,
    default_output,
)


class OptionsPanel(QWidget):
    """Right-hand panel: choose an operation, set options, pick output, run."""

    operationChanged = Signal(str)
    runRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._files: list[Path] = []
        self._forms: dict[str, QWidget] = {}
        self._page_range_edits: dict[str, QLineEdit] = {}
        self._build_ui()
        self._on_operation_changed()

    # -- construction --------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        operation_group = QGroupBox("Operation")
        operation_layout = QVBoxLayout(operation_group)

        self.operation_combo = QComboBox()
        for spec in OPERATIONS:
            self.operation_combo.addItem(spec.label, spec.key)
        operation_layout.addWidget(self.operation_combo)

        self.description_label = QLabel()
        self.description_label.setStyleSheet("color: #555;")
        self.description_label.setWordWrap(True)
        operation_layout.addWidget(self.description_label)

        self.stack = QStackedWidget()
        self._build_forms()
        operation_layout.addWidget(self.stack)
        layout.addWidget(operation_group)

        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)
        output_row = QHBoxLayout()
        self.output_label = QLabel("Output file")
        self.output_edit = QLineEdit()
        self.output_edit.setClearButtonEnabled(True)
        self.browse_button = QPushButton("Browse…")
        output_row.addWidget(self.output_label)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self.browse_button)
        output_layout.addLayout(output_row)
        layout.addWidget(output_group)

        self.run_button = QPushButton("Run")
        self.run_button.setMinimumHeight(38)
        self.run_button.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.run_button)
        layout.addStretch(1)

        self.operation_combo.currentIndexChanged.connect(self._on_operation_changed)
        self.browse_button.clicked.connect(self._browse_output)
        self.run_button.clicked.connect(self.runRequested.emit)

    def _build_forms(self) -> None:
        for spec in OPERATIONS:
            if spec.key == "extract":
                widget = self._form_extract()
            elif spec.key == "split":
                widget = self._form_split()
            elif spec.key == "merge":
                widget = self._form_merge()
            elif spec.key == "rotate":
                widget = self._form_rotate()
            elif spec.key == "render":
                widget = self._form_render()
            elif spec.key == "images_to_pdf":
                widget = self._form_images()
            elif spec.key == "text":
                widget = self._form_text()
            elif spec.key == "markdown":
                widget = self._form_markdown()
            elif spec.key == "compress":
                widget = self._form_compress()
            elif spec.key == "office":
                widget = self._form_office()
            else:
                raise ValueError(f"No form for operation {spec.key!r}")
            self._forms[spec.key] = widget
            self.stack.addWidget(widget)

    def _page_range_edit(self, key: str, placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        self._page_range_edits[key] = edit
        setattr(self, f"{key}_page_range", edit)
        return edit

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #666;")
        label.setWordWrap(True)
        return label

    def _form_extract(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow(
            "Pages",
            self._page_range_edit(
                "extract", "e.g. 1-3,5 — leave empty to copy all pages"
            ),
        )
        form.addRow(self._hint("Page numbers are 1-based and inclusive."))
        return widget

    def _form_split(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(1, 1000)
        self.chunk_spin.setValue(1)
        self.chunk_spin.setSuffix(" page(s)")
        form.addRow("Pages per file", self.chunk_spin)
        form.addRow(
            self._hint("Use 1 to create one PDF per page, or a larger chunk size.")
        )
        return widget

    def _form_merge(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            self._hint("All PDFs in the input list are merged in list order.")
        )
        return widget

    def _form_rotate(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.degrees_combo = QComboBox()
        for degrees in (90, 180, 270):
            self.degrees_combo.addItem(f"{degrees}° clockwise", degrees)
        form.addRow("Rotation", self.degrees_combo)
        form.addRow(
            "Pages",
            self._page_range_edit(
                "rotate", "e.g. 1-3,5 — leave empty to rotate all pages"
            ),
        )
        return widget

    def _form_render(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow(
            "Pages",
            self._page_range_edit(
                "render", "e.g. 1-3,5 — leave empty to render all pages"
            ),
        )

        self.render_dpi = QSpinBox()
        self.render_dpi.setRange(36, 600)
        self.render_dpi.setValue(150)
        self.render_dpi.setSuffix(" DPI")
        form.addRow("Resolution", self.render_dpi)

        self.render_format = QComboBox()
        self.render_format.addItems(FORMAT_OPTIONS)
        form.addRow("Format", self.render_format)

        self.render_quality = QSpinBox()
        self.render_quality.setRange(1, 100)
        self.render_quality.setValue(90)
        form.addRow("JPEG quality", self.render_quality)
        self.render_format.currentTextChanged.connect(self._update_render_quality)
        self._update_render_quality(self.render_format.currentText())
        return widget

    def _form_images(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self.images_page_size = QComboBox()
        self.images_page_size.addItems(PAGE_SIZE_OPTIONS)
        form.addRow("Page size", self.images_page_size)

        self.images_fit = QComboBox()
        self.images_fit.addItems(FIT_OPTIONS)
        form.addRow("Fit", self.images_fit)

        self.images_dpi = QSpinBox()
        self.images_dpi.setRange(36, 600)
        self.images_dpi.setValue(150)
        self.images_dpi.setSuffix(" DPI")
        form.addRow("Resolution", self.images_dpi)

        self.images_quality = QSpinBox()
        self.images_quality.setRange(1, 100)
        self.images_quality.setValue(90)
        form.addRow("Image quality", self.images_quality)
        return widget

    def _form_text(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow(
            "Pages",
            self._page_range_edit(
                "text", "e.g. 1-3,5 — leave empty to extract all pages"
            ),
        )
        form.addRow(self._hint("Output is plain UTF-8 text."))
        return widget

    def _form_markdown(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow(
            "Pages",
            self._page_range_edit(
                "markdown", "e.g. 1-3,5 — leave empty to convert all pages"
            ),
        )
        form.addRow(
            self._hint(
                "Best-effort Markdown: headings, paragraphs, lists and simple "
                "tables. Complex layouts are flattened, not reproduced exactly."
            )
        )
        return widget

    def _form_compress(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self.compress_mode = QComboBox()
        self.compress_mode.addItem("Lossless (keep text and vectors)", "lossless")
        self.compress_mode.addItem("Rasterize pages (loses text)", "rasterize")
        form.addRow("Mode", self.compress_mode)

        self.compress_dpi = QSpinBox()
        self.compress_dpi.setRange(36, 600)
        self.compress_dpi.setValue(150)
        self.compress_dpi.setSuffix(" DPI")
        form.addRow("Raster DPI", self.compress_dpi)

        self.compress_quality = QSpinBox()
        self.compress_quality.setRange(1, 100)
        self.compress_quality.setValue(75)
        form.addRow("JPEG quality", self.compress_quality)

        self.compress_mode.currentIndexChanged.connect(
            self._update_compress_controls
        )
        self._update_compress_controls()
        form.addRow(
            self._hint(
                "Lossless recompresses streams and keeps the text layer. "
                "Rasterize rebuilds each page as an image, which can shrink "
                "scans but makes text unsearchable."
            )
        )
        return widget

    def _form_office(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.office_status = QLabel(
            "Select this operation to check for the LibreOffice add-on."
        )
        self.office_status.setWordWrap(True)
        layout.addWidget(self.office_status)

        self.office_refresh = QPushButton("Check add-on")
        self.office_refresh.clicked.connect(self.refresh_office_status)
        row = QHBoxLayout()
        row.addWidget(self.office_refresh)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addWidget(
            self._hint(
                "Converts DOC/DOCX, ODT, RTF, XLS/XLSX, ODS, PPT/PPTX and ODP "
                "files. The optional add-on is not needed for any other "
                "operation."
            )
        )
        return widget

    # -- state ---------------------------------------------------------
    def current_key(self) -> str:
        return str(self.operation_combo.currentData())

    def set_operation(self, key: str) -> None:
        index = self.operation_combo.findData(key)
        if index >= 0:
            self.operation_combo.setCurrentIndex(index)

    def set_files(self, files) -> None:
        self._files = [Path(path) for path in files]
        self._refresh_output()

    def set_output(self, path: str | Path) -> None:
        self.output_edit.setText(str(path))

    def output_path(self) -> Path | None:
        text = self.output_edit.text().strip()
        return Path(text) if text else None

    def collect_options(self) -> OperationOptions:
        key = self.current_key()
        page_range = ""
        if key in self._page_range_edits:
            page_range = self._page_range_edits[key].text().strip()

        if key == "render":
            dpi = self.render_dpi.value()
            quality = self.render_quality.value()
        elif key == "images_to_pdf":
            dpi = self.images_dpi.value()
            quality = self.images_quality.value()
        elif key == "compress":
            dpi = self.compress_dpi.value()
            quality = self.compress_quality.value()
        else:
            dpi = 150
            quality = 90

        compression_mode = (
            str(self.compress_mode.currentData())
            if key == "compress"
            else "lossless"
        )

        return OperationOptions(
            page_range=page_range,
            chunk_size=self.chunk_spin.value(),
            degrees=int(self.degrees_combo.currentData()),
            dpi=dpi,
            image_format=self.render_format.currentText().lower(),
            quality=quality,
            page_size=self.images_page_size.currentText(),
            fit=self.images_fit.currentText().lower(),
            compression_mode=compression_mode,
            output=self.output_path(),
        )

    def set_running(self, running: bool) -> None:
        self.operation_combo.setEnabled(not running)
        self.stack.setEnabled(not running)
        self.output_edit.setEnabled(not running)
        self.browse_button.setEnabled(not running)
        self.run_button.setEnabled(not running)

    # -- slots ---------------------------------------------------------
    def _on_operation_changed(self, *_args) -> None:
        key = self.current_key()
        spec = OPERATIONS_BY_KEY[key]
        self.stack.setCurrentWidget(self._forms[key])
        self.description_label.setText(spec.description)
        self.output_label.setText(
            "Output folder" if spec.output == "dir" else "Output file"
        )
        if key == "office":
            self.refresh_office_status()
        self._refresh_output()
        self.operationChanged.emit(key)

    def refresh_office_status(self) -> None:
        """Check for the optional LibreOffice add-on and show the result."""
        try:
            found = find_libreoffice()
        except OfficeUnavailableError as exc:
            self.office_status.setText(str(exc))
            self.office_status.setStyleSheet("color: #b00020;")
            return

        if found is None:
            self.office_status.setText(
                "LibreOffice add-on: not installed. Office conversion is "
                "unavailable until the optional add-on pack is installed."
            )
            self.office_status.setStyleSheet("color: #b00020;")
            return

        binary, source = found
        self.office_status.setText(
            f"LibreOffice add-on: available ({source}) — {binary}"
        )
        self.office_status.setStyleSheet("color: #1b5e20;")

    def _refresh_output(self) -> None:
        default = default_output(self.current_key(), self._files)
        self.output_edit.setText(str(default) if default is not None else "")

    def _update_render_quality(self, fmt: str) -> None:
        self.render_quality.setEnabled(fmt.upper() == "JPEG")

    def _update_compress_controls(self, *_args) -> None:
        rasterize = self.compress_mode.currentData() == "rasterize"
        self.compress_dpi.setEnabled(rasterize)
        self.compress_quality.setEnabled(rasterize)

    def _browse_output(self) -> None:
        key = self.current_key()
        spec = OPERATIONS_BY_KEY[key]
        start = self.output_edit.text().strip()
        if not start and self._files:
            start = str(self._files[0].parent)

        if spec.output == "dir":
            chosen = QFileDialog.getExistingDirectory(
                self, "Choose output folder", start
            )
        else:
            if spec.default_suffix == ".txt":
                file_filter = "Text files (*.txt)"
            elif spec.default_suffix == ".md":
                file_filter = "Markdown files (*.md)"
            else:
                file_filter = "PDF files (*.pdf)"
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Choose output file", start, file_filter
            )

        if chosen:
            self.output_edit.setText(chosen)
