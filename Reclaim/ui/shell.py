"""The MainWindow: navigation shell + the small "host" the pages talk to.

Owns the cross-cutting UI (sidebar, header, disk-usage card, activity log,
busy/cancel state, theme + language toggles, Settings/History dialogs) and
exposes the host protocol the pages rely on: `pool`, `cancel_event`, `is_busy`,
`begin_busy`, `end_busy`, `set_busy_text`, `log` (thread-safe), `toast`,
`refresh_disk`.

Threading note: `log` is the only host method a worker thread calls directly, so
it goes through a Signal to hop onto the UI thread. Everything else is invoked
from Qt-delivered callbacks, which already run on the UI thread.
"""

import shutil
import threading
import time

from PySide6.QtCore import QByteArray, QEvent, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config, i18n, settings, winapi
from ..fsutils import human, list_drives
from ..i18n import t
from . import chrome, pages, theme, tokens, widgets
from .widgets import GhostButton, PrimaryButton, label


class MainWindow(QMainWindow):
    _log_line = Signal(str)  # worker-thread-safe path into the activity log

    def __init__(self):
        super().__init__()
        self.settings = settings.load()
        self.pool = QThreadPool.globalInstance()
        self.cancel_event = threading.Event()
        self._busy = False
        # Hidden activity-log store; shown on demand via the Log dialog (like
        # Settings/History) rather than an inline panel.
        self.log_view = QPlainTextEdit(self)
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.hide()

        self.setWindowTitle(config.APP_NAME)
        chrome.make_frameless(self)  # our own title bar (Windows)
        self.title_bar = None  # set in _build_ui when frameless
        self._grip = None
        self.resize(*tokens.WINDOW_SIZE)
        self._restore_geometry()
        self._log_line.connect(self._append_log)

        self._build_ui()
        self.refresh_disk()

    # -- construction ------------------------------------------------------ #
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Global controls live in the title bar when frameless (one uniform bar),
        # otherwise in the content header beside the native frame.
        self._build_controls()
        if chrome.FRAMELESS:
            self.title_bar = chrome.TitleBar(
                self,
                config.APP_NAME,
                subtitle=t("Map your drive, then reclaim space safely."),
                minmax=True,
                logo=True,
            )
            outer.addWidget(self.title_bar)

        body = QWidget()
        cols = QHBoxLayout(body)
        # Top margin lives on the body (not the right column) so the sidebar card
        # and the right column start at the same y — their top edges line up.
        # Kept small so the page title sits high, close under the title bar.
        cols.setContentsMargins(0, tokens.SP_1, 0, 0)
        cols.setSpacing(0)
        cols.addWidget(self._build_sidebar())

        right = QWidget()
        rcol = QVBoxLayout(right)
        rcol.setContentsMargins(tokens.SP_4, 0, tokens.SP_4, 0)
        # No inter-row spacing: the gap below the header lives in the header's own
        # bottom margin, so when the header hides (cards dismissed) the gap goes
        # with it and the page rises to line up with the sidebar nav.
        rcol.setSpacing(0)
        rcol.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.pages = [
            pages.CleanupPage(self),
            pages.AnalyzerPage(self),
            pages.DuplicatesPage(self),
            pages.OldFilesPage(self),
        ]
        for p in self.pages:
            self.stack.addWidget(p)
        rcol.addWidget(self.stack, 1)
        cols.addWidget(right, 1)
        outer.addWidget(body, 1)

        self.setCentralWidget(root)
        self._toast = widgets.Toast(self)
        self._grip = chrome.add_corner_grip(self)  # frameless resize corner
        self._apply_saved_inputs()
        self._nav_buttons[0].setChecked(True)

    def _build_controls(self):
        """Theme / language / Settings / History / Log — a compact, centered
        footer pinned to the bottom of the sidebar."""
        self.theme_btn = GhostButton(self._theme_label())
        self.theme_btn.clicked.connect(self._toggle_theme)
        # Language: a plain button with a menu — clickable, centred text like the
        # other buttons (the editable-combo trick broke both).
        self.lang_btn = GhostButton(i18n.LANGUAGES.get(i18n.get_language(), "English"))
        lang_menu = QMenu(self.lang_btn)
        for code, name in i18n.LANGUAGES.items():
            act = lang_menu.addAction(name)
            act.triggered.connect(lambda _checked=False, c=code: self._on_language(c))
        self.lang_btn.setMenu(lang_menu)
        self.settings_btn = GhostButton(t("Settings"))
        self.settings_btn.clicked.connect(self._open_settings)
        self.history_btn = GhostButton(t("History"))
        self.history_btn.clicked.connect(self._open_history)
        self.log_btn = GhostButton(t("Log"))  # opens the activity-log dialog
        self.log_btn.clicked.connect(self._open_log)
        self._controls = (
            self.theme_btn,
            self.lang_btn,
            self.settings_btn,
            self.history_btn,
            self.log_btn,
        )
        for w in self._controls:  # smaller footprint than the default size
            w.setProperty("compact", "true")
        # Donation CTA — an accent button, kept out of _controls so it stays the
        # full-size primary look (not the compact ghost footer style).
        self.kofi_btn = PrimaryButton(t("☕  Buy me a coffee"))
        self.kofi_btn.clicked.connect(self._open_kofi)

    def _build_sidebar(self):
        bar = QFrame()
        bar.setObjectName("CardAlt")
        bar.setFixedWidth(tokens.SIDEBAR_WIDTH)
        col = QVBoxLayout(bar)
        col.setContentsMargins(tokens.SP_3, tokens.SP_2, tokens.SP_3, tokens.SP_4)
        col.setSpacing(tokens.SP_2)
        if not chrome.FRAMELESS:
            # Native frame: keep the brand here (the title bar shows it otherwise).
            col.addWidget(label(config.APP_NAME, role="heading"))
            col.addWidget(
                label(t("Map your drive, then reclaim space safely."), role="muted")
            )
            col.addSpacing(tokens.SP_3)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons = []
        nav = [
            (t("Cleanup"), "fa5s.broom"),
            (t("Disk Analyzer"), "fa5s.chart-pie"),
            (t("Duplicates"), "fa5s.clone"),
            (t("Claim old files"), "fa5s.clock"),
        ]
        for index, (text, glyph) in enumerate(nav):
            btn = QPushButton(text)
            btn.setObjectName("NavItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            ic = widgets.icon(glyph, tokens.PALETTES[theme.active_theme()]["muted"])
            if ic is not None:
                btn.setIcon(ic)
            btn.clicked.connect(lambda _=False, i=index: self.stack.setCurrentIndex(i))
            self._nav_group.addButton(btn)
            self._nav_buttons.append(btn)
            col.addWidget(btn)

        # Equal stretch above and below centres the donation button in the empty
        # gap between the nav and the controls footer.
        col.addStretch(1)
        col.addWidget(self.kofi_btn)
        col.addStretch(1)
        # Compact controls footer, pinned to the bottom of the sidebar.
        for w in self._controls:
            col.addWidget(w)
        return bar

    def _build_header(self):
        # Brand + controls live in the title bar / sidebar, so the header just
        # holds the disk-usage card, the admin warning, and the busy bar. The
        # whole header hides when there's nothing to show (see _sync_header), so
        # dismissing the cards lets the page rise to align with the sidebar.
        self._disk_dismissed = False
        self._admin_dismissed = False
        header = QWidget()
        self._header = header
        col = QVBoxLayout(header)
        # Bottom margin = the gap before the page content. It's the header's own,
        # so a hidden header reserves zero space (rcol spacing is 0).
        col.setContentsMargins(0, 0, 0, tokens.SP_3)
        col.setSpacing(tokens.SP_2)

        # Disk usage card (dismissable). One labelled fill-bar block per drive,
        # rebuilt by refresh_disk into disk_rows — see _disk_row for why a bar
        # beats the old single bidi-mixed sentence (it scrambled under RTL).
        self.disk_card = QFrame()
        self.disk_card.setObjectName("CardAlt")
        drow = QHBoxLayout(self.disk_card)
        drow.setContentsMargins(tokens.SP_3, tokens.SP_2, tokens.SP_2, tokens.SP_2)
        self.disk_rows = QVBoxLayout()
        self.disk_rows.setContentsMargins(0, 0, 0, 0)
        self.disk_rows.setSpacing(tokens.SP_3)  # gap between per-drive blocks
        drow.addLayout(self.disk_rows, 1)
        # Centre the ✕ against the (now multi-line) card rather than pinning it to
        # the top corner — it reads as the card's dismiss, not the first drive's.
        drow.addWidget(self._dismiss_button(self._dismiss_disk), 0, Qt.AlignVCenter)
        col.addWidget(self.disk_card)

        # Admin warning card (only when not admin), dismissable.
        self._admin_card = None
        if not winapi.is_admin() and config.IS_WINDOWS:
            self._admin_card = self._build_admin_warning()
            col.addWidget(self._admin_card)

        # Busy row: a small spinner + live status + Cancel, shown only while an
        # operation runs (replaces the old full-width progress bar).
        self._busy_box = QWidget()
        brow = QHBoxLayout(self._busy_box)
        brow.setContentsMargins(0, 0, 0, 0)
        brow.setSpacing(tokens.SP_2)
        self.spinner = widgets.Spinner()
        brow.addWidget(self.spinner, 0, Qt.AlignVCenter)
        self.busy_label = label("", role="muted")
        brow.addWidget(self.busy_label, 0, Qt.AlignVCenter)
        brow.addStretch(1)
        self.cancel_btn = GhostButton(t("Cancel"))
        self.cancel_btn.clicked.connect(self._request_cancel)
        brow.addWidget(self.cancel_btn)
        self._busy_box.hide()
        col.addWidget(self._busy_box)
        return header

    def _dismiss_button(self, slot):
        btn = QPushButton("✕")
        btn.setObjectName("LogClose")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _dismiss_disk(self):
        self._disk_dismissed = True
        self._sync_header()

    def _dismiss_admin(self):
        self._admin_dismissed = True
        self._sync_header()

    def _sync_header(self):
        """Show each header card per its dismissed state and the busy bar per the
        busy state, and hide the whole header when all three are gone — so the
        content collapses up to the sidebar's level."""
        self.disk_card.setVisible(not self._disk_dismissed)
        if self._admin_card is not None:
            self._admin_card.setVisible(not self._admin_dismissed)
        self._busy_box.setVisible(self._busy)
        self._header.setVisible(
            (not self._disk_dismissed)
            or (self._admin_card is not None and not self._admin_dismissed)
            or self._busy
        )

    def _build_admin_warning(self):
        frame = QFrame()
        frame.setObjectName("CardAlt")
        row = QHBoxLayout(frame)
        row.setContentsMargins(tokens.SP_3, tokens.SP_2, tokens.SP_3, tokens.SP_2)
        admin_lbl = label(
            t(
                "⚠  Not admin — Update / Delivery Optimization / WER may be partly skipped."
            ),
        )
        admin_lbl.setObjectName("AdminInfo")  # bold, like the disk card
        row.addWidget(admin_lbl, 1)
        btn = GhostButton(t("Restart as admin"))
        btn.clicked.connect(winapi.relaunch_as_admin)
        row.addWidget(btn)
        row.addWidget(self._dismiss_button(self._dismiss_admin))
        return frame

    def _text_dialog(self, title, text):
        """A frameless dialog showing read-only text in the monospace Log view.
        Returns (dialog, view, content_layout) so callers add their own buttons.
        Shared by the Activity-log and Cleanup-history viewers."""
        dlg, col = chrome.frameless_dialog(self, title)
        dlg.resize(680, 440)
        view = QPlainTextEdit()
        view.setObjectName("Log")
        view.setReadOnly(True)
        view.setPlainText(text)
        col.addWidget(view, 1)
        return dlg, view, col

    def _open_kofi(self):
        """Open the donation page in the user's default browser. QDesktopServices
        hands off to the OS, so this never blocks or needs network access here."""
        QDesktopServices.openUrl(QUrl(config.KOFI_URL))

    def _open_log(self):
        """Show the activity log in a themed dialog (like Settings/History)."""
        dlg, _view, col = self._text_dialog(
            t("Activity log"), self.log_view.toPlainText()
        )
        close = GhostButton(t("Close"))
        close.clicked.connect(dlg.accept)
        col.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()

    # -- host protocol (called by pages) ----------------------------------- #
    def is_busy(self):
        return self._busy

    def begin_busy(self):
        self.cancel_event.clear()
        self._busy = True
        self.busy_label.setText(t("Working…"))  # pages refine this via set_busy_text
        self.spinner.start()
        self._sync_header()  # reveal the busy row (and the header)

    def end_busy(self):
        self._busy = False
        self.spinner.stop()
        self._sync_header()  # hide the busy row (and header if empty)

    def set_busy_text(self, text):
        """Live one-line status shown beside the spinner (e.g. a scan count).
        Called from page on_progress callbacks, which Qt delivers on the UI thread."""
        self.busy_label.setText(text)

    def log(self, msg):
        """Thread-safe: marshals onto the UI thread via a signal."""
        self._log_line.emit(str(msg))

    def _append_log(self, msg):
        # log_view is built in __init__ before this signal is connected, so it
        # always exists by the time a line arrives.
        self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def toast(self, msg):
        self._toast.show_message(msg)

    def refresh_disk(self):
        # One fill-bar block per mounted drive (grows with the drive count).
        while self.disk_rows.count():
            item = self.disk_rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        any_drive = False
        for drive in list_drives():
            try:
                u = shutil.disk_usage(drive)
            except OSError:
                continue
            any_drive = True
            pct = u.used / u.total * 100 if u.total else 0
            self.disk_rows.addWidget(
                self._disk_row(drive, human(u.free), human(u.total), pct)
            )
        if not any_drive:
            self.disk_rows.addWidget(label(t("Disk usage unavailable"), role="muted"))

    def _disk_row(self, drive, free, total, pct):
        """One drive's usage as a labelled fill-bar instead of a one-line
        sentence. The old string crammed the drive letter, two LTR figures
        ("144.7 GB") and three Arabic words into a single label, so the bidi
        algorithm reordered them into something unreadable under RTL. Here each
        piece is its own single-direction label and the proportion lives in the
        bar — so it reads correctly in both directions with no bidi mixing."""
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(tokens.SP_1)

        # Line 1: drive name (leading) and percent used (trailing).
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        name = label(drive)
        name.setObjectName("DiskInfo")
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(label(t("{pct}% used").format(pct=f"{pct:.0f}"), role="muted"))
        col.addLayout(top)

        # Line 2: the fill bar — turns danger-coloured when nearly full (a nudge
        # that the drive could use a clean).
        bar = QProgressBar()
        bar.setObjectName("DiskBar")
        bar.setTextVisible(False)
        bar.setRange(0, 100)
        bar.setValue(int(round(pct)))
        bar.setFixedHeight(tokens.SP_2)
        bar.setProperty("level", "danger" if pct >= 90 else "normal")
        col.addWidget(bar)

        # Line 3: free / total figures. Word and value are separate labels so the
        # LTR number never collides with the Arabic word — the layout mirrors as a
        # whole under RTL while each label stays single-direction.
        figs = QHBoxLayout()
        figs.setContentsMargins(0, 0, 0, 0)
        figs.addWidget(self._disk_fig(t("free"), free, "size"))
        figs.addStretch(1)
        figs.addWidget(self._disk_fig(t("total"), total, "muted"))
        col.addLayout(figs)
        return box

    @staticmethod
    def _disk_fig(word, value, value_role):
        """A "<word> <value>" pair as two adjacent labels (e.g. "free 144.7 GB"),
        word first so it reads label-then-figure in both LTR and mirrored RTL."""
        g = QWidget()
        h = QHBoxLayout(g)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(tokens.SP_1)
        h.addWidget(label(word, role="muted"))
        h.addWidget(label(value, role=value_role))
        return g

    def _request_cancel(self):
        self.cancel_event.set()
        self.log(t("Cancelling… (finishing the current step)"))

    # -- frameless chrome housekeeping ------------------------------------- #
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._grip is not None:  # park the resize grip in the corner
            self._grip.move(
                self.width() - self._grip.width() - 2,
                self.height() - self._grip.height() - 2,
            )
            self._grip.raise_()

    def changeEvent(self, event):
        super().changeEvent(event)
        # Keep the maximize/restore glyph correct after Aero-Snap or the OS
        # changing the window state behind our back.
        if event.type() == QEvent.WindowStateChange and self.title_bar is not None:
            self.title_bar.sync_max_glyph()

    # -- theme / language -------------------------------------------------- #
    def _theme_label(self):
        # The button names the mode it switches TO (the action), not the current
        # one: in dark mode it offers "Light mode", and vice versa.
        return t("Light mode") if theme.active_theme() == "dark" else t("Dark mode")

    def _toggle_theme(self):
        new = "light" if theme.active_theme() == "dark" else "dark"
        theme.apply(QApplication.instance(), new, i18n.is_rtl())
        self.theme_btn.setText(self._theme_label())
        self.settings["theme"] = new
        settings.save(self.settings)

    def _on_language(self, code):
        if code == i18n.get_language():
            return
        self.settings["language"] = code
        settings.save(self.settings)
        # Direction flips live; translated *text* applies on restart (rebuilding
        # the whole widget tree mid-session isn't worth the complexity/risk).
        i18n.set_language(code)
        theme.apply(QApplication.instance(), None, i18n.is_rtl())
        self.lang_btn.setText(i18n.LANGUAGES[code])
        chrome.notify(
            self, t("Restart needed"), t("Restart the app to apply the new language.")
        )

    # -- dialogs ----------------------------------------------------------- #
    def _open_history(self):
        dlg, view, col = self._text_dialog(
            t("Cleanup history"), settings.history_text()
        )

        def do_clear():
            settings.clear_history()
            view.setPlainText(settings.history_text())

        row = QHBoxLayout()
        clear = GhostButton(t("Clear history"))
        clear.clicked.connect(do_clear)
        close = GhostButton(t("Close"))
        close.clicked.connect(dlg.accept)
        row.addWidget(clear)
        row.addStretch(1)
        row.addWidget(close)
        col.addLayout(row)
        dlg.exec()

    def _open_settings(self):
        dlg, col = chrome.frameless_dialog(self, t("Settings"))
        dlg.resize(640, 580)
        col.addWidget(label(t("Custom folders to clean"), role="heading"))
        col.addWidget(
            label(
                t(
                    "Their contents are cleared like any cache. Added as "
                    "the 'Custom folders' cleanup category."
                ),
                role="muted",
            )
        )
        col.addLayout(self._list_editor("custom_clean_dirs"))
        col.addWidget(label(t("Folders to exclude from scans"), role="heading"))
        col.addWidget(
            label(
                t(
                    "Skipped by the Disk Analyzer, Duplicates and Old-files "
                    "scans (and everything under them)."
                ),
                role="muted",
            )
        )
        col.addLayout(self._list_editor("excluded_dirs"))
        close = GhostButton(t("Close"))
        close.clicked.connect(dlg.accept)
        col.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()

    def _list_editor(self, key):
        wrap = QHBoxLayout()
        lst = QListWidget()
        lst.addItems(self.settings.get(key, []))
        wrap.addWidget(lst, 1)
        col = QVBoxLayout()

        def save():
            self.settings[key] = [lst.item(i).text() for i in range(lst.count())]
            settings.save(self.settings)

        def add():
            d = QFileDialog.getExistingDirectory(self, t("Add…"), "/")
            if d and not lst.findItems(d, Qt.MatchExactly):
                lst.addItem(d)
                save()

        def remove():
            for item in lst.selectedItems():
                lst.takeItem(lst.row(item))
            save()

        add_btn = GhostButton(t("Add…"))
        add_btn.clicked.connect(add)
        rm_btn = GhostButton(t("Remove"))
        rm_btn.clicked.connect(remove)
        col.addWidget(add_btn)
        col.addWidget(rm_btn)
        col.addStretch(1)
        wrap.addLayout(col)
        return wrap

    # -- persistence ------------------------------------------------------- #
    def _restore_geometry(self):
        geo = self.settings.get("geometry_qt")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromHex(bytes(geo, "ascii")))
            except Exception:
                pass

    def _apply_saved_inputs(self):
        # Note: the Cleanup selection is deliberately NOT restored — categories
        # always start unchecked so nothing is ever pre-selected for deletion.
        s = self.settings
        _clean, analyze, dups, old = self.pages
        if s.get("scan_path"):
            # Re-select the saved drive if it's still mounted; otherwise leave
            # the first available drive selected.
            i = analyze.drive.findText(s["scan_path"])
            if i >= 0:
                analyze.drive.setCurrentIndex(i)
        if s.get("dup_path"):
            dups.path.setText(s["dup_path"])
        if s.get("old_path"):
            old.path.setText(s["old_path"])
        if str(s.get("old_months", "")).isdigit():
            old.months.setValue(int(s["old_months"]))
        if str(s.get("dup_min_mb", "")).isdigit():
            dups.min_mb.setValue(int(s["dup_min_mb"]))

    def closeEvent(self, event):
        # Stop any in-flight scan and let the pool drain before teardown, so a
        # worker can't emit into half-destroyed widgets on the way out.
        self.cancel_event.set()
        self.pool.waitForDone(3000)
        _clean, analyze, dups, old = self.pages
        self.settings.update(
            {
                "geometry_qt": bytes(self.saveGeometry().toHex()).decode("ascii"),
                "theme": theme.active_theme(),
                "language": i18n.get_language(),
                "scan_path": analyze.drive.currentText(),
                "dup_path": dups.path.text(),
                "old_path": old.path.text(),
                "old_months": str(old.months.value()),
                "dup_min_mb": str(dups.min_mb.value()),
            }
        )
        settings.save(self.settings)
        super().closeEvent(event)
