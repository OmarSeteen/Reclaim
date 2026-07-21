"""Tests for winapi.py -- the one module allowed to touch the Windows shell.

This is the project's guarded, irreversible-operations boundary, so tests
here deliberately never trigger a *real* destructive shell call:
`empty_recycle_bin` and `remove_windows_old` are only exercised through their
no-op/absent-target guards (forced via monkeypatched config, regardless of
the machine actually running the tests), never SHEmptyRecycleBinW or a real
takeown/rd chain -- doing so for real would empty whoever runs the suite's
actual Recycle Bin or touch a real Windows.old. `send_to_recycle_bin` is
exercised for real: it only ever touches files the test itself created, and
recycling is exactly the undoable operation the module exists to provide.

No network, no secrets, no tkinter.
"""

import os
import tempfile
import unittest

from Reclaim import config, winapi


class TestIsReparsePoint(unittest.TestCase):
    def test_ordinary_directory_is_not_a_reparse_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(winapi._is_reparse_point(tmp))

    def test_missing_path_is_not_a_reparse_point(self):
        self.assertFalse(
            winapi._is_reparse_point(
                os.path.join(tempfile.gettempdir(), "does-not-exist-xyz")
            )
        )


class TestIsAdmin(unittest.TestCase):
    def test_returns_a_bool(self):
        self.assertIsInstance(winapi.is_admin(), bool)


class TestSendToRecycleBin(unittest.TestCase):
    def test_empty_input_short_circuits_without_freeing_anything(self):
        self.assertEqual(winapi.send_to_recycle_bin([]), 0)

    def test_nonexistent_paths_are_dropped_before_any_shell_call(self):
        missing = os.path.join(tempfile.gettempdir(), "does-not-exist-xyz.tmp")
        self.assertEqual(winapi.send_to_recycle_bin([missing]), 0)

    def test_moves_a_real_temp_file_and_reports_its_size(self):
        # The one real, non-guarded op this module performs: recycling (never
        # a hard delete) a file the test itself owns.
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "junk.tmp")
            with open(target, "wb") as fh:
                fh.write(b"x" * 4096)
            freed = winapi.send_to_recycle_bin([target])
            self.assertEqual(freed, 4096)
            self.assertFalse(os.path.exists(target))


class TestGuardedNoOps(unittest.TestCase):
    """Force config.IS_WINDOWS both ways so these guards are checked
    regardless of which OS actually runs the suite -- without ever letting
    execution reach the real (destructive or elevated) branch beneath them.
    """

    def setUp(self):
        self._is_windows = config.IS_WINDOWS

    def tearDown(self):
        config.IS_WINDOWS = self._is_windows

    def test_empty_recycle_bin_noop_off_windows(self):
        config.IS_WINDOWS = False
        self.assertEqual(winapi.empty_recycle_bin(), 0)

    def test_recycle_bin_info_noop_off_windows(self):
        config.IS_WINDOWS = False
        self.assertEqual(winapi.recycle_bin_info(), (0, 0))

    def test_run_maintenance_command_noop_off_windows(self):
        config.IS_WINDOWS = False
        self.assertFalse(winapi.run_maintenance_command(["whoami"]))

    def test_open_ntfs_volume_noop_off_windows(self):
        config.IS_WINDOWS = False
        self.assertIsNone(winapi.open_ntfs_volume("C:"))

    def test_relaunch_as_admin_noop_off_windows(self):
        config.IS_WINDOWS = False
        self.assertIsNone(winapi.relaunch_as_admin())  # must not sys.exit()

    def test_remove_windows_old_true_when_target_absent(self):
        # Force the "on Windows" branch but point SYSTEM_DRIVE at an empty
        # temp dir, so the function's own `not os.path.isdir(target)` early
        # return fires before any subprocess (takeown/icacls/rd) ever runs.
        config.IS_WINDOWS = True
        saved_drive = config.SYSTEM_DRIVE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                config.SYSTEM_DRIVE = tmp + os.sep
                self.assertTrue(winapi.remove_windows_old())
                self.assertFalse(os.path.isdir(os.path.join(tmp, "Windows.old")))
        finally:
            config.SYSTEM_DRIVE = saved_drive


if __name__ == "__main__":
    unittest.main()
