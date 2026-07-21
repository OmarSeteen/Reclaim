"""Entry point for `python -m Reclaim`. See run_app.py for the frozen-build
entry point (PyInstaller needs an absolute import; this one can be relative
since -m always runs it with Reclaim as its parent package).
"""

from .gui import main

if __name__ == "__main__":
    main()
