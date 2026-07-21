"""Resolvers for *where* each cleanup category lives — the safety allowlist.

This module is the single answer to "what is the tool allowed to touch?".
Every function returns only paths that actually exist, and the set of paths
returned across this whole file is the complete universe of locations cleanup
can ever delete from. If a path isn't produced here, it is never cleaned.

Keeping this separate from the deletion logic (cleaners.py) means the dangerous
question — *which* directories — is auditable in one short file, on its own.
"""

import glob
import os

from . import config, settings


def _existing_dirs(paths, allow_globs=True):
    """Expand any globs and drop anything that isn't a real directory.

    Returning only existing dirs means callers never have to guard against
    missing apps/profiles; an uninstalled browser simply contributes nothing.

    Built-in resolvers pass wildcard patterns (browser profiles, package names)
    and rely on expansion. User-supplied paths pass allow_globs=False: a '*' is
    never legal in a real Windows path, so treating it literally means a stray
    wildcard in a custom entry (e.g. ``C:\\Users\\*\\Documents``) can't silently
    fan the allowlist out across folders whose contents would then be cleared.
    """
    out = []
    for p in paths:
        if not p:
            continue
        if allow_globs and "*" in p:
            out.extend(glob.glob(p))
        else:
            out.append(p)
    return [p for p in out if os.path.isdir(p)]


def temp_dirs():
    """User + Windows temp folders."""
    c = set()
    for var in ("TEMP", "TMP"):
        v = os.environ.get(var)
        if v:
            c.add(v)
    if config.LOCALAPPDATA:
        c.add(os.path.join(config.LOCALAPPDATA, "Temp"))
    c.add(os.path.join(config.WINDIR, "Temp"))
    return _existing_dirs(c)


# Every Chromium-based browser stores its profiles under a "User Data" root and
# keeps the same cache subfolders inside each profile. Listing the roots here and
# expanding them uniformly means adding a browser is one line, not a new block.
# (vendor, *path-parts to the User Data root under LOCALAPPDATA)
_CHROMIUM_ROOTS = [
    ("Google", "Chrome", "User Data"),
    ("Microsoft", "Edge", "User Data"),
    ("BraveSoftware", "Brave-Browser", "User Data"),
    ("Vivaldi", "User Data"),
    (
        "Opera Software",
        "Opera Stable",
    ),  # Opera keeps profiles flat, not under User Data
    ("Opera Software", "Opera GX Stable"),
    ("Chromium", "User Data"),
]


def browser_cache_dirs():
    """Cache dirs for every Chromium browser profile, plus Firefox.

    We target only the Cache/Code Cache/GPUCache subfolders — never the profile
    root — so logins, cookies, history and passwords are left intact. Each root
    is globbed with "*" so every profile (Default, Profile 1, …) is covered.
    """
    paths = []
    if config.LOCALAPPDATA:
        for parts in _CHROMIUM_ROOTS:
            base = os.path.join(config.LOCALAPPDATA, *parts, "*")
            paths += [
                os.path.join(base, "Cache", "Cache_Data"),
                os.path.join(base, "Cache"),
                os.path.join(base, "Code Cache"),
                os.path.join(base, "GPUCache"),
            ]
        paths.append(
            os.path.join(
                config.LOCALAPPDATA, "Mozilla", "Firefox", "Profiles", "*", "cache2"
            )
        )
    return _existing_dirs(paths)


