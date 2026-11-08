"""Tests for the QRunnable worker that bridges core calls to Qt signals."""

from __future__ import annotations

import time

from PySide6.QtCore import QThreadPool, QTimer

from core.errors import OperationCancelled, PdfPadError
from gui.workers import OperationWorker


def _start(worker: OperationWorker) -> None:
    QThreadPool.globalInstance().start(worker)


def test_worker_emits_result_and_progress(qtbot):
    def work(progress, cancel):
        progress(1, 2)
        progress(2, 2)
        return "done"

    worker = OperationWorker(work)
    events: list[tuple[int, int]] = []
    worker.signals.progress.connect(lambda current, total: events.append((current, total)))

    with qtbot.waitSignal(worker.signals.finished, timeout=5000) as blocker:
        _start(worker)

    assert blocker.args == ["done"]
    assert events == [(1, 2), (2, 2)]


def test_worker_passes_kwargs(qtbot):
    def work(progress, cancel, value):
        return value * 2

    worker = OperationWorker(work, value=21)
    with qtbot.waitSignal(worker.signals.finished, timeout=5000) as blocker:
        _start(worker)

    assert blocker.args == [42]


def test_worker_reports_pdf_errors(qtbot):
    def work(progress, cancel):
        raise PdfPadError("Could not read this file.")

    worker = OperationWorker(work)
    with qtbot.waitSignal(worker.signals.failed, timeout=5000) as blocker:
        _start(worker)

    assert blocker.args == ["Could not read this file.", ""]


def test_worker_reports_unexpected_errors_with_traceback(qtbot):
    def work(progress, cancel):
        raise RuntimeError("boom")

    worker = OperationWorker(work)
    with qtbot.waitSignal(worker.signals.failed, timeout=5000) as blocker:
        _start(worker)

    message, details = blocker.args
    assert message == "Unexpected error while processing the files."
    assert "RuntimeError: boom" in details
    assert "Traceback" in details


def test_worker_emits_cancelled(qtbot):
    def work(progress, cancel):
        raise OperationCancelled("stopped")

    worker = OperationWorker(work)
    with qtbot.waitSignal(worker.signals.cancelled, timeout=5000):
        _start(worker)


def test_worker_cancel_flag_is_seen_by_the_operation(qtbot):
    started = {"value": False}

    def work(progress, cancel):
        started["value"] = True
        while not cancel():
            time.sleep(0.005)
        raise OperationCancelled("stopped")

    worker = OperationWorker(work)
    QTimer.singleShot(20, worker.cancel)

    with qtbot.waitSignal(worker.signals.cancelled, timeout=5000):
        _start(worker)

    assert started["value"] is True


def test_cancel_before_start_is_immediate(qtbot):
    def work(progress, cancel):
        if cancel():
            raise OperationCancelled("already cancelled")
        return "ran"

    worker = OperationWorker(work)
    worker.cancel()

    with qtbot.waitSignal(worker.signals.cancelled, timeout=5000):
        _start(worker)


def test_worker_only_emits_one_terminal_signal(qtbot):
    def work(progress, cancel):
        return "ok"

    worker = OperationWorker(work)
    finished: list[object] = []
    failed: list[object] = []
    cancelled: list[object] = []
    worker.signals.finished.connect(finished.append)
    worker.signals.failed.connect(lambda *args: failed.append(args))
    worker.signals.cancelled.connect(lambda: cancelled.append(True))

    with qtbot.waitSignal(worker.signals.finished, timeout=5000):
        _start(worker)
    qtbot.wait(50)

    assert finished == ["ok"]
    assert failed == []
    assert cancelled == []
