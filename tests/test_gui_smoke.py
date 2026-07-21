"""Smoke test: the PySide6 MainWindow constructs and processes events headlessly.

Guarded with skipUnless so the stdlib-only logic tests still pass on a machine
without PySide6. Runs under the offscreen platform so no real window appears.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from _support import drain


@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class TestGuiSmoke(unittest.TestCase):
    def test_mainwindow_constructs(self):
        from Reclaim.ui import theme
        from Reclaim.ui.shell import MainWindow

        app = QApplication.instance() or QApplication([])
        theme.apply(app, "dark", False)
        window = MainWindow()
        window.show()
        self.assertEqual(len(window.pages), 4)  # all feature pages present

        # The Cleanup page auto-analyzes on launch; cancel it so the test stays
        # fast and deterministic, then pump until the worker settles.
        window.cancel_event.set()
        drain(app, window)
        self.assertFalse(window.is_busy())  # settled, no stuck busy state
        window.close()


if __name__ == "__main__":
    unittest.main()
