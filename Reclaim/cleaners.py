"""Cleanup categories and the analyze/clean orchestration over them.

This ties the three lower layers together: locations.py says *where*, fsutils.py
and winapi.py say *how to measure and delete*. Each category declares a `kind`
that selects the right measure/delete pair, so adding a new category is just one
dict entry plus a resolver in locations.py — no branching scattered elsewhere.
"""

import os

from . import config, fsutils, locations, winapi


def _hiberfil_estimate():
    """(size, count) of the hibernation file, for previewing the hibernation toggle."""
    p = os.path.join(config.SYSTEM_DRIVE, "hiberfil.sys")
    try:
        return os.path.getsize(p), 1
    except OSError:
        return 0, 0


def _windows_old_estimate():
    """(size, count) of C:\\Windows.old, or (0, 0) when there's no previous install."""
    d = locations.windows_old_dir()
    if not d:
        return 0, 0
    return fsutils.dir_size(d), fsutils.dir_count(d)


# Each cleaner is a small declarative record. `kind` decides how it's measured
# and cleaned:
#   "dirs"    -> get() returns directories whose *contents* are cleared
#   "files"   -> get() returns individual files to delete
#   "recycle" -> handled by the Recycle Bin shell API
#   "command" -> run(log) delegates to an OS tool; freed bytes are measured as
#                the change in free disk space, and an optional estimate()
#                previews the size since the tool reports none.
CLEANERS = [
    {"key": "temp", "label": "Temporary files",
     "desc": "User + Windows temp folders. Always safe to clear.",
     "kind": "dirs", "get": locations.temp_dirs, "needs_admin": False},
    {"key": "recycle", "label": "Recycle Bin",
     "desc": "Permanently empties the Recycle Bin.",
     "kind": "recycle", "get": lambda: [], "needs_admin": False},
    {"key": "browsers", "label": "Browser caches",
     "desc": "Chrome, Edge, Brave, Vivaldi, Opera & Firefox caches (all profiles). Logins kept.",
     "kind": "dirs", "get": locations.browser_cache_dirs, "needs_admin": False},
    {"key": "apps", "label": "App caches",
     "desc": "Discord, Spotify, Teams, Slack, Zoom & WhatsApp caches.",
     "kind": "dirs", "get": locations.app_cache_dirs, "needs_admin": False},
    {"key": "devcaches", "label": "Developer caches",
     "desc": "npm, yarn, pnpm, pip, Gradle, Maven, NuGet, Cargo, Go & editor caches. Rebuilt on next build.",
     "kind": "dirs", "get": locations.dev_cache_dirs, "needs_admin": False},
    {"key": "winupdate", "label": "Windows Update cache",
     "desc": "Old downloaded update files. Needs admin to clear fully.",
     "kind": "dirs", "get": locations.windows_update_dirs, "needs_admin": True},
    {"key": "delivopt", "label": "Delivery Optimization files",
     "desc": "Cached update-sharing data. Rebuilds automatically. Needs admin.",
     "kind": "dirs", "get": locations.delivery_optimization_dirs, "needs_admin": True},
    {"key": "wer", "label": "Error reporting dumps",
     "desc": "Windows Error Reporting archives & crash dumps.",
     "kind": "dirs", "get": locations.wer_dirs, "needs_admin": True},
    {"key": "sysdumps", "label": "System crash dumps",
     "desc": "Kernel memory dumps & minidumps from past crashes. Needs admin.",
     "kind": "files", "get": locations.system_dump_files, "needs_admin": True},
    {"key": "winlogs", "label": "Windows servicing logs",
     "desc": "CBS / DISM / setup logs. Regenerated as needed. Needs admin.",
     "kind": "dirs", "get": locations.windows_log_dirs, "needs_admin": True},
    {"key": "thumbs", "label": "Thumbnail cache",
     "desc": "Explorer thumbnail/icon cache. Rebuilds automatically.",
     "kind": "files", "get": locations.thumbnail_cache_files, "needs_admin": False},
    {"key": "custom", "label": "Custom folders",
     "desc": "Folders you've added under Settings. Their contents are cleared.",
     "kind": "dirs", "get": locations.custom_clean_dirs, "needs_admin": False},
    {"key": "winsxs", "label": "Windows component store cleanup",
     "desc": "Removes superseded update components via DISM. Needs admin; can take a while.",
     "kind": "command", "needs_admin": True,
     "run": lambda log: winapi.run_maintenance_command(config.DISM_COMPONENT_CLEANUP)},
    {"key": "hiberfil", "label": "Hibernation file",
     "desc": "Deletes hiberfil.sys by turning hibernation off (also disables Fast Startup). Needs admin.",
     "kind": "command", "needs_admin": True, "estimate": _hiberfil_estimate,
     "run": lambda log: winapi.run_maintenance_command(config.HIBERNATE_OFF)},
    {"key": "windows_old", "label": "Previous Windows installation",
     "desc": "Removes C:\\Windows.old left by a feature update. Needs admin; cannot be undone.",
     "kind": "command", "needs_admin": True, "estimate": _windows_old_estimate,
     "run": lambda log: winapi.remove_windows_old()},
]


