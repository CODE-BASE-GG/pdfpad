"""Offscreen tests for the PySide6 widgets and the main window."""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest
from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import QSettings, QThreadPool
from PySide6.QtWidgets import QInputDialog, QMessageBox

from gui.main_window import MainWindow
from gui.operations import OPERATIONS
from gui.widgets.preview import pil_to_pixmap


@pytest.fixture
def window(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    main_window = MainWindow(settings=settings)
    qtbot.addWidget(main_window)
    main_window.show()
    yield main_window
    # Let preview/operation workers finish before pytest-qt destroys widgets.
    main_window.preview.cancel_pending()
    QThreadPool.globalInstance().waitForDone(15000)


# -- construction ----------------------------------------------------------


def test_window_builds_with_defaults(window):
    assert "PDFPad" in window.windowTitle()
    assert window.options_panel.operation_combo.count() == len(OPERATIONS)
    assert window.options_panel.current_key() == "extract"
    assert window.status_label.text() == "Add files to begin."
    assert not window.progress_bar.isVisible()
    assert not window.cancel_button.isVisible()
    assert not window.open_button.isVisible()


def test_operation_combo_lists_every_operation(window):
    keys = [
        window.options_panel.operation_combo.itemData(index)
        for index in range(window.options_panel.operation_combo.count())
    ]
    assert keys == [spec.key for spec in OPERATIONS]


# -- file list -------------------------------------------------------------


def test_file_list_adds_supported_files_and_rejects_others(
    window, three_page_pdf, sample_images, tmp_path
):
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("hello", encoding="utf-8")

    rejected: list[list[str]] = []
    window.file_list.rejected.connect(rejected.append)

    added = window.file_list.add_files(
        [three_page_pdf, sample_images[0], unsupported]
    )

    assert added == 2
    assert [path.name for path in window.file_list.files()] == [
        "three.pdf",
        "red.png",
    ]
    assert rejected and rejected[0] == [str(unsupported)]


def test_file_list_skips_duplicates(window, three_page_pdf):
    assert window.file_list.add_files([three_page_pdf]) == 1
    assert window.file_list.add_files([three_page_pdf]) == 0
    assert len(window.file_list.files()) == 1


def test_file_list_remove_and_clear(window, three_page_pdf, sample_images):
    window.file_list.add_files([three_page_pdf, sample_images[0]])
    window.file_list.setCurrentRow(0)
    window.file_list.remove_selected()
    assert [path.name for path in window.file_list.files()] == ["red.png"]

    window.file_list.clear_files()
    assert window.file_list.files() == []


def test_adding_files_selects_first_and_previews(window, three_page_pdf):
    window.file_list.add_files([three_page_pdf])
    assert window.file_list.currentRow() == 0
    # The preview worker is asynchronous; the status changes immediately.
    assert window.preview._status.text() in {
        "Rendering preview…",
        "3 page(s)",
    }


# -- output defaults -------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected_name"),
    [
        ("extract", "three_extracted.pdf"),
        ("split", "three_pages"),
        ("merge", "three_merged.pdf"),
        ("rotate", "three_rotated.pdf"),
        ("render", "three_images"),
        ("images_to_pdf", "three_images.pdf"),
        ("text", "three.txt"),
        ("markdown", "three.md"),
        ("compress", "three_compressed.pdf"),
        ("office", "three_office"),
    ],
)
def test_operation_switch_updates_default_output(
    window, three_page_pdf, key, expected_name
):
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation(key)
    assert Path(window.options_panel.output_edit.text()).name == expected_name


def test_output_label_follows_operation(window, three_page_pdf):
    window.file_list.add_files([three_page_pdf])

    window.options_panel.set_operation("split")
    assert window.options_panel.output_label.text() == "Output folder"

    window.options_panel.set_operation("extract")
    assert window.options_panel.output_label.text() == "Output file"


def test_output_label_follows_compress_and_office(window, three_page_pdf):
    window.file_list.add_files([three_page_pdf])

    window.options_panel.set_operation("compress")
    assert window.options_panel.output_label.text() == "Output file"

    window.options_panel.set_operation("office")
    assert window.options_panel.output_label.text() == "Output folder"


def test_output_label_follows_markdown(window, three_page_pdf):
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("markdown")
    assert window.options_panel.output_label.text() == "Output file"


def test_output_is_empty_without_files(window):
    window.options_panel.set_operation("render")
    assert window.options_panel.output_edit.text() == ""


# -- option collection -----------------------------------------------------


