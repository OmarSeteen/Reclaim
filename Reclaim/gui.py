"""PySide6 entry point. Thin by design: build the app, apply the theme + saved
language, show the window, run the loop. All UI lives in the ui/ package; all
logic lives in the modules below it.
"""

import os
import sys
import traceback

from . import config, i18n, settings


def _write_crash_log(exc_type, exc_value, exc_tb):
    """Append the traceback to APP_DATA_DIR/crash.log. Returns the log path,
    or None if it couldn't be written — never raises, since a broken crash
    logger must not swallow the actual crash.
    """
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    path = os.path.join(config.APP_DATA_DIR, "crash.log")
    try:
        os.makedirs(config.APP_DATA_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
        return path
    except OSError:
        return None


def _install_crash_handler():
    """Catch anything that reaches the top of the event loop uncaught: log it,
    tell the user (best-effort — a dialog that itself fails must not hide the
    crash), then still chain to the default hook so the traceback reaches the
    console/debugger like normal. Without this, an unhandled exception in a
    --windowed build (no console) just kills the app with nothing to show for it.
    """

    def handle(exc_type, exc_value, exc_tb):
        path = _write_crash_log(exc_type, exc_value, exc_tb)
        try:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                i18n.t("Reclaim crashed"),
                i18n.t(
                    "Something went wrong and Reclaim needs to close.\n\n"
                    "Details were saved to:\n{path}"
                ).format(path=path or i18n.t("(couldn't write a crash log)")),
            )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle


def main():
    from PySide6.QtWidgets import QApplication

    from .ui import theme, widgets
    from .ui.shell import MainWindow

    _install_crash_handler()
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
