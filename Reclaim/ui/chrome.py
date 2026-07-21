"""Custom window chrome: a themed title bar for frameless windows + dialogs.

On Windows we drop the OS title bar (FramelessWindowHint) and supply our own,
so the window looks like one uniform surface instead of app-on-top-of-a-grey-bar.
Dragging uses QWindow.startSystemMove (so Aero-Snap and double-click-maximize
still feel native) and resizing uses a corner QSizeGrip. One TitleBar class
serves the MainWindow (min/max/close) and the dialogs (close only), so the look
is consistent. On non-Windows we leave the native frame alone and callers keep
their controls in the normal header — `FRAMELESS` is the switch for that.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..i18n import is_rtl, t
from . import tokens, widgets
from .widgets import GhostButton, PrimaryButton, label

# Custom chrome only on Windows; elsewhere the native frame is fine (and avoids
# the work of reimplementing move/resize/snap per platform).
FRAMELESS = config.IS_WINDOWS

# Title-bar glyphs from "Segoe MDL2 Assets" (present on Windows 10/11) — the
# exact native minimize/maximize/restore/close shapes. The font is set on these
# buttons in the stylesheet; off Windows the chrome isn't used anyway.
_MIN, _MAX, _RESTORE, _CLOSE = "", "", "", ""


def make_frameless(window):
    """Drop the OS frame on Windows. The caller adds a TitleBar at the top of its
    own layout (and, for the main window, a corner grip)."""
    if FRAMELESS:
        window.setWindowFlag(Qt.FramelessWindowHint, True)


class TitleBar(QWidget):
    """Draggable title bar: app/dialog name, optional extra controls, and window
    buttons. `minmax=False` gives a dialog just a close button."""

    def __init__(self, window, title, subtitle=None, minmax=True, extra=(), logo=False):
        super().__init__(window)
        self.setObjectName("TitleBar")
        self._win = window
        self._minmax = minmax

        row = QHBoxLayout(self)
        # No top margin: the window buttons hug the top-right corner (native feel)
        # rather than floating centred in a tall bar.
        row.setContentsMargins(tokens.SP_4, 0, 0, 0)
        row.setSpacing(tokens.SP_2)
        # Brand block: app name (or logo) with the tagline stacked beneath it.
        brand = QVBoxLayout()
        brand.setContentsMargins(0, tokens.SP_2, 0, tokens.SP_2)
        brand.setSpacing(0)
        # The logo replaces the app-name text in dark mode (per the design); the
        # text is the fallback for light mode and when no logo file is present.
        # Only the main window opts in (logo=True) — dialog title bars stay text.
        # Brand name beside the logo (a transparent image that reads on both
        # themes). With a logo present the name goes gold (#BrandName) and sits to
        # its right; with no logo the plain heading text stands alone. Only the
        # main window opts in (logo=True) — dialog title bars stay text.
        self._title_label = label(title, role="heading")
        self._logo_label = None
        if logo:
            pix = widgets.logo_pixmap(tokens.BRAND_LOGO_HEIGHT)
            if pix is not None:
                self._logo_label = QLabel()
                self._logo_label.setPixmap(pix)
        sub = label(subtitle, role="muted") if subtitle else None
        if self._logo_label is not None and is_rtl():
            # Arabic: stack the name + tagline in a text column and centre the
            # logo vertically against the whole block (it lands on the trailing
            # right edge under RTL). More balanced than pinning the logo to the
            # first line, and the tagline now lines up under the name on its own
            # rather than sitting alone in the window corner.
            self._title_label.setObjectName("BrandName")  # gold accent in QSS
            # "Reclaim" is Latin, so Qt left-aligns it by default even under RTL.
            # Force it (and the tagline) to the trailing right edge so the name
            # sits directly above the start of the Arabic tagline ("حلّل").
            self._title_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if sub is not None:
                sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(0)
            text_col.addWidget(self._title_label)
            if sub is not None:
                text_col.addWidget(sub)
            name_row = QHBoxLayout()
            name_row.setContentsMargins(0, 0, 0, 0)
            name_row.setSpacing(tokens.SP_2)
            name_row.addWidget(self._logo_label, 0, Qt.AlignVCenter)
            name_row.addLayout(text_col)
            name_row.addStretch(1)
            brand.addLayout(name_row)
        elif self._logo_label is not None:
            # LTR with logo: logo inline beside the name on the first line.
            self._title_label.setObjectName("BrandName")  # gold accent in QSS
            name_row = QHBoxLayout()
            name_row.setContentsMargins(0, 0, 0, 0)
            name_row.setSpacing(tokens.SP_2)
            name_row.addWidget(self._logo_label, 0, Qt.AlignVCenter)
            name_row.addWidget(self._title_label, 0, Qt.AlignVCenter)
            name_row.addStretch(1)
            brand.addLayout(name_row)
            if sub is not None:
                brand.addWidget(sub)
        else:
            brand.addWidget(self._title_label)
            if sub is not None:
                brand.addWidget(sub)
        row.addLayout(brand)
        row.addStretch(1)
        for w in extra:  # e.g. Theme / language / Settings
            row.addWidget(w, 0, Qt.AlignTop)
        if minmax:
            row.addWidget(
                self._button(_MIN, window.showMinimized, "WinBtn"), 0, Qt.AlignTop
            )
            self._max_btn = self._button(_MAX, self._toggle_max, "WinBtn")
            row.addWidget(self._max_btn, 0, Qt.AlignTop)
        row.addWidget(self._button(_CLOSE, window.close, "WinClose"), 0, Qt.AlignTop)

    def _button(self, glyph, slot, name):
        btn = QPushButton(glyph, self)
        btn.setObjectName(name)
        btn.setFocusPolicy(Qt.NoFocus)  # buttons shouldn't grab keyboard focus
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _toggle_max(self):
        self._win.showNormal() if self._win.isMaximized() else self._win.showMaximized()
        self.sync_max_glyph()

    def sync_max_glyph(self):
        """Keep the maximize/restore glyph correct (e.g. after an Aero-Snap)."""
        if self._minmax:
            self._max_btn.setText(_RESTORE if self._win.isMaximized() else _MAX)

    # Native move (with snap) when dragging an empty part of the bar; the window
    # buttons consume their own clicks, so this only fires on the bar background.
    def mousePressEvent(self, event):
        if FRAMELESS and event.button() == Qt.LeftButton:
            handle = self._win.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if FRAMELESS and self._minmax:
            self._toggle_max()
        super().mouseDoubleClickEvent(event)


def add_corner_grip(parent):
    """Return a QSizeGrip for resizing a frameless window, or None when native.
    The caller repositions it to the bottom-right corner on resize."""
    if not FRAMELESS:
        return None
    grip = QSizeGrip(parent)
    grip.setObjectName("Grip")
    return grip


def frameless_dialog(parent, title):
    """A dialog wearing our chrome (title bar with a close button). Returns
    (dialog, content_layout); the caller fills content_layout. On non-Windows
    it's a plain dialog with the native frame and no extra title bar."""
    dlg = QDialog(parent)
    make_frameless(dlg)
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    if FRAMELESS:
        outer.addWidget(TitleBar(dlg, title, minmax=False))
    body = QWidget()
    body.setObjectName("Page")  # carries the themed page background
    content = QVBoxLayout(body)
    content.setContentsMargins(tokens.SP_4, tokens.SP_3, tokens.SP_4, tokens.SP_4)
    outer.addWidget(body, 1)
    return dlg, content


def notify(parent, title, text):
    """Themed, frameless replacement for QMessageBox.information / .critical."""
    dlg, col = frameless_dialog(parent, title)
    dlg.setMinimumWidth(380)
    msg = label(text)
    msg.setWordWrap(True)
    col.addWidget(msg, 1)
    ok = PrimaryButton(t("OK"))
    ok.clicked.connect(dlg.accept)
    col.addWidget(ok, 0, Qt.AlignRight)
    dlg.exec()


def confirm(parent, title, text):
    """Themed, frameless replacement for QMessageBox.question. Returns True if the
    user confirmed (the primary button), False on cancel/close."""
    dlg, col = frameless_dialog(parent, title)
    dlg.setMinimumWidth(420)
    msg = label(text)
    msg.setWordWrap(True)
    col.addWidget(msg, 1)
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = GhostButton(t("Cancel"))
    cancel.clicked.connect(dlg.reject)
    ok = PrimaryButton(t("OK"))
    ok.clicked.connect(dlg.accept)
    row.addWidget(cancel)
    row.addWidget(ok)
    col.addLayout(row)
    return dlg.exec() == QDialog.Accepted
