"""Exercises MainWindow's footer controls: theme toggle, language switch, and
the Settings dialog's folder-list editor (custom_clean_dirs / excluded_dirs).

`_open_settings`/`_open_history` themselves call dlg.exec() (a real blocking
modal, never returns headless), so these tests call the underlying methods
directly (`_toggle_theme`, `_on_language`, `_list_editor`) instead of opening
the dialog. `_on_language` calls chrome.notify (also blocking); monkeypatched
per test like test_page_actions.py does for `_ask`. `_list_editor`'s "Add..."
button calls the native QFileDialog.getExistingDirectory, also monkeypatched.

No network, no secrets, no tkinter. Settings are redirected into a temp dir
(see test_settings.py) so nothing here touches the real per-user AppData file.
"""

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QFileDialog

    HAS_QT = True
except Exception:
    HAS_QT = False

from Reclaim import i18n, settings

if HAS_QT:
    from _support import make_window, redirect_app_data


@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class TestShellControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cm = redirect_app_data(self.tmp)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.addCleanup(i18n.set_language, i18n.get_language())

    def _make_window(self):
        app, window = make_window()
        self.addCleanup(window.close)
        return app, window

    def test_theme_toggle_flips_and_persists(self):
        from Reclaim.ui import theme as theme_mod

        _app, window = self._make_window()
        start = theme_mod.active_theme()

        window._toggle_theme()

        self.assertNotEqual(theme_mod.active_theme(), start)
        self.assertEqual(settings.load().get("theme"), theme_mod.active_theme())
        self.assertEqual(window.theme_btn.text(), window._theme_label())

    def test_language_switch_updates_i18n_and_persists(self):
        from Reclaim.ui import shell as shell_mod

        _app, window = self._make_window()
        calls = []
        original_notify = shell_mod.chrome.notify
        self.addCleanup(setattr, shell_mod.chrome, "notify", original_notify)
        shell_mod.chrome.notify = lambda *a, **k: calls.append(a)

        window._on_language("ar")

        self.assertEqual(i18n.get_language(), "ar")
        self.assertTrue(i18n.is_rtl())
        self.assertEqual(settings.load().get("language"), "ar")
        self.assertEqual(window.lang_btn.text(), i18n.LANGUAGES["ar"])
        self.assertEqual(len(calls), 1)  # "restart to apply" notice shown

    def test_language_switch_to_same_language_is_a_noop(self):
        from Reclaim.ui import shell as shell_mod

        _app, window = self._make_window()
        calls = []
        original_notify = shell_mod.chrome.notify
        self.addCleanup(setattr, shell_mod.chrome, "notify", original_notify)
        shell_mod.chrome.notify = lambda *a, **k: calls.append(a)

        window._on_language(i18n.get_language())  # already "en"

        self.assertEqual(calls, [])
        self.assertIsNone(settings.load().get("language"))

    def test_settings_list_editor_add_and_remove_persist(self):
        _app, window = self._make_window()
        chosen = self.tmp
        original_get_dir = QFileDialog.getExistingDirectory
        self.addCleanup(setattr, QFileDialog, "getExistingDirectory", original_get_dir)
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: chosen)

        wrap = window._list_editor("custom_clean_dirs")
        lst = wrap.itemAt(0).widget()
        btn_col = wrap.itemAt(1).layout()
        add_btn = btn_col.itemAt(0).widget()
        rm_btn = btn_col.itemAt(1).widget()

        add_btn.click()
        self.assertEqual(lst.count(), 1)
        self.assertEqual(lst.item(0).text(), chosen)
        self.assertEqual(settings.load().get("custom_clean_dirs"), [chosen])

        lst.item(0).setSelected(True)
        rm_btn.click()

        self.assertEqual(lst.count(), 0)
        self.assertEqual(settings.load().get("custom_clean_dirs"), [])

    def test_settings_list_editor_skips_duplicate_entries(self):
        _app, window = self._make_window()
        chosen = self.tmp
        original_get_dir = QFileDialog.getExistingDirectory
        self.addCleanup(setattr, QFileDialog, "getExistingDirectory", original_get_dir)
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: chosen)

        wrap = window._list_editor("excluded_dirs")
        lst = wrap.itemAt(0).widget()
        add_btn = wrap.itemAt(1).layout().itemAt(0).widget()

        add_btn.click()
        add_btn.click()  # picking the same folder twice must not duplicate it

        self.assertEqual(lst.count(), 1)
        self.assertEqual(settings.load().get("excluded_dirs"), [chosen])


if __name__ == "__main__":
    unittest.main()
