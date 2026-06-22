"""The one place that talks to the Windows shell (ctypes / shell32).

This is the project's *guarded boundary*. Every irreversible or
platform-specific operation lives here, behind functions that fall back
gracefully when not on Windows, so the rest of the code can stay pure and
testable. Nothing here knows about the GUI; the GUI calls down into this.

Design choice: USER files are removed via send_to_recycle_bin (undoable),
never via a hard delete. Only regenerable caches are ever permanently removed
(and that lives in fsutils, not here).
"""

import os
import sys

from . import config

# subprocess creation flag: run a child without flashing a console window. Used
# for the maintenance commands and the Windows.old removal so a GUI launch stays
# clean. (Named here because the bare hex is meaningless at the call site.)
_CREATE_NO_WINDOW = 0x08000000

# Windows file attribute set on any reparse point (junction, symlink, mount).
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_reparse_point(path):
    """True if `path` is a junction/symlink/reparse point, tested by path.

    os.path.islink misses Windows *junctions* (they aren't symlinks), so before
    running an irreversible elevated delete on a fixed system path we also check
    the reparse attribute directly — a junction there would otherwise let the
    delete follow it out to an unrelated target.
    """
    try:
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def is_admin():
    """True if the process is elevated. Used to warn before admin-only cleans."""
    if not config.IS_WINDOWS:
        return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin():
    """Re-launch this script with an elevation prompt (UAC).

    Needed for Windows Update / Delivery Optimization / WER folders, which the
    OS protects. We relaunch the exact same argv so the user lands back where
    they were, just elevated.
    """
    if not config.IS_WINDOWS:
        return
    try:
        import ctypes
        import subprocess
        # Quote argv per the Windows C-runtime rules rather than naively wrapping
        # each token in quotes: a value containing a literal " would otherwise
        # break out and inject extra arguments into the elevated relaunch.
        params = subprocess.list2cmdline(sys.argv)
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        sys.exit(0)
    except Exception:
        pass


def recycle_bin_info():
    """Return (size_bytes, item_count) for the Recycle Bin, or (0, 0).

    Queried via SHQueryRecycleBin so 'Analyze' can preview the bin's size and
    'Clean' can report how much emptying it actually freed.
    """
    if not config.IS_WINDOWS:
        return 0, 0
    try:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_int64),
                ("i64NumItems", ctypes.c_int64),
            ]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        res = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if res == 0:
            return int(info.i64Size), int(info.i64NumItems)
    except Exception:
        pass
    return 0, 0


def empty_recycle_bin():
    """Empty the Recycle Bin silently. Returns bytes freed (before - after)."""
    if not config.IS_WINDOWS:
        return 0
    before, _ = recycle_bin_info()
    try:
        import ctypes
        flags = 0x01 | 0x02 | 0x04  # NOCONFIRMATION | NOPROGRESSUI | NOSOUND
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    except Exception:
        return 0
    after, _ = recycle_bin_info()
    return max(0, before - after)


def send_to_recycle_bin(paths):
    """Move USER files to the Recycle Bin (undoable). Returns bytes freed.

    We use SHFileOperation with FOF_ALLOWUNDO rather than os.remove so the user
    can always restore a file they didn't mean to clear. On non-Windows (i.e.
    during tests) we fall back to a plain remove so the logic is still exercisable.
    """
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        return 0
    freed = 0
    for p in paths:
        try:
            freed += os.path.getsize(p)
        except OSError:
            pass

    if not config.IS_WINDOWS:
        for p in paths:  # graceful fallback for headless tests
            try:
                os.remove(p)
            except OSError:
                pass
        return freed

    try:
        import ctypes
        from ctypes import wintypes

        FO_DELETE = 0x0003
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004
        FOF_NOERRORUI = 0x0400

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_uint16),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        # pFrom is a double-null-terminated, null-separated list. We build it in
        # a unicode buffer because a plain Python str would truncate at the first
        # embedded null.
        buf = ctypes.create_unicode_buffer("\0".join(paths) + "\0")
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return freed if res == 0 else 0
    except Exception:
        return 0


def run_maintenance_command(argv):
    """Run one of the OS's own cleanup tools (DISM, powercfg) and report success.

    This is the *delegated* arm of the guarded layer: for the component store and
    the hibernation file we never delete anything ourselves — those trees are the
    OS's to manage — we invoke Microsoft's supported tool and let it do the work.
    On non-Windows (tests/headless) it's a no-op returning False, so nothing
    system-level can run off-platform.

    Returns True on a clean (exit 0) run, False otherwise. We hide the console
    window so a GUI launch doesn't flash a black box.
    """
    if not config.IS_WINDOWS:
        return False
    import subprocess

    try:
        completed = subprocess.run(
            argv, creationflags=_CREATE_NO_WINDOW, capture_output=True
        )
        return completed.returncode == 0
    except Exception:
        return False


