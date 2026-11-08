"""Filesystem helpers: input validation and atomic output writes."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import UnsupportedFileError


def require_file(path: str | Path) -> Path:
    """Return *path* as a Path, raising a user-facing error if it is not a file."""
    resolved = Path(path)
    if not resolved.exists():
        raise UnsupportedFileError(f"File not found: {resolved}")
    if not resolved.is_file():
        raise UnsupportedFileError(f"Not a file: {resolved}")
    return resolved


@contextmanager
def atomic_output(path: str | Path, suffix: str = ".tmp") -> Iterator[Path]:
    """Yield a temporary path and atomically replace *path* on success.

    The temporary file lives in the destination directory, so ``os.replace``
    stays on the same filesystem. On any exception the temporary file is
    removed and the destination is left untouched.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=suffix,
        dir=target.parent,
    )
    os.close(fd)
    tmp = Path(name)
    try:
        yield tmp
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def write_text(path: str | Path, text: str, encoding: str = "utf-8") -> Path:
    """Write *text* to *path* atomically and return the path."""
    with atomic_output(path, suffix=".txt") as tmp:
        tmp.write_text(text, encoding=encoding)
    return Path(path)
