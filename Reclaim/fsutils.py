"""Pure filesystem helpers: sizing, formatting, and safe content deletion.

Everything here is deliberately platform-agnostic and dependency-free so it can
be unit-tested headlessly. Nothing in this module knows about tkinter or the
Windows shell — it only touches the standard `os`/`shutil` surface.
"""

import os
import shutil
import string
import time


class Cancelled(Exception):
    """Raised by a long scan/clean when the user asks to stop.

    A dedicated type lets the GUI tell "the user cancelled" apart from a genuine
    error, so a cancel reads as a clean abort rather than a crash in the log.
    """


def normalize_excludes(excluded):
    """Turn an exclusion list into absolute, case-folded roots for prefix tests.

    Windows paths are case-insensitive, so we compare with normcase; doing the
    normalisation once up front keeps the per-file check in a deep walk cheap.
    """
    out = []
    for p in (excluded or ()):
        try:
            out.append(os.path.normcase(os.path.abspath(p)))
        except (OSError, ValueError):
            pass
    return out


def is_excluded(path, normed_excludes):
    """True if `path` is at or under any normalised excluded root."""
    if not normed_excludes:
        return False
    cp = os.path.normcase(os.path.abspath(path))
    for root in normed_excludes:
        if cp == root or cp.startswith(root + os.sep):
            return True
    return False


def human(n):
    """Format a byte count as a short human string (e.g. 1536 -> '1.5 KB')."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def months_old(seconds):
    """Express an age purely in whole months — the 'old downloads' view thinks
    in months, so one unit reads uniformly (a 2-year file shows '24 months',
    not '2.0y'). Under a month → '<1 month'. Plain English on purpose: the age
    column isn't translated."""
    months = int(seconds / 86400 / 30)
    if months < 1:
        return "<1 month"
    return f"{months} month" + ("s" if months != 1 else "")


def list_drives():
    """Return the mounted drive roots to report usage for, in order.

    On Windows that's every ready volume A:..Z: (a letter is included only if
    shutil.disk_usage answers, so empty card readers / unmounted letters are
    skipped); elsewhere just '/'. Lets the header show one line per drive and
    grow automatically as drives are added.
    """
    if os.name != "nt":
        return ["/"]
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            shutil.disk_usage(root)
        except OSError:
            continue
        drives.append(root)
    return drives or ["C:\\"]


def disk_free(path):
    """Free bytes on the volume containing `path`, or 0 if it can't be read.

    Used to measure what a delegated OS command (DISM, powercfg) actually freed:
    those tools don't report bytes, so we diff free space before and after rather
    than trust an estimate. Returns 0 on error so a failed probe reads as "no
    change" instead of crashing the run.
    """
    try:
        return shutil.disk_usage(path).free
    except (OSError, ValueError):
        return 0


# Windows file attribute for any reparse point (junction, symlink, etc.).
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_dir(entry):
    """True if a scandir directory entry is a junction / symlink / reparse point.

    Why this matters: Windows junctions are NOT symlinks, so os.walk happily
    descends into them — which double-counts a target (e.g. the legacy
    `Documents and Settings` -> `Users` junction) or loops. Skipping reparse
    points makes every scan size correct and terminating. We test the reparse
    attribute where the platform exposes it and fall back to is_symlink()
    elsewhere (e.g. POSIX, where st_file_attributes doesn't exist).
    """
    try:
        if entry.is_symlink():
            return True
        attrs = getattr(entry.stat(follow_symlinks=False),
                        "st_file_attributes", 0)
        return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def iter_files(base, should_cancel=None, excluded=None):
    """Yield (path, stat_result) for every real file under `base`, fast.

    Built on os.scandir instead of os.walk + os.path.getsize: scandir carries the
    size/mtime from the directory enumeration, so on Windows there's no extra
    stat syscall per file — the single biggest speed win for whole-drive scans.
    Reparse-point directories and symlinked files are skipped (see is_reparse_dir)
    so a scan can't double-count or loop. `should_cancel()` is polled once per
    directory (raising Cancelled); `excluded` subtrees are pruned. Unreadable
    entries are skipped, never raised, so one locked folder can't abort the tally.
    """
    normed = normalize_excludes(excluded)
    stack = [os.path.abspath(base)]
    while stack:
        path = stack.pop()
        if should_cancel and should_cancel():
            raise Cancelled()
        if is_excluded(path, normed):
            continue
        try:
            scan = os.scandir(path)
        except OSError:
            continue
        with scan:
            for entry in scan:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not is_reparse_dir(entry):
                            stack.append(entry.path)
                    elif not entry.is_symlink():
                        yield entry.path, entry.stat(follow_symlinks=False)
                except OSError:
                    continue


