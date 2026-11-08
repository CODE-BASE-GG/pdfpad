"""Background workers for running core operations without freezing the GUI."""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from core.errors import OperationCancelled, PdfPadError


class WorkerSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()


class OperationWorker(QRunnable):
    """Run one core operation in a thread pool with progress and cancellation.

    Core operations receive two injected keyword arguments:
    ``progress(current, total)`` and ``cancel() -> bool``.
    """

    def __init__(self, func: Callable[..., Any], /, **kwargs: Any) -> None:
        super().__init__()
        self.func = func
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Ask the running operation to stop at its next checkpoint."""
        self._cancel_event.set()

    def _cancel_cb(self) -> bool:
        return self._cancel_event.is_set()

    def _progress_cb(self, current: int, total: int) -> None:
        self.signals.progress.emit(current, total)

    @Slot()
    def run(self) -> None:
        try:
            result = self.func(
                progress=self._progress_cb,
                cancel=self._cancel_cb,
                **self.kwargs,
            )
        except OperationCancelled:
            self.signals.cancelled.emit()
        except PdfPadError as exc:
            self.signals.failed.emit(str(exc), "")
        except Exception:
            self.signals.failed.emit(
                "Unexpected error while processing the files.",
                traceback.format_exc(),
            )
        else:
            self.signals.finished.emit(result)