def test_collect_options_reads_render_widgets(window, three_page_pdf):
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("render")
    window.options_panel.render_page_range.setText("1-2")
    window.options_panel.render_dpi.setValue(200)
    window.options_panel.render_format.setCurrentText("JPEG")
    window.options_panel.render_quality.setValue(70)

    options = window.options_panel.collect_options()

    assert options.page_range == "1-2"
    assert options.dpi == 200
    assert options.image_format == "jpeg"
    assert options.quality == 70
    assert options.output is not None


def test_collect_options_reads_images_widgets(window, sample_images):
    window.file_list.add_files(sample_images)
    window.options_panel.set_operation("images_to_pdf")
    window.options_panel.images_page_size.setCurrentText("Letter")
    window.options_panel.images_fit.setCurrentText("Cover")
    window.options_panel.images_dpi.setValue(180)
    window.options_panel.images_quality.setValue(65)

    options = window.options_panel.collect_options()

    assert options.page_size == "Letter"
    assert options.fit == "cover"
    assert options.dpi == 180
    assert options.quality == 65


def test_collect_options_reads_compress_widgets(window, three_page_pdf):
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("compress")
    window.options_panel.compress_mode.setCurrentText("Rasterize pages (loses text)")
    window.options_panel.compress_dpi.setValue(200)
    window.options_panel.compress_quality.setValue(70)

    options = window.options_panel.collect_options()

    assert options.compression_mode == "rasterize"
    assert options.dpi == 200
    assert options.quality == 70


def test_collect_options_reads_markdown_page_range(window, rich_pdf):
    window.file_list.add_files([rich_pdf])
    window.options_panel.set_operation("markdown")
    window.options_panel.markdown_page_range.setText("2")

    options = window.options_panel.collect_options()

    assert options.page_range == "2"
    assert options.output is not None
    assert options.output.name == "rich.md"


def test_compress_quality_controls_follow_mode(window, three_page_pdf):
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("compress")

    window.options_panel.compress_mode.setCurrentText("Lossless (keep text and vectors)")
    assert not window.options_panel.compress_dpi.isEnabled()
    assert not window.options_panel.compress_quality.isEnabled()

    window.options_panel.compress_mode.setCurrentText("Rasterize pages (loses text)")
    assert window.options_panel.compress_dpi.isEnabled()
    assert window.options_panel.compress_quality.isEnabled()


def test_office_status_unavailable_when_no_backend(window, monkeypatch, three_page_pdf):
    monkeypatch.delenv("PDFPAD_LIBREOFFICE", raising=False)
    monkeypatch.setenv("PATH", str(Path(tempfile.mkdtemp()) / "bin"))

    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("office")

    assert "not installed" in window.options_panel.office_status.text()
    assert window.options_panel.office_status.styleSheet().startswith("color: #b00020;")


def test_jpeg_quality_enabled_only_for_jpeg(window, three_page_pdf):
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("render")

    window.options_panel.render_format.setCurrentText("PNG")
    assert not window.options_panel.render_quality.isEnabled()

    window.options_panel.render_format.setCurrentText("JPEG")
    assert window.options_panel.render_quality.isEnabled()


# -- running ---------------------------------------------------------------


def test_run_without_files_warns(window, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: calls.append(args)
    )

    window.options_panel.run_button.click()

    assert calls
    assert "No input files" in calls[0][1]


def test_invalid_selection_shows_error(window, monkeypatch, sample_images):
    calls: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args, **kwargs: calls.append(args)
    )

    window.file_list.add_files([sample_images[0]])
    window.options_panel.set_operation("extract")
    window.options_panel.run_button.click()

    assert calls
    assert "PDF" in calls[0][2]


def test_extract_runs_end_to_end(window, qtbot, three_page_pdf, tmp_path):
    output = tmp_path / "selected.pdf"
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("extract")
    window.options_panel.extract_page_range.setText("1-2")
    window.options_panel.set_output(output)

    window.options_panel.run_button.click()

    qtbot.waitUntil(output.is_file, timeout=15000)
    qtbot.waitUntil(
        lambda: window.status_label.text().startswith("Done"), timeout=5000
    )

    assert len(PdfReader(str(output)).pages) == 2
    assert window.open_button.isVisible()
    assert not window.progress_bar.isVisible()
    assert not window.cancel_button.isVisible()


def test_text_runs_end_to_end(window, qtbot, text_pdf, tmp_path):
    output = tmp_path / "text.txt"
    window.file_list.add_files([text_pdf])
    window.options_panel.set_operation("text")
    window.options_panel.text_page_range.setText("2")
    window.options_panel.set_output(output)

    window.options_panel.run_button.click()

    qtbot.waitUntil(output.is_file, timeout=15000)
    assert output.read_text(encoding="utf-8") == "Hello two"


