"""Run heavy logic off the UI thread, the Qt way.

This mirrors the discipline the Tkinter UI had in `_run_async`: nothing that
touches the filesystem runs on the GUI thread, and a cancel flag stops long
scans. Here that's a QThreadPool + QRunnable whose signals (always delivered on
the UI thread by Qt) report result / error / cancelled / finished / progress.

The logic layer already speaks this language: scan functions take an
`on_progress` callback and a `should_cancel` predicate and raise
`fsutils.Cancelled`. So `submit` hands the job a thread-safe progress emitter,
and the page wires a threading.Event's `is_set` as `should_cancel`.
"""

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..fsutils import Cancelled


class WorkerSignals(QObject):
    """Cross-thread signals for one job. Qt marshals these to the UI thread."""
    result = Signal(object)      # the job's return value
    error = Signal(str)          # an unexpected failure (message)
    cancelled = Signal()         # the user stopped it (clean, not an error)
    finished = Signal()          # always emitted last, success or not
    progress = Signal(object)    # forwarded from the job's on_progress


# Keeps live workers referenced until they finish. Without this the Python
# Worker (and its WorkerSignals QObject) can be garbage-collected the moment
# `submit` returns — the job still runs on the C++ side, but its queued
# result/finished signals are delivered to a dead object and silently lost.
_alive = set()


class Worker(QRunnable):
    """A no-argument job run on the thread pool. Build it via `submit`."""

    def __init__(self, job=None):
        super().__init__()
        # We manage lifetime via `_alive`; let the pool not delete us out from
        # under the Python object.
        self.setAutoDelete(False)
        self.signals = WorkerSignals()
        self.job = job

    def _emit(self, signal, *args):
        # Emitting can fail with "Signal source has been deleted" if the app is
        # closing and the C++ signals object is already gone — there's nothing
        # left to report to, so swallow it rather than spam the worker thread.
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    @Slot()
    def run(self):
        try:
            result = self.job()
        except Cancelled:
            self._emit(self.signals.cancelled)
        except Exception as exc:        # a worker crash must never kill the app
            self._emit(self.signals.error, str(exc))
        else:
            self._emit(self.signals.result, result)
        finally:
            self._emit(self.signals.finished)


def submit(pool, make_job, on_result=None, on_error=None,
           on_cancelled=None, on_finished=None, on_progress=None):
    """Start `make_job(progress_emit)` on the pool and wire its callbacks.

    `make_job` is a factory that receives a thread-safe `progress_emit` callable
    and returns the actual no-arg job; jobs that don't report progress simply
    ignore the argument. This indirection is what lets the job emit progress
    through the worker's own signal (which exists only after the worker does).
    Returns the Worker so the caller can keep a reference if needed.
    """
    worker = Worker()
    s = worker.signals
    for signal, callback in (
        (s.result, on_result), (s.error, on_error),
        (s.cancelled, on_cancelled), (s.finished, on_finished),
        (s.progress, on_progress),
    ):
        if callback is not None:
            signal.connect(callback)
    # Hold a reference until the job finishes, then release it (the signal has
    # been delivered by then, so it's safe to let the worker be collected).
    _alive.add(worker)
    s.finished.connect(lambda: _alive.discard(worker))

    def progress(*args):    # guarded like Worker._emit, for use inside the job
        try:
            s.progress.emit(*args)
        except RuntimeError:
            pass

    worker.job = make_job(progress)
    pool.start(worker)
    return worker
