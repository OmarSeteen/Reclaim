"""Tests for ui/workers.py -- the QThreadPool wiring every page's on_* handler
submits jobs through via PageBase._run. Exercises the signal contract
(result / error / cancelled / finished / progress) that wiring depends on.

Runs under the offscreen Qt platform; skipped where PySide6 isn't installed.
No network, no secrets, no tkinter.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication

    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from _support import pump_until as _pump_until


@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class TestWorkersSubmit(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.pool = QThreadPool.globalInstance()

    def _run(self, make_job, **callbacks):
        from Reclaim.ui import workers

        finished = {"done": False}

        def on_finished():
            finished["done"] = True

        workers.submit(self.pool, make_job, on_finished=on_finished, **callbacks)
        self.assertTrue(
            _pump_until(self.app, lambda: finished["done"]),
            "worker never signalled finished",
        )

    def test_successful_job_delivers_result_then_finished(self):
        results = []
        self._run(lambda progress: (lambda: 42), on_result=results.append)
        self.assertEqual(results, [42])

    def test_job_exception_delivers_error_not_result(self):
        results = []
        errors = []

        def make_job(progress):
            def job():
                raise ValueError("boom")

            return job

        self._run(make_job, on_result=results.append, on_error=errors.append)
        self.assertEqual(errors, ["boom"])
        self.assertEqual(results, [])

    def test_cancelled_job_delivers_cancelled_not_error(self):
        from Reclaim.fsutils import Cancelled

        cancelled = []
        errors = []

        def make_job(progress):
            def job():
                raise Cancelled()

            return job

        self._run(
            make_job,
            on_cancelled=lambda: cancelled.append(True),
            on_error=errors.append,
        )
        self.assertEqual(cancelled, [True])
        self.assertEqual(errors, [])

    def test_progress_is_forwarded_from_inside_the_job(self):
        seen = []

        def make_job(progress):
            def job():
                progress("a")
                progress("b")
                return "done"

            return job

        self._run(make_job, on_progress=seen.append)
        self.assertEqual(seen, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