def test_markdown_runs_end_to_end(window, qtbot, rich_pdf, tmp_path):
    output = tmp_path / "rich.md"
    window.file_list.add_files([rich_pdf])
    window.options_panel.set_operation("markdown")
    window.options_panel.markdown_page_range.setText("2")
    window.options_panel.set_output(output)

    window.options_panel.run_button.click()

    qtbot.waitUntil(output.is_file, timeout=15000)
    text = output.read_text(encoding="utf-8")
    assert text.startswith("# Page Two")
    assert "# Document Title" not in text
    qtbot.waitUntil(
        lambda: window.status_label.text().startswith("Done"), timeout=5000
    )
    assert window.open_button.isVisible()


def test_render_runs_end_to_end(window, qtbot, three_page_pdf, tmp_path):
    output = tmp_path / "images"
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("render")
    window.options_panel.render_page_range.setText("1")
    window.options_panel.render_dpi.setValue(72)
    window.options_panel.set_output(output)

    window.options_panel.run_button.click()

    expected = output / "three_page_1.png"
    qtbot.waitUntil(expected.is_file, timeout=15000)
    assert Image.open(expected).size == (300, 400)


def test_compress_runs_end_to_end(window, qtbot, three_page_pdf, tmp_path):
    output = tmp_path / "three_compressed.pdf"
    window.file_list.add_files([three_page_pdf])
    window.options_panel.set_operation("compress")
    window.options_panel.compress_mode.setCurrentText("Lossless (keep text and vectors)")
    window.options_panel.set_output(output)

    window.options_panel.run_button.click()

    qtbot.waitUntil(output.is_file, timeout=15000)
    qtbot.waitUntil(
        lambda: window.status_label.text().startswith("Done"), timeout=5000
    )
    assert "Size:" in window.status_label.text()
    assert window.open_button.isVisible()


# -- encrypted PDFs --------------------------------------------------------


def test_encrypted_pdf_prompts_and_runs(
    window, qtbot, monkeypatch, encrypted_pdf, tmp_path
):
    output = tmp_path / "decrypted.pdf"
    prompts: list[str] = []

    def fake_get_text(_parent, _title, label, *args, **kwargs):
        prompts.append(label)
        return "secret", True

    monkeypatch.setattr(QInputDialog, "getText", fake_get_text)

    window.file_list.add_files([encrypted_pdf])
    window.options_panel.set_output(output)
    window.options_panel.run_button.click()

    qtbot.waitUntil(output.is_file, timeout=15000)
    assert len(PdfReader(str(output)).pages) == 2
    assert prompts and "encrypted.pdf" in prompts[0]


def test_cancelled_password_prompt_aborts(
    window, monkeypatch, encrypted_pdf, tmp_path
):
    output = tmp_path / "decrypted.pdf"
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *args, **kwargs: ("", False)
    )

    window.file_list.add_files([encrypted_pdf])
    window.options_panel.set_output(output)
    window.options_panel.run_button.click()

    assert window.status_label.text() == "Cancelled."
    assert not output.exists()


def test_too_many_wrong_passwords_shows_error(
    window, monkeypatch, encrypted_pdf, tmp_path
):
    calls: list[tuple] = []
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *args, **kwargs: ("wrong", True)
    )
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args, **kwargs: calls.append(args)
    )

    window.file_list.add_files([encrypted_pdf])
    window.options_panel.set_output(tmp_path / "decrypted.pdf")
    window.options_panel.run_button.click()

    assert calls
    assert "Too many incorrect passwords" in calls[0][2]


# -- preview helpers -------------------------------------------------------


def test_pil_to_pixmap_rgb(qtbot):
    image = Image.new("RGB", (40, 30), "red")
    pixmap = pil_to_pixmap(image)
    assert not pixmap.isNull()
    assert (pixmap.width(), pixmap.height()) == (40, 30)


def test_pil_to_pixmap_rgba(qtbot):
    image = Image.new("RGBA", (20, 10), (255, 0, 0, 128))
    pixmap = pil_to_pixmap(image)
    assert not pixmap.isNull()
    assert (pixmap.width(), pixmap.height()) == (20, 10)


def test_preview_shows_image(window, sample_images):
    window.preview.show_file(sample_images[0])
    assert window.preview._row.count() == 1
    assert sample_images[0].name in window.preview._status.text()


def test_preview_clears(window, sample_images):
    window.preview.show_file(sample_images[0])
    window.preview.clear()
    assert window.preview._row.count() == 0
    assert window.preview._status.text() == "Select a file to preview."