def dir_size(path):
    """Total size of all files under `path`.

    Unreadable entries are skipped rather than raised: a cleanup tool must keep
    going past the odd permission-denied file instead of aborting the whole tally.
    """
    return sum(st.st_size for _p, st in iter_files(path))


def dir_count(path):
    """Number of files under `path` (directories not counted)."""
    count = 0
    for _ in iter_files(path):
        count += 1
    return count


def dir_size_and_count(path):
    """Total size and file count under `path` in a single walk.

    When a caller needs both (Analyze shows size *and* item count), folding them
    into one iter_files pass avoids scandir-walking a large cache twice.
    """
    size = count = 0
    for _p, st in iter_files(path):
        size += st.st_size
        count += 1
    return size, count


def clean_dir_contents(path, log):
    """Delete the *contents* of `path` while keeping `path` itself.

    Why keep the folder: apps expect their cache directory to exist and recreate
    files inside it; deleting the directory itself can break the app until restart.

    Returns bytes actually freed, measured as (size before - size after). We
    measure rather than assume, because in-use files are skipped (not forced),
    so the freed total must reflect what really went.
    """
    if not os.path.isdir(path):
        return 0
    before = dir_size(path)
    try:
        entries = list(os.scandir(path))
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                if is_reparse_dir(entry):
                    # A junction/symlink inside a cache dir points elsewhere on
                    # the volume; shutil.rmtree would follow it and delete the
                    # TARGET's contents — outside the allowlisted tree. Skip it,
                    # matching iter_files (which also skips reparse dirs), so the
                    # before/after size measurement stays consistent too.
                    log(f"    skipped (reparse point): {entry.name}")
                    continue
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                os.remove(entry.path)
        except OSError:
            log(f"    skipped (in use): {entry.name}")
    after = dir_size(path)
    return max(0, before - after)


def delete_files(paths, log):
    """Permanently delete a list of individual files. Returns bytes freed.

    Used only for regenerable caches (e.g. thumbnail DBs). User files take the
    undoable Recycle-Bin path in winapi.send_to_recycle_bin instead.
    """
    freed = 0
    for p in paths:
        try:
            sz = os.path.getsize(p)
            os.remove(p)
            freed += sz
        except OSError:
            log(f"    skipped (in use): {os.path.basename(p)}")
    return freed


def unique_path(path):
    """Return `path`, or the first ' (n)' variant that doesn't already exist.

    Prevents a move/copy from silently overwriting an unrelated file that happens
    to share the name at the destination — we keep both rather than clobber.
    """
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{root} ({i}){ext}"):
        i += 1
    return f"{root} ({i}){ext}"


def move_files(paths, dest_dir, base_dir=None, log=None):
    """Move files to `dest_dir` (e.g. another drive). Returns (moved, bytes_moved).

    Why this is the safe way to relocate user files: shutil.move copies then
    deletes the source, so a failure mid-way (locked file, target drive full)
    leaves the original untouched — we never lose data to a half-move. Each
    failure is logged and skipped so one bad file doesn't abort the batch.

    When `base_dir` is given and a file lives under it, its path *relative* to
    base_dir is recreated under dest_dir; that preserves folder structure and
    stops two files with the same name from colliding. Files outside base_dir
    (or on another drive from it) keep just their basename. Remaining name
    clashes are resolved with unique_path rather than overwriting.
    """
    moved = 0
    bytes_moved = 0
    for p in paths:
        if not os.path.isfile(p):
            continue
        rel = os.path.basename(p)
        if base_dir:
            try:
                candidate = os.path.relpath(p, base_dir)
                if not candidate.startswith(".."):  # i.e. genuinely under base_dir
                    rel = candidate
            except ValueError:
                pass  # different drive than base_dir -> fall back to basename
        target = unique_path(os.path.join(dest_dir, rel))
        try:
            sz = os.path.getsize(p)
            os.makedirs(os.path.dirname(target) or dest_dir, exist_ok=True)
            shutil.move(p, target)
            moved += 1
            bytes_moved += sz
        except OSError:
            if log:
                log(f"    skipped (in use or target full): {os.path.basename(p)}")
    return moved, bytes_moved


def find_old_files(folder, days, should_cancel=None, excluded=None):
    """Return [(size, path, mtime), ...] for files older than `days`, biggest first.

    Sorted big-first because the whole point is reclaiming space: the user wants
    the heavy, forgotten files at the top of the list, not alphabetical order.

    `should_cancel()` is polled once per directory so a user-requested stop is
    honoured promptly without the cost of checking on every file; it raises
    Cancelled. `excluded` roots are pruned from the walk so a protected folder is
    never even read.
    """
    cutoff = time.time() - days * 86400
    out = []
    for fp, st in iter_files(folder, should_cancel=should_cancel, excluded=excluded):
        if st.st_mtime < cutoff:
            out.append((st.st_size, fp, st.st_mtime))
    out.sort(reverse=True)
    return out
