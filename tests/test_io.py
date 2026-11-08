from __future__ import annotations

import pytest

from core.io import atomic_output, write_text


def test_atomic_output_writes_target(tmp_path):
    target = tmp_path / "out.bin"
    with atomic_output(target) as tmp:
        tmp.write_bytes(b"hello")
        assert not target.exists()
    assert target.read_bytes() == b"hello"


def test_atomic_output_replaces_existing_file(tmp_path):
    target = tmp_path / "out.bin"
    target.write_bytes(b"old")
    with atomic_output(target) as tmp:
        tmp.write_bytes(b"new")
    assert target.read_bytes() == b"new"


def test_atomic_output_keeps_target_on_failure(tmp_path):
    target = tmp_path / "out.bin"
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError):
        with atomic_output(target) as tmp:
            tmp.write_bytes(b"partial")
            raise RuntimeError("boom")
    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_output_creates_parent_directories(tmp_path):
    target = tmp_path / "a" / "b" / "out.bin"
    with atomic_output(target) as tmp:
        tmp.write_bytes(b"x")
    assert target.read_bytes() == b"x"


def test_write_text(tmp_path):
    output = write_text(tmp_path / "note.txt", "héllo")
    assert output.read_text(encoding="utf-8") == "héllo"
