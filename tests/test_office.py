"""Tests for the optional LibreOffice bridge."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from core.errors import (
    OfficeUnavailableError,
    OperationCancelled,
    PdfOperationError,
    UnsupportedFileError,
)
from core.office import (
    OFFICE_SUFFIXES,
    OfficeInfo,
    find_libreoffice,
    office_available,
    office_info,
    office_to_pdf,
)
from tests.fake_office import make_fake_office

OFFICE_EXTS = (".docx", ".odt", ".xlsx", ".pptx", ".rtf")


def _make_office_file(tmp_path: Path, suffix: str, stem: str) -> Path:
    target = tmp_path / f"{stem}{suffix}"
    target.write_bytes(b"%fake office document%")
    return target


# -- detection -------------------------------------------------------------


def test_find_libreoffice_uses_system_binary(tmp_path, monkeypatch):
    monkeypatch.delenv("PDFPAD_LIBREOFFICE", raising=False)
    found = find_libreoffice(binary=shutil.which("soffice"))
    assert found is not None
    assert Path(found[0]).name == "soffice"


def test_find_libreoffice_none_when_nothing_installed(monkeypatch, tmp_path):
    monkeypatch.delenv("PDFPAD_LIBREOFFICE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert find_libreoffice() is None
    assert office_available() is False


def test_find_libreoffice_honours_environment_variable(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path)
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))
    found = find_libreoffice()
    assert found is not None
    assert found[0] == fake
    assert found[1] == "environment"


def test_find_libreoffice_invalid_env_var_raises(monkeypatch):
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", "/does/not/exist")
    with pytest.raises(OfficeUnavailableError):
        find_libreoffice()
    assert office_available() is False


def test_find_libreoffice_bundle_dir_is_checked(tmp_path, monkeypatch):
    monkeypatch.delenv("PDFPAD_LIBREOFFICE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "no-bin"))

    # A bundle dir without program/soffice contributes nothing, and no system
    # binary is on PATH, so nothing is found.
    empty_bundle = tmp_path / "empty"
    empty_bundle.mkdir()
    assert find_libreoffice(bundle_dir=empty_bundle) is None

    # A real executable under program/soffice is found as bundled.
    bundle = tmp_path / "bundle" / "program"
    bundle.mkdir(parents=True)
    fake = make_fake_office(bundle, "soffice")
    found = find_libreoffice(bundle_dir=tmp_path / "bundle")
    assert found is not None
    assert found[0] == fake
    assert found[1] == "bundled"


def test_office_info_available_and_source(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path)
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))
    info = office_info()
    assert isinstance(info, OfficeInfo)
    assert info.available is True
    assert info.binary == fake
    assert info.source == "environment"
    assert info.version is not None


def test_office_info_unavailable_when_missing(monkeypatch):
    monkeypatch.delenv("PDFPAD_LIBREOFFICE", raising=False)
    monkeypatch.setenv("PATH", str(Path(tempfile.mkdtemp()) / "bin"))
    info = office_info()
    assert info.available is False
    assert info.binary is None


def test_office_suffixes_cover_common_formats():
    for suffix in OFFICE_EXTS:
        assert suffix.lower() in OFFICE_SUFFIXES


# -- conversion ------------------------------------------------------------


def _run_office(
    tmp_path: Path,
    files: list[Path],
    output_dir: Path | None = None,
    **kwargs,
) -> list[Path]:
    output_dir = output_dir or tmp_path / "out"
    return office_to_pdf(files, output_dir, **kwargs)


def test_office_converts_a_document(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    source = _make_office_file(tmp_path, ".docx", "report")
    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    result = _run_office(tmp_path, [source])

    assert len(result) == 1
    assert result[0] == tmp_path / "out" / "report.pdf"
    assert result[0].is_file()
    assert result[0].read_bytes() == b"%PDF-1.4 fake%"


def test_office_converts_multiple_documents(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    sources = [
        _make_office_file(tmp_path, ".odt", "alpha"),
        _make_office_file(tmp_path, ".xlsx", "beta"),
    ]
    result = _run_office(tmp_path, sources)

    assert [path.name for path in result] == ["alpha.pdf", "beta.pdf"]
    assert result == [tmp_path / "out" / "alpha.pdf", tmp_path / "out" / "beta.pdf"]


def test_office_duplicate_stems_get_unique_names(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    sources = [
        _make_office_file(tmp_path, ".docx", "report"),
        _make_office_file(tmp_path, ".odt", "report"),
        _make_office_file(tmp_path, ".rtf", "report"),
    ]
    result = _run_office(tmp_path, sources)

    assert [path.name for path in result] == ["report.pdf", "report-2.pdf", "report-3.pdf"]


def test_office_uses_binary_argument_over_env(monkeypatch, tmp_path):
    explicit = make_fake_office(tmp_path / "explicit")
    env = make_fake_office(tmp_path / "env")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(env))

    source = _make_office_file(tmp_path, ".docx", "report")
    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    result = office_to_pdf([source], tmp_path / "out", binary=str(explicit))
    assert result[0] == tmp_path / "out" / "report.pdf"


def test_office_reports_progress(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    events: list[tuple[int, int]] = []
    sources = [
        _make_office_file(tmp_path, ".odt", "one"),
        _make_office_file(tmp_path, ".pptx", "two"),
        _make_office_file(tmp_path, ".docx", "three"),
    ]
    result = office_to_pdf(sources, tmp_path / "out", progress=lambda c, t: events.append((c, t)))

    assert events == [(1, 3), (2, 3), (3, 3)]
    assert len(result) == 3


def test_office_cancel_before_first_document_leaves_no_output(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    source = _make_office_file(tmp_path, ".docx", "report")

    # Cancel immediately: nothing is staged or converted.
    with pytest.raises(OperationCancelled):
        office_to_pdf([source], tmp_path / "out", cancel=lambda: True)
    assert not list((tmp_path / "out").glob("*.pdf"))


def test_office_timeout(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))
    monkeypatch.setenv("FAKE_OFFICE_BEHAVIOR", "sleep")
    monkeypatch.setenv("FAKE_OFFICE_SLEEP", "30")

    source = _make_office_file(tmp_path, ".docx", "report")

    with pytest.raises(PdfOperationError, match="timed out"):
        office_to_pdf([source], tmp_path / "out", timeout=0.1)

    assert not (tmp_path / "out" / "report.pdf").exists()


def test_office_conversion_failure_propagates(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    monkeypatch.setenv("FAKE_OFFICE_BEHAVIOR", "fail")
    source = _make_office_file(tmp_path, ".docx", "report")

    with pytest.raises(PdfOperationError, match="could not convert"):
        office_to_pdf([source], tmp_path / "out")


def test_office_no_output_propagates(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    monkeypatch.setenv("FAKE_OFFICE_BEHAVIOR", "no-output")
    source = _make_office_file(tmp_path, ".docx", "report")

    with pytest.raises(PdfOperationError, match="produced no PDF"):
        office_to_pdf([source], tmp_path / "out")


def test_office_multiple_outputs_propagates(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    monkeypatch.setenv("FAKE_OFFICE_BEHAVIOR", "multi-output")
    source = _make_office_file(tmp_path, ".docx", "report")

    with pytest.raises(PdfOperationError, match="several PDFs"):
        office_to_pdf([source], tmp_path / "out")


def test_office_wrong_output_name_is_resilient(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    # LibreOffice sometimes names the output differently than the input stem;
    # PDFPad accepts any single PDF produced in the output directory.
    monkeypatch.setenv("FAKE_OFFICE_BEHAVIOR", "wrong-name")
    source = _make_office_file(tmp_path, ".docx", "report")

    result = office_to_pdf([source], tmp_path / "out")
    assert result == [tmp_path / "out" / "report.pdf"]
    assert result[0].read_bytes() == b"%PDF-1.4 fake%"


def test_office_unsupported_input_is_rejected(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    not_office = tmp_path / "notes.txt"
    not_office.write_text("hello")

    with pytest.raises(UnsupportedFileError, match="Unsupported Office document"):
        office_to_pdf([not_office], tmp_path / "out")


def test_office_missing_input_is_rejected(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    with pytest.raises(UnsupportedFileError, match="File not found"):
        office_to_pdf([tmp_path / "missing.docx"], tmp_path / "out")


def test_office_no_documents_is_rejected(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    with pytest.raises(PdfOperationError, match="No Office documents provided"):
        office_to_pdf([], tmp_path / "out")


def test_office_unavailable_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("PDFPAD_LIBREOFFICE", raising=False)
    monkeypatch.setenv("PATH", str(Path(tempfile.mkdtemp()) / "bin"))

    source = _make_office_file(tmp_path, ".docx", "report")

    with pytest.raises(OfficeUnavailableError):
        office_to_pdf([source], tmp_path / "out")


# -- arguments / profile ---------------------------------------------------


def test_office_records_command_arguments(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    log = tmp_path / "invocations.jsonl"
    monkeypatch.setenv("FAKE_OFFICE_LOG", str(log))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    source = _make_office_file(tmp_path, ".docx", "report")
    office_to_pdf([source], tmp_path / "out")

    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines, "expected at least one recorded invocation"
    invocation = json.loads(lines[-1])
    assert "--headless" in invocation
    assert "--convert-to" in invocation
    assert "pdf" in invocation
    inputs = [arg for arg in invocation if not arg.startswith("-")]
    assert inputs and inputs[-1].endswith("report.docx")
    assert "--outdir" in invocation


def test_office_uses_private_profile(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    source = _make_office_file(tmp_path, ".docx", "report")
    office_to_pdf([source], tmp_path / "out")

    log_path = tmp_path / "invocations.jsonl"
    monkeypatch.setenv("FAKE_OFFICE_LOG", str(log_path))
    office_to_pdf([source], tmp_path / "out")

    invocation = json.loads(log_path.read_text().splitlines()[-1])
    profile = [arg for arg in invocation if arg.startswith("-env:UserInstallation=")]
    assert profile, "expected a private UserInstallation profile"
    assert "pdfpad-office-profile" in profile[0]


def test_office_input_not_written_next_to_original(tmp_path, monkeypatch):
    fake = make_fake_office(tmp_path / "bin")
    monkeypatch.setenv("PDFPAD_LIBREOFFICE", str(fake))

    template = tmp_path / "template.pdf"
    template.write_bytes(b"%PDF-1.4 fake%")
    monkeypatch.setenv("FAKE_OFFICE_TEMPLATE", str(template))

    source_dir = tmp_path / "inputs"
    source_dir.mkdir()
    source = _make_office_file(source_dir, ".docx", "report")

    office_to_pdf([source], tmp_path / "out")

    # The original file is unchanged and no lock/temp files appear beside it.
    assert source.read_bytes() == b"%fake office document%"
    assert [p.name for p in source_dir.iterdir()] == ["report.docx"]
