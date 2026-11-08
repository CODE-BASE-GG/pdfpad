"""Cooperative progress reporting and cancellation for long operations.

The GUI passes a progress callback and a cancel predicate. Core operations
call :func:`check_cancel` between units of work (a page, an image, a file) and
:func:`report` afterwards. Cancellation is cooperative: an operation stops at
the next checkpoint and raises :class:`OperationCancelled`.
"""

from __future__ import annotations

from collections.abc import Callable

from .errors import OperationCancelled

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]


def report(
    progress: ProgressCallback | None,
    current: int,
    total: int,
) -> None:
    """Report *current* of *total* completed units, if a callback is set."""
    if progress is not None:
        progress(current, total)


def check_cancel(cancel: CancelCallback | None) -> None:
    """Raise :class:`OperationCancelled` when the caller requested a cancel."""
    if cancel is not None and cancel():
        raise OperationCancelled("Operation cancelled.")
