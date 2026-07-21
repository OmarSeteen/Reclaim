"""Tests for locations.py -- the safety allowlist. No network, no secrets.

`_existing_dirs` is the single filter every resolver in this file funnels
through, so its glob/allow_globs/existence behavior gets the most direct
coverage here. The rest of the file gets a sweep: every resolver must return
only paths that exist right now on real disk, since a path this module
didn't produce is a path the app can never touch (see the safety invariant
in CLAUDE.md).
"""

import os
import tempfile
import unittest

from _support import redirect_app_data

from Reclaim import locations, settings

DIR_LIST_RESOLVERS = [
    locations.temp_dirs,
    locations.browser_cache_dirs,
    locations.app_cache_dirs,
    locations.dev_cache_dirs,
    locations.windows_update_dirs,
    locations.delivery_optimization_dirs,
    locations.wer_dirs,
    locations.windows_log_dirs,
]

FILE_LIST_RESOLVERS = [
    locations.system_dump_files,
    locations.thumbnail_cache_files,
]


class TestExistingDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.real = os.path.join(self.tmp, "real")
        os.makedirs(self.real)

    def test_drops_missing_and_falsy_paths(self):
        out = locations._existing_dirs(
            [self.real, os.path.join(self.tmp, "missing"), "", None]
        )
        self.assertEqual(out, [self.real])

    def test_drops_files_a_directory_check_must_reject(self):
        f = os.path.join(self.tmp, "not_a_dir.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("x")
        self.assertEqual(locations._existing_dirs([f]), [])

    def test_expands_globs_by_default(self):
        os.makedirs(os.path.join(self.tmp, "profileA", "Cache"))
        os.makedirs(os.path.join(self.tmp, "profileB", "Cache"))
        pattern = os.path.join(self.tmp, "*", "Cache")
        out = locations._existing_dirs([pattern])
        self.assertEqual(len(out), 2)
        for p in out:
            self.assertTrue(os.path.isdir(p))

    def test_literal_star_is_not_expanded_when_globs_disallowed(self):
        # A user-supplied custom entry passes allow_globs=False: a stray '*'
        # must be treated as a literal (nonexistent) path, never expanded
        # into every matching profile folder.
        os.makedirs(os.path.join(self.tmp, "profileA", "Cache"))
        os.makedirs(os.path.join(self.tmp, "profileB", "Cache"))
        pattern = os.path.join(self.tmp, "*", "Cache")
        self.assertEqual(locations._existing_dirs([pattern], allow_globs=False), [])


class TestResolversReturnOnlyWhatExists(unittest.TestCase):
    """A minimal regression net: whatever these resolvers return today must
    still be real, existing paths -- the one guarantee locations.py exists
    to provide. Doesn't assert *which* paths (that's host-machine-dependent),
    only that nothing nonexistent or bogus slips through."""

    def test_dir_resolvers_return_only_existing_directories(self):
        for fn in DIR_LIST_RESOLVERS:
            for p in fn():
                self.assertTrue(
                    os.path.isdir(p), f"{fn.__name__} returned missing dir {p!r}"
                )

    def test_file_resolvers_return_only_existing_files(self):
        for fn in FILE_LIST_RESOLVERS:
            for p in fn():
                self.assertTrue(
                    os.path.isfile(p), f"{fn.__name__} returned missing file {p!r}"
                )

    def test_windows_old_dir_is_empty_or_a_real_directory(self):
        d = locations.windows_old_dir()
        if d:
            self.assertTrue(os.path.isdir(d))

    def test_downloads_dir_is_empty_or_a_real_directory(self):
        d = locations.downloads_dir()
        if d:
            self.assertTrue(os.path.isdir(d))


class TestCustomCleanDirs(unittest.TestCase):
    """custom_clean_dirs is the one resolver driven by user input (via
    settings), so it's the one place a hostile/careless entry could try to
    widen the allowlist -- worth its own direct coverage."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cm = redirect_app_data(self.tmp)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_returns_only_existing_custom_entries(self):
        real = os.path.join(self.tmp, "keep")
        os.makedirs(real)
        missing = os.path.join(self.tmp, "gone")
        settings.save({"custom_clean_dirs": [real, missing]})
        self.assertEqual(locations.custom_clean_dirs(), [real])

    def test_custom_entry_wildcard_is_never_expanded(self):
        os.makedirs(os.path.join(self.tmp, "a", "Documents"))
        os.makedirs(os.path.join(self.tmp, "b", "Documents"))
        pattern = os.path.join(self.tmp, "*", "Documents")
        settings.save({"custom_clean_dirs": [pattern]})
        # The literal folder named '*' doesn't exist, so the pattern is
        # dropped -- not silently fanned out across every profile.
        self.assertEqual(locations.custom_clean_dirs(), [])

    def test_no_settings_file_yields_empty_list(self):
        self.assertEqual(locations.custom_clean_dirs(), [])


if __name__ == "__main__":
    unittest.main()