def analyze_cleaner(cleaner):
    """Return (size_bytes, item_count) for one category WITHOUT deleting anything.

    Read-only by design: 'Analyze' must be safe to run at any time, so it shares
    no code path with the deletion functions. Command cleaners can't be measured
    by walking files, so they report their optional estimate() (or nothing).
    """
    if cleaner["kind"] == "recycle":
        return winapi.recycle_bin_info()
    if cleaner["kind"] == "command":
        estimate = cleaner.get("estimate")
        return estimate() if estimate else (0, 0)
    if cleaner["kind"] == "files":
        files = cleaner["get"]()
        size = 0
        for f in files:
            try:
                size += os.path.getsize(f)
            except OSError:
                pass
        return size, len(files)
    total_size = total_count = 0
    for d in cleaner["get"]():
        size, count = fsutils.dir_size_and_count(d)   # one walk, not two
        total_size += size
        total_count += count
    return total_size, total_count


def preview_cleaner(cleaner):
    """Return [(label, size_bytes), ...] of what a category would act on, WITHOUT
    deleting anything — the data behind the "Preview" dialog.

    This is the trust bridge between Analyze (a single total) and Clean (the
    irreversible step): it names the exact folders/files that would be touched.
    Rows are biggest-first; recycle/command categories show a one-line summary
    since there's no per-file list to enumerate.
    """
    kind = cleaner["kind"]
    if kind == "recycle":
        size, count = winapi.recycle_bin_info()
        return [(f"Recycle Bin contents ({count} items)", size)]
    if kind == "command":
        estimate = cleaner.get("estimate")
        size = estimate()[0] if estimate else 0
        return [(cleaner["desc"], size)]
    if kind == "files":
        rows = []
        for f in cleaner["get"]():
            try:
                rows.append((f, os.path.getsize(f)))
            except OSError:
                rows.append((f, 0))
        rows.sort(key=lambda r: r[1], reverse=True)
        return rows
    rows = [(d, fsutils.dir_size(d)) for d in cleaner["get"]()]
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def clean_cleaner(cleaner, log):
    """Run one category and return bytes freed. `log` is a callback for progress."""
    if cleaner["kind"] == "recycle":
        return winapi.empty_recycle_bin()
    if cleaner["kind"] == "command":
        # The OS tools don't report bytes, so we diff free space across the run.
        # It's the honest measure even if a touch noisy from other processes.
        before = fsutils.disk_free(config.SYSTEM_DRIVE)
        if not cleaner["run"](log):
            log("    skipped (needs admin, or not supported on this system)")
        after = fsutils.disk_free(config.SYSTEM_DRIVE)
        return max(0, after - before)
    if cleaner["kind"] == "files":
        return fsutils.delete_files(cleaner["get"](), log)
    freed = 0
    for d in cleaner["get"]():
        log(f"    cleaning {d}")
        freed += fsutils.clean_dir_contents(d, log)
    return freed
