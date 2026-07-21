"""Whole-drive size mapping for the Disk Analyzer.

Kept free of any GUI dependency so it can be tested directly and reused. The GUI
passes a progress callback; tests omit it. The heavy lifting is a single
bottom-up walk — see build_size_map for why that ordering matters.
"""

import hashlib
import heapq
import os
import time
from collections import namedtuple

from . import config, fsutils, mft, winapi

# What a scan produces. A small named record beats returning a 5-tuple that
# callers have to remember the order of.
ScanResult = namedtuple("ScanResult", "dir_sizes top_files top_types total scanned")

# One set of byte-identical files. `size` is the size of a single copy; the
# space wasted by the group is size * (len(paths) - 1), since one copy is the
# original you'd keep.
DuplicateGroup = namedtuple("DuplicateGroup", "size paths")


def _try_mft_size_map(base, on_progress, should_cancel):
    """Return a ScanResult from the NTFS MFT, or None to fall back to scandir.

    Only attempted for a whole volume root (e.g. "C:\\"); a subfolder doesn't map
    to the MFT cleanly. Opens the volume via winapi (admin/NTFS-gated), parses
    every record, and assembles the tree — all in mft.py. Cancellation propagates
    (the user meant to stop); any other failure returns None so the caller uses
    the reliable scandir path. The volume handle is always closed.
    """
    drive, tail = os.path.splitdrive(base)
    if not drive or tail.strip("\\/") != "":
        return None  # not a volume root
    volume = winapi.open_ntfs_volume(drive)
    if volume is None:
        return None
    try:
        records = mft.scan(
            volume["read"],
            volume["bytes_per_cluster"],
            volume["record_size"],
            volume["mft_start_lcn"],
            on_progress=on_progress,
            should_cancel=should_cancel,
            sector_size=volume["bytes_per_sector"],
        )
    except fsutils.Cancelled:
        raise
    except Exception:
        return None
    finally:
        try:
            volume["close"]()
        except Exception:
            pass
    if not records:
        return None
    dir_sizes, top_files, top_types, total, scanned = mft.assemble(
        records, drive + "\\"
    )
    if scanned == 0:
        return None
    return ScanResult(dir_sizes, top_files, top_types, total, scanned)


def build_size_map(base, on_progress=None, should_cancel=None, excluded=None):
    """Map every folder's total size under `base` in one pass.

    Uses an explicit os.scandir walk rather than os.walk + os.path.getsize: the
    DirEntry's stat is filled in from the directory enumeration, so on Windows
    each file's size costs no extra syscall — the dominant speed win on a full
    drive. Reparse-point directories (junctions/symlinks) are skipped via
    fsutils.is_reparse_dir, so a junction can't make the totals double-count.

    Sizes roll up bottom-up: we record each directory in discovery order, and
    because a child is only discovered after its parent, walking that list in
    reverse visits every child before its parent — so a parent's total is just
    (its own files + its children's already-summed totals), an O(n) sweep that
    makes drilling into a scanned tree feel instant.

    `on_progress(count)` is throttled to SCAN_STATUS_INTERVAL. `should_cancel()`
    is polled once per directory and raises Cancelled. `excluded` roots are
    recorded as size 0 and never scanned, rolling up as empty into their parent.
    """
    base = os.path.abspath(base)
    # Fast path: read the NTFS MFT directly when scanning a whole volume root.
    # It needs admin + NTFS and ignores exclusions, so it only applies when no
    # excludes are set; any failure returns None and we fall through to scandir.
    if not excluded:
        fast = _try_mft_size_map(base, on_progress, should_cancel)
        if fast is not None:
            return fast

    normed = fsutils.normalize_excludes(excluded)
    own_size = {}  # dir -> bytes of files directly inside it
    children = {}  # dir -> [child dir paths]
    order = []  # dirs in discovery order (every parent before its kids)
    heap = []  # bounded min-heap of the largest files: (size, path)
    ext_sizes = {}  # extension -> total bytes
    scanned = 0
    last = time.time()

    stack = [base]
    while stack:
        path = stack.pop()
        if should_cancel and should_cancel():
            raise fsutils.Cancelled()
        order.append(path)
        if fsutils.is_excluded(path, normed):
            own_size[path] = 0
            children[path] = []
            continue
        s = 0
        kids = []
        try:
            scan = os.scandir(path)
        except OSError:
            own_size[path] = 0
            children[path] = []
            continue
        with scan:
            for entry in scan:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not fsutils.is_reparse_dir(entry):
                            kids.append(entry.path)
                            stack.append(entry.path)
                        continue
                    if entry.is_symlink():
                        continue
                    sz = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                s += sz
                scanned += 1
                ext = os.path.splitext(entry.name)[1].lower() or "(no ext)"
                ext_sizes[ext] = ext_sizes.get(ext, 0) + sz
                # Keep only the FILE_HEAP_SIZE biggest files, so memory stays flat.
                if len(heap) < config.FILE_HEAP_SIZE:
                    heapq.heappush(heap, (sz, entry.path))
                elif sz > heap[0][0]:
                    heapq.heapreplace(heap, (sz, entry.path))
                if on_progress and time.time() - last > config.SCAN_STATUS_INTERVAL:
                    last = time.time()
                    on_progress(scanned)
        own_size[path] = s
        children[path] = kids

    dir_sizes = {}
    for path in reversed(order):
        total = own_size.get(path, 0)
        for child in children.get(path, ()):
            total += dir_sizes.get(child, 0)
        dir_sizes[path] = total

    top_files = sorted(heap, reverse=True)[: config.TOP_FILES_SHOWN]
    top_types = sorted(ext_sizes.items(), key=lambda kv: kv[1], reverse=True)[
        : config.TOP_TYPES_SHOWN
    ]
    return ScanResult(dir_sizes, top_files, top_types, dir_sizes.get(base, 0), scanned)


