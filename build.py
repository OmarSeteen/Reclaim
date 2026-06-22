"""Build a standalone Windows executable with PyInstaller.

Run:  python build.py   (after `pip install pyinstaller PySide6`)
Produces dist/Reclaim/Reclaim.exe — a windowed (no console) build.
PyInstaller's bundled PySide6 hooks collect the Qt runtime/plugins automatically.

Why --onedir and not --onefile: a one-file build unpacks itself into a
%TEMP%\\_MEIxxxxxx folder on every launch and only deletes it on a clean exit —
a crash or force-kill leaves that temp folder behind. For a tool whose whole job
is to NOT leave junk on the drive, that's the wrong default; it's also the
recommended mode for Qt apps (faster start, no extracting ~150 MB each run). We
ship a folder (zip it to distribute) that runs in place with no temp extraction.

Kept as a tiny wrapper so the build options live in one place instead of in a
README command the user has to retype correctly each time.
"""

import importlib.util
import os
import subprocess
import sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))

    # Fail loudly with a fix if the build tools aren't installed — otherwise the
    # subprocess just errors and it's easy to miss why no output appeared.
    missing = [m for m in ("PyInstaller", "PySide6")
               if importlib.util.find_spec(m) is None]
    if missing:
        print("Cannot build — missing package(s):", ", ".join(missing))
        print(f"Install them first:\n    {sys.executable} -m pip install "
              + " ".join(m.lower() if m == "PyInstaller" else m for m in missing))
        raise SystemExit(1)

    # Entry is the top-level launcher, NOT Reclaim/__main__.py: PyInstaller
    # runs the entry as `__main__` with no parent package, so the package's own
    # __main__ (relative `from .gui import ...`) would crash with "attempted
    # relative import with no known parent package". run_app.py imports absolutely.
    entry = os.path.join(here, "run_app.py")

    # Qt is huge. A QtWidgets app needs only QtCore/QtGui/QtWidgets, so we let the
    # PySide6 hook collect those (hidden-imports, since the UI imports them lazily
    # inside main() where static analysis can't see them) and exclude the big
    # modules we never use — that's the difference between a ~660 MB and a lean
    # bundle. `--collect-submodules Reclaim` pulls the whole app package
    # (incl. ui/), again because those imports are lazy.
    qt_excludes = [
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtDesigner", "PySide6.QtBluetooth", "PySide6.QtPositioning",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql",
        "PySide6.QtTest", "PySide6.QtNetworkAuth", "PySide6.QtWebChannel",
        "PySide6.QtWebSockets", "PySide6.QtSpatialAudio", "PySide6.QtScxml",
        "PySide6.QtNfc", "PySide6.QtRemoteObjects", "PySide6.QtHelp",
        "tkinter",   # the app's UI is PySide6; tkinter is never imported
    ]
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",             # run-in-place folder; no %TEMP% extraction
        "--windowed",           # no console window for a GUI app
        "--noconfirm",          # overwrite a previous build without prompting
        "--name", "Reclaim",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--collect-submodules", "Reclaim",
    ]
    # The .exe's file icon (Explorer, and the taskbar when pinned but not
    # running). The window/taskbar icon while running is set separately at
    # runtime (gui.py → setWindowIcon); this covers the static file icon. Skip
    # if absent so a checkout without the asset still builds.
    app_icon = os.path.join(here, "Reclaim", "ui", "assets", "app_icon.ico")
    if os.path.isfile(app_icon):
        cmd += ["--icon", app_icon]
    for mod in qt_excludes:
        cmd += ["--exclude-module", mod]
    # Bundle the UI's optional data dirs (brand logo, bundled fonts) when they
    # exist. --collect-submodules only grabs .py modules, not data files, so
    # these need an explicit --add-data; skipped silently when absent so the
    # build never fails just because no logo/font was dropped in.
    for data_dir in ("assets", "fonts"):
        src = os.path.join(here, "Reclaim", "ui", data_dir)
        if os.path.isdir(src):
            dest = os.path.join("Reclaim", "ui", data_dir)
            cmd += ["--add-data", f"{src}{os.pathsep}{dest}"]
    cmd.append(entry)
    print("Running:", " ".join(cmd))
    # Run from the repo root so build/ and dist/ land next to this script,
    # regardless of where the user invoked it from.
    code = subprocess.call(cmd, cwd=here)
    if code == 0:
        print("\nBuilt:", os.path.join(here, "dist", "Reclaim",
                                       "Reclaim.exe"))
        print("Zip the dist/Reclaim/ folder to distribute it.")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
