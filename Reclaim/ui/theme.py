"""Turns design tokens into a live Qt stylesheet, and handles theme/RTL/fonts.

Everything visual is assembled here from tokens.py so widgets never hard-code a
colour. We use string.Template ($name) rather than str.format because QSS is
full of literal {} braces — $-substitution leaves them untouched. Public API:
load_fonts(), apply(app, theme, rtl), repolish(widget).
"""

import os
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase

from . import tokens

# Remembers the last applied theme so a toggle can flip it without the caller
# tracking state. Set by apply().
_active_theme = tokens.DEFAULT_THEME


def load_fonts(app):
    """Register any bundled .ttf/.otf under ui/fonts/ so the token font stacks
    can resolve to them. Best-effort: missing dir or files just means we fall
    back to platform fonts, which is fine — never a hard failure."""
    fonts_dir = os.path.join(os.path.dirname(__file__), tokens.FONTS_DIR_NAME)
    if not os.path.isdir(fonts_dir):
        return
    for name in os.listdir(fonts_dir):
        if name.lower().endswith((".ttf", ".otf")):
            try:
                QFontDatabase.addApplicationFont(os.path.join(fonts_dir, name))
            except Exception:
                pass


def active_theme():
    return _active_theme


def _qss(palette, rtl):
    """Assemble the full stylesheet for one palette. `rtl` only changes the font
    stack (Arabic naskh) — layout mirroring is handled by Qt's layout direction.
    """
    family = ", ".join(tokens.FONT_ARABIC if rtl else tokens.FONT_LATIN)
    v = dict(palette)
    v.update(
        font=family,
        mono=", ".join(tokens.FONT_MONO),
        r_card=tokens.RADIUS_CARD,
        r_ctrl=tokens.RADIUS_CONTROL,
        r_pill=tokens.RADIUS_PILL,
        sb=tokens.SCROLLBAR_WIDTH,
        fs_body=tokens.FS_BODY,
        fs_heading=tokens.FS_HEADING,
        fs_display=tokens.FS_DISPLAY,
        fs_caption=tokens.FS_CAPTION,
        fs_mono=tokens.FS_MONO,
        sp1=tokens.SP_1,
        sp2=tokens.SP_2,
        sp3=tokens.SP_3,
        sp4=tokens.SP_4,
        sp6=tokens.SP_6,
    )
    return Template(_QSS_TEMPLATE).safe_substitute(v)


def apply(app, theme=None, rtl=False):
    """Apply a theme (and layout direction) to the whole application.

    Re-applying is how we switch theme or language at runtime: build the QSS for
    the chosen palette and set the app-wide layout direction. `theme=None` keeps
    the current one (used when only the direction changes).
    """
    global _active_theme
    if theme is not None:
        _active_theme = theme if theme in tokens.PALETTES else tokens.DEFAULT_THEME
    palette = tokens.PALETTES[_active_theme]
    app.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    app.setStyleSheet(_qss(palette, rtl))


def repolish(widget):
    """Re-evaluate a widget's style after a dynamic property changes.

    Qt only restyles on property change if you nudge it: unpolish→polish. Needed
    whenever we flip a custom property the QSS keys off (e.g. a button variant,
    or a card's 'selected' state)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# Property-driven QSS. Selectors key off dynamic properties (variant=…, role=…)
# so one widget class can render several looks. $-placeholders filled from tokens.
_QSS_TEMPLATE = """
* { font-family: $font; font-size: ${fs_body}px; color: $text; }
QMainWindow, QWidget#Page, QWidget#Root { background: $bg; }

/* Cards & surfaces */
QFrame#Card {
    background: $surface; border: 1px solid $border;
    border-radius: ${r_card}px;
}
QFrame#CardAlt { background: $surface_alt; border: 1px solid $border;
    border-radius: ${r_card}px; }

/* Dialogs follow the theme (without this they render dark in light mode). */
QDialog { background: $bg; }
QPlainTextEdit#Log {
    background: $surface; color: $text; border: 1px solid $border;
    border-radius: ${r_ctrl}px;
}
/* Folder lists in Settings — without this they render dark in light mode. */
QListWidget {
    background: $surface; color: $text; border: 1px solid $border;
    border-radius: ${r_ctrl}px;
}
QListWidget::item { padding: ${sp1}px ${sp2}px; }
QListWidget::item:selected { background: $accent_press; color: $on_accent; }