def app_cache_dirs():
    """Caches for common Electron/desktop apps: Discord, Spotify, Teams, Slack,
    Zoom, WhatsApp. These all rebuild on next launch, so only the cache
    subfolders are listed — never an app's settings or message store.
    """
    paths = []
    if config.APPDATA:
        paths += [
            os.path.join(config.APPDATA, "discord", "Cache"),
            os.path.join(config.APPDATA, "discord", "Code Cache"),
            os.path.join(config.APPDATA, "discord", "GPUCache"),
            os.path.join(config.APPDATA, "Spotify", "Storage"),
            os.path.join(config.APPDATA, "Microsoft", "Teams", "Cache"),
            os.path.join(config.APPDATA, "Microsoft", "Teams", "Code Cache"),
            os.path.join(config.APPDATA, "Microsoft", "Teams", "GPUCache"),
            os.path.join(config.APPDATA, "Slack", "Cache"),
            os.path.join(config.APPDATA, "Slack", "Code Cache"),
            os.path.join(config.APPDATA, "Slack", "GPUCache"),
            os.path.join(config.APPDATA, "Slack", "Service Worker", "CacheStorage"),
            os.path.join(config.APPDATA, "Zoom", "data", "Cache"),
        ]
    if config.LOCALAPPDATA:
        paths += [
            os.path.join(config.LOCALAPPDATA, "Spotify", "Storage"),
            os.path.join(
                config.LOCALAPPDATA,
                "Packages",
                "MSTeams_*",
                "LocalCache",
                "Microsoft",
                "MSTeams",
            ),
            os.path.join(config.LOCALAPPDATA, "Zoom", "bin", "Cache"),
            os.path.join(
                config.LOCALAPPDATA, "Packages", "*WhatsAppDesktop*", "LocalCache"
            ),
        ]
    return _existing_dirs(paths)


# Each dev toolchain caches downloaded packages/builds in a well-known spot. All
# of these are content-addressable or re-downloadable, so clearing them only
# costs a re-fetch on next build — never source or config. Listed as (env-base,
# *sub-parts); env-base is "USER", "LOCAL", or "APPDATA" and resolves below.
_DEV_CACHE_SPECS = [
    ("LOCAL", "npm-cache"),  # npm
    ("APPDATA", "npm-cache"),  # npm (older location)
    ("LOCAL", "Yarn", "Cache"),  # Yarn classic
    ("LOCAL", "pnpm", "store"),  # pnpm content-addressable store
    ("LOCAL", "pip", "Cache"),  # pip wheel/http cache
    ("USER", ".gradle", "caches"),  # Gradle
    ("USER", ".m2", "repository"),  # Maven
    ("USER", ".nuget", "packages"),  # NuGet global packages
    ("LOCAL", "NuGet", "v3-cache"),  # NuGet http cache
    ("USER", ".cargo", "registry", "cache"),  # Rust/Cargo
    ("USER", "go", "pkg", "mod", "cache", "download"),  # Go modules
    ("USER", "AppData", "Local", "Microsoft", "vscode-cpptools"),  # VS Code C++ tools
    ("APPDATA", "Code", "Cache"),  # VS Code disk cache
    ("APPDATA", "Code", "CachedData"),  # VS Code compiled bytecode
    ("APPDATA", "Code", "Code Cache"),
    ("APPDATA", "Code", "GPUCache"),
    ("LOCAL", "JetBrains", "*", "caches"),  # JetBrains IDE caches
]


def dev_cache_dirs():
    """Package-manager and build caches for common dev toolchains.

    Safe to clear: everything here is downloaded or generated and rebuilds on the
    next install/build. On a developer's drive this is often the single largest
    reclaimable bucket. Docker is intentionally excluded — its data lives in a
    VHDX that must be managed through Docker, not by deleting files underneath it.
    """
    bases = {
        "LOCAL": config.LOCALAPPDATA,
        "APPDATA": config.APPDATA,
        "USER": config.USERPROFILE,
    }
    paths = []
    for base_key, *parts in _DEV_CACHE_SPECS:
        base = bases.get(base_key, "")
        if base:
            paths.append(os.path.join(base, *parts))
    return _existing_dirs(paths)


def windows_update_dirs():
    """Old downloaded Windows Update payloads (needs admin to clear fully)."""
    d = os.path.join(config.WINDIR, "SoftwareDistribution", "Download")
    return [d] if os.path.isdir(d) else []


def delivery_optimization_dirs():
    """Peer-to-peer update-sharing cache. Rebuilds automatically; needs admin."""
    paths = [
        os.path.join(
            config.WINDIR,
            "ServiceProfiles",
            "NetworkService",
            "AppData",
            "Local",
            "Microsoft",
            "Windows",
            "DeliveryOptimization",
            "Cache",
        ),
        os.path.join(config.WINDIR, "SoftwareDistribution", "DeliveryOptimization"),
    ]
    return _existing_dirs(paths)


