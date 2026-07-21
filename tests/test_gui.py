"""Tests for gui.py's crash handler -- the top-level safety net for anything
that reaches the event loop uncaught. Without it, an unhandled exception in
the --windowed build (no console) just kills the app silently.

`_write_crash_log` is pure and tested directly. `_install_crash_handler`'s
`QMessageBox.critical` call is monkeypatched to avoid a real blocking modal
(dlg.exec() never returns headless) -- everything else (log write, chaining
to sys.__excepthook__) runs for real.

No network, no secrets, no tkinter.
"""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401

    HAS_QT = True
except Exception:
    HAS_QT = False

from _support import redirect_app_data

from Reclaim import gui


class TestWriteCrashLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cm = redirect_app_data(self.tmp)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def _raise(self):
        raise ValueError("boom")

    def test_writes_traceback_and_returns_path(self):
        try:
            self._raise()
        except ValueError:
            path = gui._write_crash_log(*sys.exc_info())

        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("ValueError: boom", text)
        self.assertIn("_raise", text)

    def test_appends_rather_than_overwrites(self):
        try:
            self._raise()
        except ValueError:
            gui._write_crash_log(*sys.exc_info())
        try:
            self._raise()
        except ValueError:
            path = gui._write_crash_log(*sys.exc_info())

        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count("ValueError: boom"), 2)


@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class TestInstallCrashHandler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cm = redirect_app_data(self.tmp)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self._saved_excepthook = sys.excepthook
        self._saved_dunder_excepthook = sys.__excepthook__
        self.addCleanup(setattr, sys, "excepthook", self._saved_excepthook)
        self.addCleanup(setattr, sys, "__excepthook__", self._saved_dunder_excepthook)

    def test_handler_logs_shows_dialog_and_chains_to_default_hook(self):
        from PySide6.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication([])

        dialog_calls = []
        original_critical = QMessageBox.critical
        self.addCleanup(setattr, QMessageBox, "critical", original_critical)
        QMessageBox.critical = staticmethod(lambda *a, **k: dialog_calls.append((a, k)))

        chained = []
        sys.__excepthook__ = lambda *args: chained.append(args)

        gui._install_crash_handler()
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

        self.assertEqual(len(dialog_calls), 1)
        self.assertEqual(len(chained), 1)
        log_path = os.path.join(self.tmp, "crash.log")
        with open(log_path, encoding="utf-8") as fh:
            self.assertIn("RuntimeError: kaboom", fh.read())


if __name__ == "__main__":
    unittest.main()
