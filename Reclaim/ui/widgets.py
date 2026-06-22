"""Reusable, styled building blocks. No business logic — pure presentation.

Each component sets an objectName or a dynamic property that theme.py's QSS keys
off, so the look stays entirely in the stylesheet and these stay tiny. Icons go
through `icon()`, which uses qtawesome when available and degrades to no icon
otherwise (the import is optional, per the brief).
"""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from . import theme, tokens

try:                       # optional dependency — guarded
    import qtawesome as qta
except Exception:          # pragma: no cover - environment dependent
    qta = None

# The brand logo is an *optional* drop-in, exactly like the bundled fonts: if no
# file is present we fall back to the text brand / default window icon rather
# than failing. Filenames are matched best-first, so it works whether you drop a
# single transparent logo.svg/logo.png or the exported app_icon.ico + icon_*.png
# set — see assets/README.md.
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
# For the title-bar brand: an SVG (crisp at any DPI) or the largest raster we
# have, since it's smoothly downscaled to ~28px. A .ico isn't used here — its
# tiny embedded sizes would look soft scaled to the brand height.
_LOGO_NAMES = ("logo.svg", "logo.png", "icon_master_512.png",
               "icon_256x256.png", "icon_64x64.png")
# For the window/taskbar icon: a multi-resolution .ico is ideal on Windows
# (Qt picks the right embedded size); otherwise an SVG / largest raster.
_ICON_NAMES = ("app_icon.ico", "logo.svg", "logo.png",
               "icon_256x256.png", "icon_64x64.png", "icon_32x32.png")


def _first_existing(names):
    """First of `names` present in ui/assets/, or None. Lets the asset set be
    named either way (single logo.* or the exported icon_* bundle)."""
    for name in names:
        path = os.path.join(_ASSETS_DIR, name)
        if os.path.isfile(path):
            return path
    return None


def logo_pixmap(height):
    """Brand logo scaled to `height` px (aspect ratio kept), or None if there's
    no logo file (or it failed to load). Used by the title-bar brand."""
    path = _first_existing(_LOGO_NAMES)
    if not path:
        return None
    pix = QPixmap(path)
    if pix.isNull():
        return None
    return pix.scaledToHeight(height, Qt.SmoothTransformation)


def logo_icon():
    """QIcon of the brand logo for the window/taskbar, or None if no logo file."""
    path = _first_existing(_ICON_NAMES)
    if not path:
        return None
    ic = QIcon(path)
    return None if ic.isNull() else ic


def icon(name, color=None):
    """Return a QIcon for a Font Awesome / Material name, or None if qtawesome
    isn't installed. Callers must treat None as "show no icon" so the UI works
    either way."""
    if qta is None:
        return None
    try:
        return qta.icon(name, color=color or tokens.PALETTES[tokens.DEFAULT_THEME]["muted"])
    except Exception:
        return None


def label(text="", role=None, mono=False):
    """A QLabel tagged with a style role ('display'/'heading'/'muted'/'size'/…)."""
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if mono:
        lbl.setObjectName("Mono")
    return lbl


class Card(QFrame):
    """A rounded surface panel with comfortable padding and a vertical layout.

    The default container for every grouped block; `body` is the layout callers
    add into. `alt=True` uses the slightly raised surface for nested emphasis.
    """

    def __init__(self, alt=False, parent=None):
        super().__init__(parent)
        self.setObjectName("CardAlt" if alt else "Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(tokens.SP_4, tokens.SP_4, tokens.SP_4, tokens.SP_4)
        self.body.setSpacing(tokens.SP_2)


class PrimaryButton(QPushButton):
    """The single accent call-to-action per context."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setProperty("variant", "primary")
        self.setCursor(Qt.PointingHandCursor)


class GhostButton(QPushButton):
    """A quiet, outlined secondary action."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setProperty("variant", "ghost")
        self.setCursor(Qt.PointingHandCursor)


class DangerButton(QPushButton):
    """For irreversible/destructive actions (still gated by a confirm dialog)."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setProperty("variant", "danger")
        self.setCursor(Qt.PointingHandCursor)


class EmptyState(QWidget):
    """Centered icon + message shown instead of a blank panel when there's
    nothing yet (e.g. before a scan, or 'no files found')."""

    def __init__(self, message, glyph="fa5s.inbox", parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setAlignment(Qt.AlignCenter)
        ic = icon(glyph)
        if ic is not None:
            badge = QLabel()
            badge.setPixmap(ic.pixmap(40, 40))
            badge.setAlignment(Qt.AlignCenter)
            col.addWidget(badge)
        self._msg = label(message, role="muted")
        self._msg.setAlignment(Qt.AlignCenter)
        col.addWidget(self._msg)

    def set_message(self, text):
        self._msg.setText(text)


class ResultArea(QStackedWidget):
    """Wraps a results table/tree so an empty result shows a friendly message
    instead of a blank panel. Page builds it with the content widget, then calls
    `set_empty(...)` after each run to flip between the placeholder and content."""

    def __init__(self, content, message, glyph="fa5s.inbox", parent=None):
        super().__init__(parent)
        self._empty = EmptyState(message, glyph)
        self.content = content
        self.addWidget(self._empty)    # index 0
        self.addWidget(content)        # index 1

    def set_empty(self, is_empty, message=None):
        if message is not None:
            self._empty.set_message(message)
        self.setCurrentIndex(0 if is_empty else 1)


class Spinner(QWidget):
    """A small indeterminate busy spinner: a gold arc that rotates while active.

    Painted with QPainter (a rotating 270° arc) rather than a GIF/asset, so it
    needs no dependency and follows the active theme's accent colour. start()
    runs the timer and shows it; stop() halts the timer and hides it — cheaper
    than repainting a hidden widget, and it disappears cleanly when idle."""

    def __init__(self, diameter=16, parent=None):
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(diameter, diameter)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self.hide()

    def start(self):
        if not self._timer.isActive():
            self._timer.start(60)        # ~16 fps: smooth enough, negligible cost
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _step(self):
        self._angle = (self._angle + 20) % 360
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(tokens.PALETTES[theme.active_theme()]["accent"]))
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        rect = self.rect().adjusted(2, 2, -2, -2)
        # Qt arc angles are in 1/16°; sweep 270° from a rotating start angle.
        p.drawArc(rect, -self._angle * 16, 270 * 16)
        p.end()


class Toast(QLabel):
    """A transient, self-dismissing message pinned near the bottom of a parent.

    Lighter than a modal dialog for "done"/"freed X" confirmations. Positioned
    over its parent so it doesn't disturb the layout, and fades out on a timer.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setProperty("role", "good")
        self.setStyleSheet(
            f"background: {tokens.PALETTES[tokens.DEFAULT_THEME]['surface_alt']};"
            f"border: 1px solid {tokens.PALETTES[tokens.DEFAULT_THEME]['border']};"
            f"border-radius: {tokens.RADIUS_PILL}px; padding: {tokens.SP_2}px {tokens.SP_4}px;"
        )
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text, msecs=3200):
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            x = (parent.width() - self.width()) // 2
            y = parent.height() - self.height() - tokens.SP_6
            self.move(max(0, x), max(0, y))
        self.show()
        self.raise_()
        self._timer.start(msecs)