def remove_windows_old():
    """Best-effort removal of C:\\Windows.old (admin). Returns True if it's gone.

    The folder is owned by TrustedInstaller, so a plain delete fails: we first
    take ownership and grant rights, then remove it — the same sequence Disk
    Cleanup performs internally. We shell out via cmd so the take-own / grant /
    remove chain runs as one elevated step. No-op off Windows.
    """
    if not config.IS_WINDOWS:
        return False
    target = os.path.join(config.SYSTEM_DRIVE, "Windows.old")
    if not os.path.isdir(target):
        return True  # already absent — treat as success
    if os.path.islink(target) or _is_reparse_point(target):
        # Windows.old is created by Setup as a real directory. If this path is a
        # junction/symlink instead, it was planted: the take-ownership + rd /s /q
        # chain below would follow it and recursively delete the link's TARGET.
        # Refuse rather than run an irreversible elevated delete through a reparse
        # point.
        return False
    import subprocess

    # Invoke takeown/icacls/cmd by ABSOLUTE path (see config.SYSTEM32) so a
    # planted binary in the working directory can't hijack this elevated step.
    # `rd` is an internal cmd builtin, so it's safe once cmd.exe itself is pinned.
    cmd = os.path.join(config.SYSTEM32, "cmd.exe")
    takeown = os.path.join(config.SYSTEM32, "takeown.exe")
    icacls = os.path.join(config.SYSTEM32, "icacls.exe")
    script = (
        f'"{takeown}" /f "{target}" /r /d y >nul 2>&1 & '
        f'"{icacls}" "{target}" /grant *S-1-5-32-544:F /t /c >nul 2>&1 & '
        f'rd /s /q "{target}"'
    )
    try:
        subprocess.run([cmd, "/c", script], creationflags=_CREATE_NO_WINDOW,
                       capture_output=True)
    except Exception:
        pass
    return not os.path.isdir(target)


def open_ntfs_volume(drive):
    """Open a volume for raw MFT reading, or return None to signal "use fallback".

    This is the I/O seam for the MFT fast path (mft.py): it opens \\\\.\\<drive>
    — which requires administrator rights — and queries the NTFS geometry. It
    returns None (never raises) whenever the fast path can't apply: off Windows,
    without admin, on a non-NTFS volume, or on any API error. The caller then
    quietly uses the scandir scan instead.

    On success returns a dict with the geometry plus `read(offset, length)` and
    `close()` callables. The handle stays open until `close()` is called, so the
    caller must close it (build_size_map does, in a finally).
    """
    if not config.IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        GENERIC_READ = 0x80000000
        FILE_SHARE_RW = 0x01 | 0x02
        OPEN_EXISTING = 3
        FSCTL_GET_NTFS_VOLUME_DATA = 0x00090064
        INVALID = ctypes.c_void_p(-1).value

        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        letter = drive.rstrip("\\/").rstrip(":")
        handle = k32.CreateFileW(
            f"\\\\.\\{letter}:", GENERIC_READ, FILE_SHARE_RW, None,
            OPEN_EXISTING, 0, None)
        if not handle or handle == INVALID:
            return None

        buf = ctypes.create_string_buffer(128)
        returned = wintypes.DWORD(0)
        ok = k32.DeviceIoControl(
            handle, FSCTL_GET_NTFS_VOLUME_DATA, None, 0, buf, 128,
            ctypes.byref(returned), None)
        if not ok:
            k32.CloseHandle(handle)        # not NTFS, or query failed
            return None

        raw = buf.raw
        # NTFS_VOLUME_DATA_BUFFER field offsets (documented layout).
        bytes_per_sector = int.from_bytes(raw[40:44], "little")
        bytes_per_cluster = int.from_bytes(raw[44:48], "little")
        record_size = int.from_bytes(raw[48:52], "little")
        mft_start_lcn = int.from_bytes(raw[64:72], "little")
        if bytes_per_cluster == 0 or record_size == 0:
            k32.CloseHandle(handle)
            return None
        if bytes_per_sector == 0:
            bytes_per_sector = 512        # legacy default if the volume omits it

        k32.SetFilePointerEx.argtypes = [
            wintypes.HANDLE, ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]

        def read(offset, length):
            """Read `length` bytes at byte `offset` (caller keeps both
            sector-aligned, as MFT/cluster reads always are)."""
            pos = ctypes.c_longlong(0)
            if not k32.SetFilePointerEx(handle, ctypes.c_longlong(offset),
                                        ctypes.byref(pos), 0):  # FILE_BEGIN
                return b""
            out = ctypes.create_string_buffer(length)
            nread = wintypes.DWORD(0)
            if not k32.ReadFile(handle, out, length, ctypes.byref(nread), None):
                return b""
            return out.raw[:nread.value]

        return {
            "bytes_per_sector": bytes_per_sector,
            "bytes_per_cluster": bytes_per_cluster,
            "record_size": record_size,
            "mft_start_lcn": mft_start_lcn,
            "read": read,
            "close": lambda: k32.CloseHandle(handle),
        }
    except Exception:
        return None