/* Small flat dismiss "✕" (admin-warning bar). */
QPushButton#LogClose {
    background: transparent; border: none; color: $muted; font-size: 11px;
    min-width: 22px; max-width: 22px; min-height: 20px;
}
QPushButton#LogClose:hover { color: $text; }

/* Scroll areas must show the page background, not the default (black under a
   global stylesheet). The viewport is transparent; the scroll body carries bg. */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget { background: transparent; }
QWidget#ScrollBody { background: $bg; }

/* Text roles */
QLabel[role="display"] { font-size: ${fs_display}px; font-weight: 600; color: $text; }
QLabel[role="heading"] { font-size: ${fs_heading}px; font-weight: 600; color: $text; }
/* Gold app name beside the title-bar logo (both themes use the gold accent). */
QLabel#BrandName { font-size: ${fs_display}px; font-weight: 700; color: $accent; }
QLabel[role="muted"]   { color: $muted; font-size: ${fs_caption}px; }
QLabel[role="size"]    { color: $accent; font-weight: 600; }
QLabel[role="good"]    { color: $good; font-weight: 600; }
QLabel#Mono, QPlainTextEdit#Log { font-family: $mono; font-size: ${fs_mono}px; }
QLabel#DiskInfo, QLabel#AdminInfo { color: $text; font-weight: 600; font-size: ${fs_caption}px; }

/* Disk-usage fill bar (one per drive in the header card). Gold fill normally,
   warm-red when nearly full as a hint the drive wants a clean. */
QProgressBar#DiskBar {
    background: $surface; border: 1px solid $border; border-radius: 4px;
}
QProgressBar#DiskBar::chunk { background: $accent; border-radius: 4px; }
QProgressBar#DiskBar[level="danger"]::chunk { background: $danger; }

/* Buttons — variant property selects the look */
QPushButton {
    background: $surface_alt; color: $text; border: 1px solid $border;
    border-radius: ${r_ctrl}px; padding: ${sp2}px ${sp4}px;
}
QPushButton:hover { border-color: $accent; }
QPushButton:pressed { background: $border; }
QPushButton:disabled { color: $muted; border-color: $border; }
QPushButton[variant="primary"] {
    background: $accent; color: $on_accent; border: none; font-weight: 600;
}
QPushButton[variant="primary"]:hover { background: $accent_hover; }
QPushButton[variant="primary"]:pressed { background: $accent_press; }
QPushButton[variant="primary"]:disabled { background: $surface_alt; color: $muted; }
QPushButton[variant="danger"] { background: $danger; color: #FFFFFF; border: none; }
QPushButton[variant="ghost"] { background: transparent; border: 1px solid $border; }
QPushButton[variant="ghost"]:hover { border-color: $accent; color: $accent; }

/* Custom title bar (frameless windows) + window buttons */
QWidget#TitleBar { background: $bg; }
QPushButton#WinBtn, QPushButton#WinClose {
    background: transparent; border: none; border-radius: 0;
    min-width: 17px; max-width: 17px; min-height: 15px; color: $muted;
    font-family: "Segoe MDL2 Assets"; font-size: 10px;
}
QPushButton#WinBtn:hover { background: $surface_alt; color: $text; }
QPushButton#WinClose:hover { background: $danger; color: #FFFFFF; }
QSizeGrip#Grip { background: transparent; width: 14px; height: 14px; }

/* Compact, centre-aligned sidebar control footer (Theme/lang/Settings/History/Log). */
QPushButton[compact="true"], QComboBox[compact="true"] {
    padding: ${sp1}px ${sp2}px; font-size: ${fs_caption}px; text-align: center;
}
/* The language button uses a menu; hide the dropdown indicator so its text
   stays centred, and theme the menu itself. */
QPushButton::menu-indicator { image: none; width: 0px; }
QMenu { background: $surface; color: $text; border: 1px solid $border; }
QMenu::item { padding: ${sp2}px ${sp4}px; }
QMenu::item:selected { background: $accent_press; color: $on_accent; }

