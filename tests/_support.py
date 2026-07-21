"""Shared test-only helpers. Not a test module itself (unittest discover only
loads test*.py), so nothing here runs on its own.
"""

import os
import time
from contextlib import contextmanager

from Reclaim import config


@contextmanager
def redirect_app_data(tmp_dir):
    """Point settings/history at `tmp_dir` for the duration of the block, so
    settings.save()/record_cleanup() never touch the real per-user AppData
    file. Restores the originals on exit even if the block raises.
    """
    saved = (config.APP_DATA_DIR, config.SETTINGS_FILE, config.HISTORY_FILE)
    config.APP_DATA_DIR = tmp_dir
    config.SETTINGS_FILE = os.path.join(tmp_dir, "settings.json")
    config.HISTORY_FILE = os.path.join(tmp_dir, "history.log")
    try:
        yield
    finally:
        (config.APP_DATA_DIR, config.SETTINGS_FILE, config.HISTORY_FILE) = saved


def pump_until(app, predicate, timeout=5):
    """Process Qt events until `predicate()` is true or `timeout` seconds
    pass. Returns whether it settled."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
    return False


def drain(app, window, timeout=10):
    """Pump until the worker pool and window go idle. Doesn't touch
    cancel_event: a job a caller just submitted (e.g. CleanupPage's clean
    job, which checks cancel_event.is_set() per cleaner) must not be raced
    and cancelled by this call.
    """
    from PySide6.QtCore import QThreadPool

    pool = QThreadPool.globalInstance()
    pump_until(
        app,
        lambda: pool.activeThreadCount() == 0 and not window.is_busy(),
        timeout,
    )
    app.processEvents()


def settle(app, window, clear_cancel=False):
    """Cancel and drain a pending job (e.g. the auto-analyze right after
    MainWindow construction), then optionally clear cancel_event so a later
    action isn't pre-cancelled.
    """
    window.cancel_event.set()
    drain(app, window)
    if clear_cancel:
        window.cancel_event.clear()


def make_window():
    """Construct a real MainWindow, cancel+drain its initial auto-analyze, and
    return (app, window). Caller must redirect config's app-data paths first
    (see redirect_app_data) and close the window (e.g. self.addCleanup).
    """
    from PySide6.QtWidgets import QApplication

    from Reclaim.ui import theme
    from Reclaim.ui.shell import MainWindow

    app = QApplication.instance() or QApplication([])
    theme.apply(app, "dark", False)
    window = MainWindow()
    window.show()
    settle(app, window, clear_cancel=True)
    return app, window
