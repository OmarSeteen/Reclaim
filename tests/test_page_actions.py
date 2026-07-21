"""Exercises the click -> confirm -> clean path through the real MainWindow
host wiring (PageBase._run / workers.submit), the layer test_gui_smoke.py
doesn't reach: it only checks the window constructs, never that pressing a
delete/clean button actually confirms and deletes.

`_ask` / `chrome.notify` are monkeypatched per test to avoid a real blocking
modal (frameless dialogs use dlg.exec(), which never returns headless).
Everything below that -- selection, the confirm gate, the background job,
winapi.send_to_recycle_bin -- runs for real, but only ever against throwaway
temp files: CleanupPage's real CLEANERS (which resolve real cache dirs) is
swapped for one fake "files" entry before the window builds its cards, so
"Clean selected" can never touch anything outside the test's temp dir.

No network, no secrets, no tkinter. Settings/history are redirected into the
temp dir (see test_settings.py) so record_cleanup() never touches the real
per-user AppData file.
"""

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTreeWidgetItem

    HAS_QT = True
except Exception:
    HAS_QT = False

from Reclaim import cleaners as cleaners_mod

if HAS_QT:
    from _support import drain as _drain
    from _support import make_window, redirect_app_data


def _fake_files_cleaner(get_paths):
    return {
        "key": "test_fake",
        "label": "Test fake cache",
        "desc": "Throwaway cleaner for the test.",
        "kind": "files",
        "needs_admin": False,
        "get": get_paths,
    }


@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class TestPageActions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cm = redirect_app_data(self.tmp)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self._saved_cleaners = cleaners_mod.CLEANERS

    def tearDown(self):
        cleaners_mod.CLEANERS = self._saved_cleaners

    def _make_window(self):
        app, window = make_window()
        self.addCleanup(window.close)
        return app, window

    def _junk_file(self):
        junk_dir = os.path.join(self.tmp, "junk")
        os.makedirs(junk_dir, exist_ok=True)
        junk = os.path.join(junk_dir, "junk.tmp")
        with open(junk, "wb") as fh:
            fh.write(b"x" * 4096)
        return junk

    # -- Cleanup page: "Clean selected" ------------------------------------ #

    def test_clean_selected_confirmed_deletes_only_the_fake_cleaners_files(self):
        junk = self._junk_file()
        cleaners_mod.CLEANERS = [_fake_files_cleaner(lambda: [junk])]
        app, window = self._make_window()
        page = window.pages[0]  # CleanupPage
        page.checks["test_fake"].setChecked(True)
        page._ask = lambda title, text: True

        page.on_clean()
        _drain(app, window)

        self.assertFalse(os.path.exists(junk))

    def test_clean_selected_declined_keeps_the_file(self):
        junk = self._junk_file()
        cleaners_mod.CLEANERS = [_fake_files_cleaner(lambda: [junk])]
        app, window = self._make_window()
        page = window.pages[0]
        page.checks["test_fake"].setChecked(True)
        page._ask = lambda title, text: False

        page.on_clean()
        _drain(app, window)

        self.assertTrue(os.path.exists(junk))
        self.assertFalse(window.is_busy())

    # -- Old files page: "Move selected to Recycle Bin" -------------------- #

    def _old_file(self):
        target = os.path.join(self.tmp, "old.txt")
        with open(target, "wb") as fh:
            fh.write(b"x" * 2048)
        return target

    def test_old_files_delete_confirmed_sends_to_recycle_bin(self):
        app, window = self._make_window()
        page = window.pages[3]  # OldFilesPage
        target = self._old_file()
        page.path.setText(self.tmp)  # keeps the post-delete re-scan hermetic
        page._add_old_row(2048, 200 * 86400, target)
        page.table.item(0, 0).setCheckState(Qt.Checked)
        page._ask = lambda title, text: True

        page.on_delete()
        _drain(app, window)

        self.assertFalse(os.path.exists(target))

    def test_old_files_delete_declined_keeps_file(self):
        app, window = self._make_window()
        page = window.pages[3]
        target = self._old_file()
        page.path.setText(self.tmp)
        page._add_old_row(2048, 200 * 86400, target)
        page.table.item(0, 0).setCheckState(Qt.Checked)
        page._ask = lambda title, text: False

        page.on_delete()
        _drain(app, window)

        self.assertTrue(os.path.exists(target))
        self.assertFalse(window.is_busy())

    def test_old_files_delete_with_nothing_selected_notifies_and_skips(self):
        app, window = self._make_window()
        page = window.pages[3]
        from Reclaim.ui import pages as pages_mod

        calls = []
        original_notify = pages_mod.chrome.notify
        pages_mod.chrome.notify = lambda *a, **k: calls.append(a)
        try:
            page.on_delete()
        finally:
            pages_mod.chrome.notify = original_notify

        self.assertEqual(len(calls), 1)
        self.assertFalse(window.is_busy())

    # -- Duplicates page: "Move selected to Recycle Bin" ------------------- #

    def test_duplicates_delete_confirmed_sends_to_recycle_bin(self):
        app, window = self._make_window()
        page = window.pages[2]  # DuplicatesPage
        page.path.setText(self.tmp)  # keeps the post-delete re-scan hermetic
        target = self._old_file()
        head = QTreeWidgetItem(page.tree, ["group", "1 file", "2.0 KB"])
        child = QTreeWidgetItem(head, [os.path.basename(target), "2.0 KB"])
        child.setData(0, Qt.UserRole, target)
        child.setCheckState(0, Qt.Checked)
        page._ask = lambda title, text: True

        page.on_delete()
        _drain(app, window)

        self.assertFalse(os.path.exists(target))


# ----------------------------------------------------------------------------- #
#  Disk Analyzer: scan -> tree/treemap population -> drill-down
# ----------------------------------------------------------------------------- #
@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class TestAnalyzerPage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cm = redirect_app_data(self.tmp)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def _make_window(self):
        app, window = make_window()
        self.addCleanup(window.close)
        return app, window

    def test_scan_populates_tree_and_treemap_and_drills_down(self):
        sub = os.path.join(self.tmp, "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "f.bin"), "wb") as fh:
            fh.write(b"x" * 8192)

        app, window = self._make_window()
        page = window.pages[1]  # AnalyzerPage
        page.drive.addItem(self.tmp)
        page.drive.setCurrentIndex(page.drive.count() - 1)

        page.on_scan()
        _drain(app, window)

        base = os.path.abspath(self.tmp)
        self.assertEqual(page.tree.topLevelItemCount(), 1)
        self.assertIn(base, page.dir_sizes)
        self.assertGreaterEqual(page.dir_sizes[base], 8192)
        self.assertFalse(page.tm_up.isEnabled())  # landed on the root node

        sub_path = os.path.join(base, "sub")
        page._on_tm_nav(sub_path)  # simulates clicking into the sub-tile
        self.assertTrue(page.tm_up.isEnabled())
        self.assertIn(sub_path, page.tm_label.text())


if __name__ == "__main__":
    unittest.main()
