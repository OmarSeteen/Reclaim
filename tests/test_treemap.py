"""Tests for the pure squarified-treemap layout. No GUI, no I/O."""

import unittest

from Reclaim import treemap


class TestSquarify(unittest.TestCase):
    def test_empty_and_degenerate(self):
        self.assertEqual(treemap.squarify([], 0, 0, 100, 100), [])
        self.assertEqual(treemap.squarify([(1, "a")], 0, 0, 0, 100), [])
        # Non-positive weights are dropped.
        self.assertEqual(treemap.squarify([(0, "a"), (-5, "b")], 0, 0, 100, 100), [])

    def test_covers_area_proportionally(self):
        items = [(40, "a"), (30, "b"), (20, "c"), (10, "d")]
        rects = treemap.squarify(items, 0, 0, 200, 100)
        self.assertEqual(len(rects), 4)
        total_area = sum(rw * rh for _p, _x, _y, rw, rh in rects)
        self.assertAlmostEqual(total_area, 200 * 100, places=3)  # fills the rect
        # Each tile's area is proportional to its weight.
        by = {p: rw * rh for p, _x, _y, rw, rh in rects}
        self.assertAlmostEqual(by["a"] / by["d"], 4.0, places=3)
        self.assertAlmostEqual(by["b"] / by["c"], 1.5, places=3)

    def test_all_rects_within_bounds(self):
        items = [(i + 1, str(i)) for i in range(25)]
        rects = treemap.squarify(items, 10, 20, 300, 150)
        for _p, rx, ry, rw, rh in rects:
            self.assertGreaterEqual(rx, 10 - 1e-6)
            self.assertGreaterEqual(ry, 20 - 1e-6)
            self.assertLessEqual(rx + rw, 10 + 300 + 1e-6)
            self.assertLessEqual(ry + rh, 20 + 150 + 1e-6)

    def test_single_item_fills_everything(self):
        rects = treemap.squarify([(5, "only")], 0, 0, 80, 60)
        self.assertEqual(len(rects), 1)
        p, x, y, w, h = rects[0]
        self.assertEqual((p, x, y, w, h), ("only", 0, 0, 80, 60))

    def test_aspect_ratios_are_reasonable(self):
        # Squarified layout should avoid extreme slivers for balanced inputs.
        items = [(10, i) for i in range(10)]
        rects = treemap.squarify(items, 0, 0, 100, 100)
        for _p, _x, _y, rw, rh in rects:
            ratio = max(rw / rh, rh / rw)
            self.assertLess(ratio, 6.0)


if __name__ == "__main__":
    unittest.main()
