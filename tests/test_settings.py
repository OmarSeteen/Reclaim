"""Tests for the settings/history store. No network, no secrets.

We redirect the module's file paths (config attributes, read at call time) into a
temp dir so the real per-user settings are never touched.
"""

import os
import tempfile
import unittest

from Reclaim import config, settings


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = (config.APP_DATA_DIR, config.SETTINGS_FILE,
                       config.HISTORY_FILE, config.HISTORY_MAX_LINES)
        config.APP_DATA_DIR = self.tmp
        config.SETTINGS_FILE = os.path.join(self.tmp, "settings.json")
        config.HISTORY_FILE = os.path.join(self.tmp, "history.log")

    def tearDown(self):
        (config.APP_DATA_DIR, config.SETTINGS_FILE,
         config.HISTORY_FILE, config.HISTORY_MAX_LINES) = self._saved

    def test_load_defaults_to_empty_when_absent(self):
        self.assertEqual(settings.load(), {})

    def test_save_then_load_roundtrips(self):
        settings.save({"scan_path": "C:\\", "selected": ["temp", "apps"]})
        data = settings.load()
        self.assertEqual(data["scan_path"], "C:\\")
        self.assertEqual(data["selected"], ["temp", "apps"])

    def test_corrupt_file_is_treated_as_empty(self):
        with open(config.SETTINGS_FILE, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json")
        self.assertEqual(settings.load(), {})

    def test_history_records_and_reads_back(self):
        self.assertEqual(settings.history_text(), "No cleanup history yet.")
        settings.record_cleanup("Freed 1.0 GB.")
        text = settings.history_text()
        self.assertIn("Freed 1.0 GB.", text)

    def test_clear_history(self):
        settings.record_cleanup("Freed 1.0 GB.")
        self.assertIn("Freed", settings.history_text())
        settings.clear_history()
        self.assertEqual(settings.history_text(), "No cleanup history yet.")

    def test_history_is_capped(self):
        config.HISTORY_MAX_LINES = 5
        for i in range(20):
            settings.record_cleanup(f"run {i}")
        with open(config.HISTORY_FILE, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        self.assertEqual(len(lines), 5)            # bounded
        self.assertIn("run 19", lines[-1])         # newest kept
        self.assertNotIn("run 0", "".join(lines))  # oldest dropped


if __name__ == "__main__":
    unittest.main()
