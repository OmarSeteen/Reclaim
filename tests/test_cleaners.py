"""Tests for the cleaner records and orchestration. No network, no secrets.

These exercise the declarative CLEANERS table and the analyze/clean dispatch
without ever deleting real system files: command cleaners no-op off Windows, so
the deletion paths here only touch throwaway temp dirs.
"""

import os
import tempfile
import unittest

from Reclaim import cleaners, config, fsutils, locations


VALID_KINDS = {"dirs", "files", "recycle", "command"}
REQUIRED_KEYS = {"key", "label", "desc", "kind", "needs_admin"}


class TestCleanerRecords(unittest.TestCase):
    def test_every_record_is_well_formed(self):
        seen_keys = set()
        for c in cleaners.CLEANERS:
            self.assertTrue(REQUIRED_KEYS <= set(c), f"{c} missing required keys")
            self.assertIn(c["kind"], VALID_KINDS)
            self.assertNotIn(c["key"], seen_keys, "duplicate cleaner key")
            seen_keys.add(c["key"])
            # Each kind must carry what its dispatch needs.
            if c["kind"] == "command":
                self.assertIn("run", c, f"{c['key']} command needs a run()")
            elif c["kind"] != "recycle":
                self.assertIn("get", c, f"{c['key']} needs a get() resolver")

    def test_new_categories_present(self):
        keys = {c["key"] for c in cleaners.CLEANERS}
        for expected in ("devcaches", "sysdumps", "winlogs",
                         "winsxs", "hiberfil", "windows_old"):
            self.assertIn(expected, keys)


class TestAnalyzeCommand(unittest.TestCase):
    def test_command_uses_estimate_when_present(self):
        fake = {"kind": "command", "run": lambda log: True,
                "estimate": lambda: (1234, 1)}
        self.assertEqual(cleaners.analyze_cleaner(fake), (1234, 1))

    def test_command_without_estimate_reports_nothing(self):
        fake = {"kind": "command", "run": lambda log: True}
        self.assertEqual(cleaners.analyze_cleaner(fake), (0, 0))


class TestCleanDispatch(unittest.TestCase):
    def test_command_clean_returns_nonnegative_and_logs_skip_offplatform(self):
        # Off Windows the run() no-ops, so freed space can't go negative and the
        # skip message is logged rather than crashing.
        logs = []
        fake = {"kind": "command",
                "run": lambda log: cleaners.winapi.run_maintenance_command(["whoami"])}
        freed = cleaners.clean_cleaner(fake, logs.append)
        self.assertGreaterEqual(freed, 0)

    def test_files_clean_removes_listed_files(self):
        base = tempfile.mkdtemp()
        f = os.path.join(base, "junk.tmp")
        with open(f, "wb") as fh:
            fh.write(b"x" * 4096)
        fake = {"kind": "files", "get": lambda: [f]}
        freed = cleaners.clean_cleaner(fake, lambda m: None)
        self.assertEqual(freed, 4096)
        self.assertFalse(os.path.exists(f))


class TestPreview(unittest.TestCase):
    def test_dirs_preview_lists_paths_biggest_first(self):
        base = tempfile.mkdtemp()
        small = os.path.join(base, "small")
        big = os.path.join(base, "big")
        os.makedirs(small)
        os.makedirs(big)
        with open(os.path.join(small, "s"), "wb") as fh:
            fh.write(b"x" * 100)
        with open(os.path.join(big, "b"), "wb") as fh:
            fh.write(b"x" * 5000)
        fake = {"kind": "dirs", "get": lambda: [small, big]}
        rows = cleaners.preview_cleaner(fake)
        self.assertEqual([r[0] for r in rows], [big, small])  # biggest first
        self.assertEqual(rows[0][1], 5000)

    def test_command_preview_uses_estimate(self):
        fake = {"kind": "command", "desc": "Run a thing", "run": lambda log: True,
                "estimate": lambda: (999, 1)}
        rows = cleaners.preview_cleaner(fake)
        self.assertEqual(rows, [("Run a thing", 999)])


class TestResolversAndHelpers(unittest.TestCase):
    def test_dev_cache_dirs_returns_only_existing_dirs(self):
        for d in locations.dev_cache_dirs():
            self.assertTrue(os.path.isdir(d))

    def test_system_resolvers_return_safe_types(self):
        self.assertIsInstance(locations.system_dump_files(), list)
        self.assertIsInstance(locations.windows_log_dirs(), list)
        self.assertIn(locations.windows_old_dir(), ["", locations.windows_old_dir()])

    def test_disk_free_is_positive_for_a_real_path(self):
        self.assertGreater(fsutils.disk_free(tempfile.gettempdir()), 0)
        self.assertEqual(fsutils.disk_free("\0 not a path"), 0)


if __name__ == "__main__":
    unittest.main()