def _hash_file(path, limit=None):
    """SHA-256 of a file, or of its first `limit` bytes when `limit` is set.

    Returns None on any read error (locked/vanished file) so the caller can drop
    that file from consideration rather than abort the whole scan. Reads in
    bounded chunks so a huge file never has to fit in memory.
    """
    h = hashlib.sha256()
    remaining = limit
    try:
        with open(path, "rb") as fh:
            while True:
                want = config.DUP_HASH_CHUNK
                if remaining is not None:
                    if remaining <= 0:
                        break
                    want = min(want, remaining)
                chunk = fh.read(want)
                if not chunk:
                    break
                h.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
    except OSError:
        return None
    return h.digest()


def _collapse_hardlinks(paths):
    """Keep one path per distinct physical file within an identical-content group.

    Two paths that are hardlinks point at the *same* bytes on disk (same volume +
    file id), so they aren't wasteful copies and deleting one frees nothing — the
    data lives until the last link is gone. We must not present them as
    reclaimable duplicates. We keep the first path seen for each (st_dev, st_ino)
    and drop the rest. A file we can't stat, or whose inode is unavailable
    (st_ino == 0, some filesystems), is treated as distinct so we never collapse
    two genuinely-separate files by mistake.
    """
    seen = set()
    out = []
    for p in paths:
        try:
            st = os.stat(p)
            key = (st.st_dev, st.st_ino) if st.st_ino else None
        except OSError:
            key = None
        if key is None:
            out.append(p)
        elif key not in seen:
            seen.add(key)
            out.append(p)
    return out


def find_duplicates(
    base, min_size=None, on_progress=None, should_cancel=None, excluded=None
):
    """Find groups of byte-identical files at or above `min_size`, costliest first.

    A three-stage funnel keeps the work cheap: most files are unique, so we want
    to prove that as early as possible.
      1. Group by exact size — files of different size can't be identical, and
         this needs only the stat() we already do while walking.
      2. Within each same-size group, compare a partial hash of the head; this
         rejects look-alikes (e.g. installers padded to the same size) after one
         small read.
      3. Only the survivors of step 2 get a full-content hash to confirm.
    The expensive full read therefore happens for a tiny minority of files.
    Confirmed groups are then collapsed across hardlinks (see _collapse_hardlinks)
    so files that merely share storage aren't reported as reclaimable copies.

    Returns [DuplicateGroup, ...] sorted by wasted space (size * extra copies)
    descending, so the biggest reclaim is at the top. `on_progress(count)` is
    throttled like build_size_map; `should_cancel()` is polled during both the
    walk and the hashing pass (the slow part) and raises Cancelled; `excluded`
    roots are pruned from the walk. Pass None for all three in tests.
    """
    base = os.path.abspath(base)
    if min_size is None:
        min_size = config.DUP_MIN_SIZE

    by_size = {}
    scanned = 0
    last = time.time()
    # Shared fast walker: scandir-based, reparse-safe, cancel/exclude aware.
    for fp, st in fsutils.iter_files(
        base, should_cancel=should_cancel, excluded=excluded
    ):
        if st.st_size < min_size:
            continue
        by_size.setdefault(st.st_size, []).append(fp)
        scanned += 1
        if on_progress and time.time() - last > config.SCAN_STATUS_INTERVAL:
            last = time.time()
            on_progress(scanned)

    groups = []
    for sz, paths in by_size.items():
        if len(paths) < 2:
            continue  # unique size -> can't be a duplicate
        if should_cancel and should_cancel():
            raise fsutils.Cancelled()
        # Stage 2: bucket by a cheap head hash.
        by_partial = {}
        for p in paths:
            digest = _hash_file(p, limit=config.DUP_PARTIAL_READ)
            if digest is not None:
                by_partial.setdefault(digest, []).append(p)
        # Stage 3: confirm survivors with a full hash.
        for candidates in by_partial.values():
            if len(candidates) < 2:
                continue
            by_full = {}
            for p in candidates:
                digest = _hash_file(p)
                if digest is not None:
                    by_full.setdefault(digest, []).append(p)
            for matched in by_full.values():
                # Drop hardlink siblings: identical content but the same physical
                # file, so they're not reclaimable copies.
                distinct = _collapse_hardlinks(matched)
                if len(distinct) >= 2:
                    groups.append(DuplicateGroup(sz, sorted(distinct)))

    groups.sort(key=lambda g: g.size * (len(g.paths) - 1), reverse=True)
    return groups
