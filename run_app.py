"""Frozen-app entry point for PyInstaller.

PyInstaller executes its entry script as the top-level ``__main__`` module, with
no parent package — so it cannot be ``Reclaim/__main__.py`` (whose
``from .gui import main`` is a *relative* import and fails without a parent).
This thin top-level launcher uses an *absolute* import instead, which works both
frozen and from source. Normal use is unaffected: ``python -m Reclaim``
still goes through the package's own ``__main__.py``.
"""

from Reclaim.gui import main

if __name__ == "__main__":
    main()
