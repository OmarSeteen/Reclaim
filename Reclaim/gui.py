"""PySide6 entry point. Thin by design: build the app, apply the theme + saved
language, show the window, run the loop. All UI lives in the ui/ package; all
logic lives in the modules below it.
"""

import os
import sys

from . import config, i18n, settings


def main():
    from PySide6.QtWidgets import QApplication

    from .ui import theme, widgets
    from .ui.shell import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)

    # Brand icon for the window/taskbar. Optional like the logo/fonts: absent
    # file just leaves the default icon (see widgets.logo_icon).
    ic = widgets.logo_icon()
    if ic is not None:
        app.setWindowIcon(ic)

    theme.load_fonts(app)
    saved = settings.load()
    i18n.set_language(saved.get("language", config.DEFAULT_LANGUAGE))
    theme.apply(app, saved.get("theme", theme.tokens.DEFAULT_THEME), i18n.is_rtl())

    window = MainWindow()
    # Self-test hook: lets a build verify the (possibly frozen) app constructs
    # and imports everything without entering the blocking event loop. Set
    # RECLAIM_SELFTEST=1 (with QT_QPA_PLATFORM=offscreen) → builds, pumps once,
    # exits 0. A real failure still surfaces as a normal exception/non-zero exit.
    if os.environ.get("RECLAIM_SELFTEST"):
        app.processEvents()
        return
    window.show()
    sys.exit(app.exec())
