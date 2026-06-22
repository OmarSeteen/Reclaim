"""Tests for fsutils. No network, no secrets, no tkinter — pure filesystem.

Each test builds a throwaway tree in a temp dir so it can run anywhere.
"""

import os
import tempfile
import time
import unittest

from Reclaim import fsutils


class TestFormatting(unittest.TestCase):
    def test_human_units(self):
        self.assertEqual(fsutils.human(0), "0.0 B")
        self.assertEqual(fsutils.human(1536), "1.5 KB")
        self.assertEqual(fsutils.human(5 * 1024 ** 3), "5.0 GB")

    def test_months_old(self):
        day = 86400
        self.assertEqual(fsutils.months_old(10 * day), "<1 month")
        self.assertEqual(fsutils.months_old(45 * day), "1 month")
        self.assertEqual(fsutils.months_old(7 * 30 * day), "7 months")
        # always months, never years (a 2-year file reads as months)
        self.assertEqual(fsutils.months_old(2 * 365 * day), "24 months")


class TestSizing(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "sub"))
        for i in range(3):
            with open(os.path.join(self.base, f"f{i}.bin"), "wb") as fh:
                fh.write(b"x" * 1024 * 100)  # 100 KB each
        with open(os.path.join(self.base, "sub", "big.bin"), "wb") as fh:
            fh.write(b"y" * 1024 * 500)      # 500 KB

    def test_dir_size_and_count(self):
        self.assertEqual(fsutils.dir_size(self.base), (3 * 100 + 500) * 1024)
        self.assertEqual(fsutils.dir_count(self.base), 4)

    def test_clean_keeps_root_but_empties_it(self):
        freed = fsutils.clean_dir_contents(self.base, lambda m: None)
        self.assertEqual(freed, (3 * 100 + 500) * 1024)
        self.assertTrue(os.path.isdir(self.base))      # folder preserved
        self.assertEqual(os.listdir(self.base), [])    # contents gone


class TestOldFiles(unittest.TestCase):
    def test_finds_only_files_past_threshold(self):
        base = tempfile.mkdtemp()
        fresh = os.path.join(base, "fresh.txt")
        old = os.path.join(base, "old.txt")
        with open(fresh, "wb") as fh:
            fh.write(b"a" * 10)
        with open(old, "wb") as fh:
            fh.write(b"b" * 2000)
        past = time.time() - 200 * 86400
        os.utime(old, (past, past))

        results = fsutils.find_old_files(base, days=90)
        paths = [p for _s, p, _m in results]
        self.assertIn(old, paths)
        self.assertNotIn(fresh, paths)
        # biggest-first ordering
        self.assertEqual(results[0][1], old)

    def test_cancel_raises(self):
        base = tempfile.mkdtemp()
        with open(os.path.join(base, "x.txt"), "wb") as fh:
            fh.write(b"x")
        with self.assertRaises(fsutils.Cancelled):
            fsutils.find_old_files(base, days=0, should_cancel=lambda: True)

    def test_excluded_subtree_is_skipped(self):
        base = tempfile.mkdtemp()
        skip = os.path.join(base, "skip")
        os.makedirs(skip)
        old = os.path.join(skip, "old.txt")
        with open(old, "wb") as fh:
            fh.write(b"b" * 2000)
        past = time.time() - 200 * 86400
        os.utime(old, (past, past))
        results = fsutils.find_old_files(base, days=90, excluded=[skip])
        self.assertEqual(results, [])


class TestMoveFiles(unittest.TestCase):
    def setUp(self):
        self.src = tempfile.mkdtemp()
        self.dest = tempfile.mkdtemp()

    def _make(self, rel, data=b"data"):
        path = os.path.join(self.src, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_moves_and_reports_bytes(self):
        a = self._make("a.bin", b"x" * 1000)
        moved, freed = fsutils.move_files([a], self.dest, base_dir=self.src)
        self.assertEqual((moved, freed), (1, 1000))
        self.assertFalse(os.path.exists(a))                      # source gone
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "a.bin")))

    def test_preserves_relative_structure(self):
        nested = self._make(os.path.join("sub", "deep", "f.txt"), b"hi")
        fsutils.move_files([nested], self.dest, base_dir=self.src)
        self.assertTrue(os.path.isfile(
            os.path.join(self.dest, "sub", "deep", "f.txt")))

    def test_collision_does_not_overwrite(self):
        # A file already at the destination with the same name must survive.
        existing = os.path.join(self.dest, "dup.txt")
        with open(existing, "wb") as fh:
            fh.write(b"ORIGINAL")
        src = self._make("dup.txt", b"NEW")
        fsutils.move_files([src], self.dest, base_dir=self.src)
        with open(existing, "rb") as fh:
            self.assertEqual(fh.read(), b"ORIGINAL")             # untouched
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "dup (1).txt")))

    def test_missing_source_is_skipped(self):
        moved, freed = fsutils.move_files(
            [os.path.join(self.src, "ghost.bin")], self.dest)
        self.assertEqual((moved, freed), (0, 0))


class TestIterFiles(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "a", "b"))
        for rel in ("top.txt", os.path.join("a", "m.txt"),
                    os.path.join("a", "b", "deep.txt")):
            with open(os.path.join(self.base, rel), "wb") as fh:
                fh.write(b"x" * 10)

    def test_yields_every_file_with_stat(self):
        files = dict(fsutils.iter_files(self.base))
        self.assertEqual(len(files), 3)
        for st in files.values():
            self.assertEqual(st.st_size, 10)

    def test_dir_size_and_count_match_manual_walk(self):
        self.assertEqual(fsutils.dir_size(self.base), 30)
        self.assertEqual(fsutils.dir_count(self.base), 3)

    def test_cancel_and_exclude(self):
        with self.assertRaises(fsutils.Cancelled):
            list(fsutils.iter_files(self.base, should_cancel=lambda: True))
        kept = dict(fsutils.iter_files(
            self.base, excluded=[os.path.join(self.base, "a")]))
        self.assertEqual(list(kept), [os.path.join(self.base, "top.txt")])

    def test_is_reparse_dir_false_for_plain_dir(self):
        with os.scandir(self.base) as it:
            for entry in it:
                if entry.is_dir():
                    self.assertFalse(fsutils.is_reparse_dir(entry))


class TestExcludeHelpers(unittest.TestCase):
    def test_is_excluded_matches_root_and_descendants(self):
        normed = fsutils.normalize_excludes([os.path.join("C:", "cache")])
        self.assertTrue(fsutils.is_excluded(os.path.join("C:", "cache"), normed))
        self.assertTrue(
            fsutils.is_excluded(os.path.join("C:", "cache", "deep", "f"), normed))
        self.assertFalse(fsutils.is_excluded(os.path.join("C:", "cacheother"), normed))
        self.assertFalse(fsutils.is_excluded(os.path.join("C:", "other"), normed))


if __name__ == "__main__":
    unittest.main()