/* Sidebar nav items — each is its own card (surface tile + border, rounded),
   dimmed by default, green with a green border when active. */
QPushButton#NavItem {
    background: $surface; border: 1px solid $border; border-radius: ${r_card}px;
    padding: ${sp3}px ${sp4}px; text-align: center; color: $muted; font-weight: 600;
}
QPushButton#NavItem:hover { border-color: $accent; color: $text; }
QPushButton#NavItem:checked { background: $surface_alt; border-color: $good; color: $good; }

/* Inputs */
QLineEdit, QSpinBox, QComboBox {
    background: $surface_alt; border: 1px solid $border;
    border-radius: ${r_ctrl}px; padding: ${sp2}px ${sp3}px; selection-background-color: $accent;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: $accent; }
QComboBox:hover { border-color: $accent; }
/* Seamless dropdown: no divider box, just a small arrow with breathing room. */
QComboBox { padding-right: ${sp6}px; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    border: none; background: transparent; width: 22px;
}
QComboBox::down-arrow { width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border; border-radius: ${r_ctrl}px;
    padding: ${sp1}px; outline: 0; selection-background-color: $accent_press;
}
QCheckBox::indicator,
QTableView::indicator, QTableWidget::indicator,
QTreeView::indicator, QTreeWidget::indicator {
    width: 16px; height: 16px; border: 1px solid $border; border-radius: 4px;
    background: $surface_alt;
}
QCheckBox::indicator:checked,
QTableView::indicator:checked, QTableWidget::indicator:checked,
QTreeView::indicator:checked, QTreeWidget::indicator:checked {
    background: $accent; border-color: $accent;
}
/* Define the hover states explicitly so the native style can't paint its blue
   hover ring over our indicator — hover looks identical to the resting state. */
QCheckBox::indicator:hover,
QTableView::indicator:hover, QTableWidget::indicator:hover,
QTreeView::indicator:hover, QTreeWidget::indicator:hover {
    border: 1px solid $border; background: $surface_alt;
}
QCheckBox::indicator:checked:hover,
QTableView::indicator:checked:hover, QTableWidget::indicator:checked:hover,
QTreeView::indicator:checked:hover, QTreeWidget::indicator:checked:hover {
    background: $accent; border-color: $accent;
}

/* Trees & tables */
QTreeView, QTableView, QTreeWidget, QTableWidget {
    background: $surface; alternate-background-color: $surface_alt;
    border: 1px solid $border; border-radius: ${r_card}px; outline: 0;
    gridline-color: $border;
}
QTreeView::item, QTableView::item,
QTreeWidget::item, QTableWidget::item { padding: ${sp2}px; }
/* Kill the native (Windows 11) rounded blue cell-hover; defined before
   :selected so a selected row still wins and keeps its accent fill. */
QTreeView::item:hover, QTableView::item:hover,
QTreeWidget::item:hover, QTableWidget::item:hover { background: transparent; }
QTreeView::item:selected, QTableView::item:selected,
QTreeWidget::item:selected, QTableWidget::item:selected {
    background: $accent_press; color: $on_accent;
}
QHeaderView::section {
    background: $surface_alt; color: $muted; border: none;
    border-bottom: 1px solid $border; padding: ${sp2}px ${sp3}px; font-weight: 600;
}
/* Round the header's outer corners so it sits flush inside the card's rounded
   border instead of poking square corners past it. */
QHeaderView::section:first { border-top-left-radius: ${r_card}px; }
QHeaderView::section:last  { border-top-right-radius: ${r_card}px; }

/* Tabs (busy state now uses the painted Spinner widget, not a progress bar) */
QTabBar::tab {
    background: transparent; color: $muted; padding: ${sp2}px ${sp4}px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabWidget::pane { border: none; }

/* Slim scrollbars */
QScrollBar:vertical { background: transparent; width: ${sb}px; margin: 0; }
QScrollBar::handle:vertical { background: $border; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar:horizontal { background: transparent; height: ${sb}px; margin: 0; }
QScrollBar::handle:horizontal { background: $border; border-radius: 5px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: ${sp2}px; }
"""
