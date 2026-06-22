"""Squarified-treemap layout. Pure geometry, no GUI — so it can be unit-tested.

Given a list of weighted items and a rectangle, it returns sub-rectangles whose
*areas* are proportional to the weights and whose *aspect ratios* are kept as
close to square as possible (the "squarified" algorithm of Bruls, Huizing &
van Wijk). The GUI then just paints the rectangles it gets back; none of the
tiling maths lives in the widget layer.
"""


def _worst_ratio(areas, side):
    """Worst aspect ratio when `areas` are laid as one row along a strip of the
    given `side` length. Lower is squarer; we grow a row until this gets worse.

    The row's thickness is fixed at sum(areas)/side, so each tile's extent along
    the strip is area/thickness and its aspect ratio is the longer/shorter of
    those two. We return the worst (largest) ratio in the row.
    """
    total = sum(areas)
    if total <= 0 or side <= 0:
        return float("inf")
    thickness = total / side
    worst = 1.0
    for a in areas:
        length = a / thickness
        if length <= 0:
            return float("inf")
        worst = max(worst, thickness / length, length / thickness)
    return worst


def squarify(items, x, y, w, h):
    """Tile rect (x, y, w, h) for `items`, a list of (weight, payload).

    Returns [(payload, rx, ry, rw, rh), ...] covering the rectangle, areas
    proportional to weight, biggest-first. Non-positive weights are dropped; an
    empty list or a zero-area rectangle yields []. Iterative (no recursion) so a
    node with hundreds of children can't blow the stack.
    """
    cells = [(float(wt), p) for wt, p in items if wt > 0]
    if not cells or w <= 0 or h <= 0:
        return []
    total = sum(wt for wt, _ in cells)
    scale = (w * h) / total          # weight -> area in pixels^2
    cells = [(wt * scale, p) for wt, p in cells]
    cells.sort(key=lambda c: c[0], reverse=True)

    out = []
    cx, cy, cw, ch = x, y, w, h
    i, n = 0, len(cells)
    while i < n:
        side = min(cw, ch)
        # Grow a row greedily while it keeps the worst aspect ratio improving.
        row = [cells[i]]
        j = i + 1
        while j < n:
            with_next = [c[0] for c in row] + [cells[j][0]]
            if _worst_ratio(with_next, side) > _worst_ratio([c[0] for c in row], side):
                break
            row.append(cells[j])
            j += 1
        row_area = sum(c[0] for c in row)
        if cw <= ch:
            # Lay the row across the width; it occupies a band of this height.
            band = row_area / cw if cw else 0
            rx = cx
            for area, payload in row:
                rw = area / band if band else 0
                out.append((payload, rx, cy, rw, band))
                rx += rw
            cy += band
            ch -= band
        else:
            # Lay the row down the height; it occupies a column of this width.
            band = row_area / ch if ch else 0
            ry = cy
            for area, payload in row:
                rh = area / band if band else 0
                out.append((payload, cx, ry, band, rh))
                ry += rh
            cx += band
            cw -= band
        i = j
    return out
