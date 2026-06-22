"""All tunable constants and environment-derived base paths in one place.

Rule of this module: values only, no logic. If you need to change a colour, a
folder location, or a safety cap, you change it here once instead of hunting
through ten files. Every non-obvious value carries a comment saying *why* it is
what it is, so a future reader doesn't have to guess.
"""

import os
import sys

# --- Platform -------------------------------------------------------------- #
# Resolved once at import. The Windows shell APIs (winapi.py) and the cleanup
# locations (locations.py) both branch on this, so it must be a single source.
IS_WINDOWS = sys.platform.startswith("win")

# Environment-derived base directories. These are effectively constants for the
# life of the process; resolving them here keeps locations.py free of os.environ
# lookups and makes the "where do things live" question answerable in one spot.
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
APPDATA = os.environ.get("APPDATA", "")
PROGRAMDATA = os.environ.get("ProgramData", r"C:\ProgramData")
USERPROFILE = os.environ.get("USERPROFILE", os.path.expanduser("~"))
WINDIR = os.environ.get("SystemRoot", r"C:\Windows")
SYSTEM_DRIVE = os.environ.get("SystemDrive", "C:") + os.sep
# Absolute path to the system tools directory. Elevated helper commands (DISM,
# powercfg, takeown, icacls, cmd) are invoked by FULL path from here, never by
# bare name: a bare name is resolved via the current working directory first, so
# a malicious "Dism.exe"/"cmd.exe" planted next to a launched .exe would run with
# the elevation the user just granted. Pinning System32 closes that hijack.
SYSTEM32 = os.path.join(WINDIR, "System32")

# --- Window / app metadata ------------------------------------------------- #
APP_NAME = "Reclaim"
# UI language used until the user picks one (stored in settings thereafter).
DEFAULT_LANGUAGE = "en"
# Donation link opened by the sidebar "Buy me a coffee" button. Kept here (not
# inline in the UI) so the address lives in one auditable place like every other
# path/constant.
KOFI_URL = "https://ko-fi.com/omarseteen"

# --- Persisted state ------------------------------------------------------- #
# Where settings and the cleanup history live. We keep them under LOCALAPPDATA
# (per-user, never roamed) so a portable .exe doesn't scatter files next to
# itself; fall back to the home dir if LOCALAPPDATA is somehow unset.
APP_DATA_DIR = os.path.join(LOCALAPPDATA or USERPROFILE, "Reclaim")
SETTINGS_FILE = os.path.join(APP_DATA_DIR, "settings.json")
HISTORY_FILE = os.path.join(APP_DATA_DIR, "history.log")
# How many history lines to show in the viewer.
HISTORY_VIEW_LINES = 200
# Hard cap on lines kept in the history file, so an append-only log can't grow
# without bound over the life of the machine. Old runs past this are dropped;
# the recent ones are what anyone actually looks at.
HISTORY_MAX_LINES = 1000

# The "Recommended clean" preset: only the fully-safe, no-admin categories whose
# contents always regenerate. Deliberately excludes anything admin-gated or
# irreversible (Windows.old, component store) so one click can never surprise.
RECOMMENDED_KEYS = ["temp", "recycle", "browsers", "apps", "devcaches", "thumbs"]

# --- Safety / performance caps --------------------------------------------- #
# Track only the N largest files during a scan. A bounded heap keeps memory flat
# even on a drive with millions of files (we never hold them all at once).
FILE_HEAP_SIZE = 300
# How many of those largest files to actually display.
TOP_FILES_SHOWN = 60
# How many file-type rows (by extension) to display.
TOP_TYPES_SHOWN = 30
# Max children rendered per folder node in the drill-down tree. A folder with
# 100k entries would freeze the UI if we inserted them all; the user only ever
# cares about the biggest few, so we cap and sort by size.
TREE_CHILD_CAP = 500
# Minimum seconds between progress-status updates, so a fast scan doesn't flood
# the UI thread with redraw requests.
SCAN_STATUS_INTERVAL = 0.4
# Default age threshold for the "old files" finder. 90 days is long enough that
# anything still relevant has almost certainly been touched since. The UI lets
# the user pick the threshold in whole months; DAYS_PER_MONTH converts to the
# day count find_old_files actually uses (it works in days).
DEFAULT_OLD_DAYS = 90
DAYS_PER_MONTH = 30
DEFAULT_OLD_MONTHS = DEFAULT_OLD_DAYS // DAYS_PER_MONTH   # 3 months

# --- Duplicate finder ------------------------------------------------------ #
# Ignore files below this size. Tiny duplicates aren't worth the scan cost or
# the deletion risk; the space worth reclaiming lives in the big files (media,
# ISOs, build artifacts). 1 MB is a floor that keeps the result list meaningful.
DUP_MIN_SIZE = 1 * 1024 * 1024
# Bytes read for the cheap "do the heads match?" pre-hash. Two files of equal
# size but different first 64 KB can't be identical, so this rejects most
# candidates without ever reading them whole.
DUP_PARTIAL_READ = 64 * 1024
# Chunk size for the full-content hash of the survivors. 1 MB balances syscall
# overhead against memory; we never hold a whole file in RAM at once.
DUP_HASH_CHUNK = 1 * 1024 * 1024

# --- System reclaim (admin) ------------------------------------------------ #
# Windows component store ("WinSxS") cleanup. We never delete inside WinSxS
# ourselves — that would corrupt servicing — we ask DISM, the OS's own tool, to
# remove superseded components. /ResetBase makes the cleanup permanent (existing
# updates can no longer be uninstalled), which is the trade-off for max space.
DISM_COMPONENT_CLEANUP = [
    os.path.join(SYSTEM32, "Dism.exe"), "/online", "/Cleanup-Image",
    "/StartComponentCleanup", "/ResetBase",
]
# Turning hibernation off deletes hiberfil.sys (often several GB). This also
# disables Fast Startup, so it is offered as an explicit, reversible choice
# (re-enable with `powercfg /hibernate on`).
HIBERNATE_OFF = [os.path.join(SYSTEM32, "powercfg.exe"), "/hibernate", "off"]

# --- Treemap --------------------------------------------------------------- #
# Max child rectangles drawn per node. A treemap with thousands of slivers is
# unreadable and slow to draw; the biggest items are what the eye is for, so we
# cap and (the GUI) folds the remainder into one "(smaller items)" tile.
TREEMAP_CHILD_CAP = 150
# Don't draw a tile for anything below this fraction of the node — sub-pixel
# slivers just add noise. Folded into the remainder tile instead.
TREEMAP_MIN_FRACTION = 0.004

# Note: all colours/fonts/spacing for the PySide6 UI live in ui/tokens.py (the
# single rebrand point). config.py stays UI-toolkit-agnostic — values only.
