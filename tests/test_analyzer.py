"""Tests for the drive-mapping analyzer. No network, no secrets, no tkinter."""

import os
import tempfile
import unittest

from Reclaim import analyzer, fsutils


class TestBuildSizeMap(unittest.TestCase):
    def setUp(self):
        # base/{ photos/(3 x 1MB jpg), videos/big.bin (5MB), notes.txt (2B) }
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "photos"))
        os.makedirs(os.path.join(self.base, "videos"))
        for i in range(3):
            with open(os.path.join(self.base, "photos", f"p{i}.jpg"), "wb") as fh:
                fh.write(b"a" * 1024 * 1024)
        with open(os.path.join(self.base, "videos", "big.bin"), "wb") as fh:
            fh.write(b"b" * 1024 * 1024 * 5)
        with open(os.path.join(self.base, "notes.txt"), "wb") as fh:
            fh.write(b"hi")

    def test_totals_roll_up(self):
        r = analyzer.build_size_map(self.base)
        self.assertEqual(r.total, 3 * 1024 * 1024 + 5 * 1024 * 1024 + 2)
        self.assertEqual(
            r.dir_sizes[os.path.join(self.base, "photos")], 3 * 1024 * 1024
        )
        self.assertEqual(
            r.dir_sizes[os.path.join(self.base, "videos")], 5 * 1024 * 1024
        )
        self.assertEqual(r.scanned, 5)

    def test_largest_file_and_type_ranking(self):
        r = analyzer.build_size_map(self.base)
        biggest_size, biggest_path = r.top_files[0]
        self.assertEqual(os.path.basename(biggest_path), "big.bin")
        self.assertEqual(biggest_size, 5 * 1024 * 1024)
        # .bin should outrank .jpg by total size
        top_ext = r.top_types[0][0]
        self.assertEqual(top_ext, ".bin")

    def test_progress_callback_is_optional(self):
        # Must work with no callback (the test path) ...
        analyzer.build_size_map(self.base)
        # ... and call back when supplied.
        seen = []
        analyzer.build_size_map(self.base, on_progress=seen.append)
        # callback is throttled, so it may or may not fire on a tiny tree;
        # the contract is only that supplying it never errors.


class TestFindDuplicates(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()

    def _write(self, name, data):
        path = os.path.normpath(os.path.join(self.base, name))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_groups_identical_files_only(self):
        # Two identical 2 MB files, plus one same-size file with different bytes.
        content = b"A" * (2 * 1024 * 1024)
        a = self._write("a.bin", content)
        b = self._write("nested/b.bin", content)
        self._write("c.bin", b"B" * (2 * 1024 * 1024))  # same size, not identical

        groups = analyzer.find_duplicates(self.base)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0].paths), {a, b})
        self.assertEqual(groups[0].size, 2 * 1024 * 1024)

    def test_min_size_excludes_small_files(self):
        # Identical but tiny: excluded at the default floor, included when lowered.
        self._write("s1.txt", b"hello world")
        self._write("s2.txt", b"hello world")
        self.assertEqual(analyzer.find_duplicates(self.base), [])
        groups = analyzer.find_duplicates(self.base, min_size=1)
        self.assertEqual(len(groups), 1)

    def test_partial_match_is_not_enough(self):
        # Same size and same first 64 KB, but different tails -> NOT duplicates.
        head = b"H" * (64 * 1024)
        self._write("x.bin", head + b"1" * (64 * 1024))
        self._write("y.bin", head + b"2" * (64 * 1024))
        groups = analyzer.find_duplicates(self.base, min_size=1024)
        self.assertEqual(groups, [])

    def test_sorted_by_wasted_space(self):
        # A group of 3 medium copies wastes more than a pair of slightly bigger ones.
        med = b"M" * (1 * 1024 * 1024)
        for n in ("m1.bin", "m2.bin", "m3.bin"):
            self._write(n, med)
        big = b"G" * (1024 * 1024 + 500)
        self._write("g1.bin", big)
        self._write("g2.bin", big)
        groups = analyzer.find_duplicates(self.base, min_size=1024)
        wasted = [g.size * (len(g.paths) - 1) for g in groups]
        self.assertEqual(wasted, sorted(wasted, reverse=True))

    def test_hardlinks_are_not_counted_as_duplicates(self):
        # A real copy plus a hardlink to it: only the copy + one representative of
        # the hardlinked data should be reported (deleting a hardlink frees nothing).
        content = b"H" * (2 * 1024 * 1024)
        original = self._write("orig.bin", content)
        link = os.path.join(self.base, "hardlink.bin")
        try:
            os.link(original, link)
        except (OSError, AttributeError, NotImplementedError):
            self.skipTest("hardlinks unsupported on this filesystem")
        a_copy = self._write("real_copy.bin", content)  # genuine separate copy

        groups = analyzer.find_duplicates(self.base)
        self.assertEqual(len(groups), 1)
        paths = set(groups[0].paths)
        # Exactly one of {original, link} survives, plus the genuine copy -> 2.
        self.assertEqual(len(paths), 2)
        self.assertIn(a_copy, paths)
        self.assertEqual(len(paths & {original, link}), 1)


class TestCancelAndExclude(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "keep"))
        os.makedirs(os.path.join(self.base, "skip"))
        big = b"Z" * (2 * 1024 * 1024)
        with open(os.path.join(self.base, "keep", "a.bin"), "wb") as fh:
            fh.write(big)
        with open(os.path.join(self.base, "skip", "b.bin"), "wb") as fh:
            fh.write(big)  # identical to a.bin, but in the excluded subtree

    def test_build_size_map_cancels(self):
        with self.assertRaises(fsutils.Cancelled):
            analyzer.build_size_map(self.base, should_cancel=lambda: True)

    def test_find_duplicates_cancels(self):
        with self.assertRaises(fsutils.Cancelled):
            analyzer.find_duplicates(self.base, should_cancel=lambda: True)

    def test_excluded_subtree_is_ignored_by_size_map(self):
        excl = [os.path.join(self.base, "skip")]
        r = analyzer.build_size_map(self.base, excluded=excl)
        self.assertEqual(r.dir_sizes[os.path.join(self.base, "skip")], 0)
        self.assertEqual(r.total, 2 * 1024 * 1024)  # only keep/a.bin counts

    def test_excluded_subtree_breaks_duplicate_pairing(self):
        # With "skip" excluded, a.bin has no partner -> no duplicate group.
        excl = [os.path.join(self.base, "skip")]
        self.assertEqual(analyzer.find_duplicates(self.base, excluded=excl), [])
        # Without the exclusion, the pair is found.
        self.assertEqual(len(analyzer.find_duplicates(self.base)), 1)


if __name__ == "__main__":
    unittest.main()