def wer_dirs():
    """Windows Error Reporting archives/queues plus per-user crash dumps.

    The ProgramData entries need admin; the per-user CrashDumps folder does not,
    so both are included and whatever is locked simply gets skipped at clean time.
    """
    paths = [
        os.path.join(
            config.PROGRAMDATA, "Microsoft", "Windows", "WER", "ReportArchive"
        ),
        os.path.join(config.PROGRAMDATA, "Microsoft", "Windows", "WER", "ReportQueue"),
        os.path.join(config.PROGRAMDATA, "Microsoft", "Windows", "WER", "Temp"),
    ]
    if config.LOCALAPPDATA:
        paths += [
            os.path.join(
                config.LOCALAPPDATA, "Microsoft", "Windows", "WER", "ReportArchive"
            ),
            os.path.join(
                config.LOCALAPPDATA, "Microsoft", "Windows", "WER", "ReportQueue"
            ),
            os.path.join(config.LOCALAPPDATA, "CrashDumps"),
        ]
    return _existing_dirs(paths)


def system_dump_files():
    """Kernel/system crash dumps (admin). Individual files, so kind="files".

    These are post-mortem artifacts written after a crash and are never needed
    for normal operation; a single MEMORY.DMP can be several GB. We list the
    files (not the folders) so Explorer's own dump folders stay in place.
    """
    paths = [
        os.path.join(config.WINDIR, "MEMORY.DMP"),
        os.path.join(config.WINDIR, "LiveKernelReports", "*.dmp"),
    ]
    minidump = os.path.join(config.WINDIR, "Minidump")
    paths.append(os.path.join(minidump, "*.dmp"))
    out = []
    for p in paths:
        if "*" in p:
            out.extend(glob.glob(p))
        elif os.path.isfile(p):
            out.append(p)
    return out


def windows_log_dirs():
    """Servicing/setup log folders (admin). Pure logs — regenerated as needed.

    CBS and DISM logs grow unbounded over a machine's life; Panther holds setup
    logs from the last upgrade. None are consulted at runtime, only for forensic
    debugging, so clearing their contents is safe.
    """
    paths = [
        os.path.join(config.WINDIR, "Logs", "CBS"),
        os.path.join(config.WINDIR, "Logs", "DISM"),
        os.path.join(config.WINDIR, "Panther"),
    ]
    return _existing_dirs(paths)


def windows_old_dir():
    """The previous-Windows backup left by a feature update, if present.

    Returns the single path (for size preview) or "" when there's nothing to
    clean. Removal itself is delegated to a guarded command, not a raw delete,
    because the tree is owned by TrustedInstaller — see cleaners/winapi.
    """
    d = os.path.join(config.SYSTEM_DRIVE, "Windows.old")
    return d if os.path.isdir(d) else ""


def thumbnail_cache_files():
    """Explorer thumbnail/icon cache DB files (regenerated on demand)."""
    if not config.LOCALAPPDATA:
        return []
    base = os.path.join(config.LOCALAPPDATA, "Microsoft", "Windows", "Explorer")
    if not os.path.isdir(base):
        return []
    return glob.glob(os.path.join(base, "thumbcache_*.db")) + glob.glob(
        os.path.join(base, "iconcache_*.db")
    )


def custom_clean_dirs():
    """User-added folders to clear, read from settings at call time.

    These still pass through _existing_dirs, so the allowlist stays the single
    gate: a custom entry is treated exactly like a built-in one and a path that
    doesn't exist (or was removed) simply contributes nothing.
    """
    data = settings.load()
    # allow_globs=False: custom entries are literal folders, never patterns.
    return _existing_dirs(data.get("custom_clean_dirs", []), allow_globs=False)


def downloads_dir():
    """Best guess at the user's Downloads folder, falling back to the profile."""
    d = os.path.join(config.USERPROFILE, "Downloads")
    if os.path.isdir(d):
        return d
    return config.USERPROFILE if os.path.isdir(config.USERPROFILE) else ""
