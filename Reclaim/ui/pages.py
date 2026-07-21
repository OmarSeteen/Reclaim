"""The feature screens. Each page is a QWidget that calls the existing logic
modules and never touches the filesystem on the UI thread (it goes through
`host` + workers). Pages know nothing about the shell beyond a small host
protocol: `pool`, `cancel_event`, `is_busy()`, `begin_busy()`, `end_busy()`,
`set_busy_text(msg)`, `log(msg)` (thread-safe), `toast(msg)`, `refresh_disk()`.
"""

import os
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import analyzer, cleaners, config, locations, settings, treemap, winapi
from ..fsutils import (
    disk_free,
    find_old_files,
    human,
    list_drives,
    months_old,
    move_files,
)
from ..i18n import t
from . import chrome, theme, tokens, workers
from .widgets import Card, DangerButton, GhostButton, PrimaryButton, ResultArea, label


def _table(headers, stretch_col):
    """A read-only, row-selecting table with the given headers. No row-hover
    effect (callers that want one set tooltips instead)."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)  # cleaner: rely on alternating rows, not gridlines
    table.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.Stretch)
    return table


class _SortItem(QTableWidgetItem):
    """A table cell that sorts by a stored numeric key instead of its text, so
    a 'Size'/'Age' column orders by bytes/seconds rather than lexicographically
    (otherwise '9.0 MB' would sort after '10.0 MB')."""

    def __init__(self, text, sort_key):
        super().__init__(text)
        self._key = sort_key

    def __lt__(self, other):
        if isinstance(other, _SortItem):
            return self._key < other._key
        return super().__lt__(other)


class PageBase(QWidget):
    """Shared plumbing: a guarded `_run` that pushes a job to the pool, manages
    the busy state, disables this page's action buttons, and routes
    error/cancel to the activity log so every page handles them identically."""

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.setObjectName("Page")
        self.action_buttons = []

    def _run(self, make_job, on_result=None, on_progress=None, then=None):
        if self.host.is_busy():
            return
        self.host.begin_busy()
        for b in self.action_buttons:
            b.setEnabled(False)

        def finished():
            for b in self.action_buttons:
                b.setEnabled(True)
            self.host.end_busy()
            self.host.refresh_disk()
            # Runs after the busy state is cleared, so `then` may start another
            # job (e.g. re-analyze after a clean) without tripping the busy guard.
            if then:
                then()

        workers.submit(
            self.host.pool,
            make_job,
            on_result=on_result,
            on_progress=on_progress,
            on_error=lambda m: self.host.log(f"ERROR: {m}"),
            on_cancelled=lambda: self.host.log(t("Cancelled.")),
            on_finished=finished,
        )

    def _ask(self, title, text):
        return chrome.confirm(self, t(title), text)


# ----------------------------------------------------------------------------- #
#  Cleanup
# ----------------------------------------------------------------------------- #
class CleanupPage(PageBase):
    def __init__(self, host):
        super().__init__(host)
        self.cleaners = cleaners.CLEANERS
        self.checks = {}
        self.size_labels = {}
        self._cards = {}  # key -> the card QWidget (for re-sorting)
        self._sizes = {}  # key -> last analyzed size (drives the order)

        outer = QVBoxLayout(self)
        # No top margin: the page title hugs the top of the content area.
        outer.setContentsMargins(
            tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN
        )
        outer.setSpacing(tokens.PAGE_SPACING)
        outer.addWidget(label(t("Cleanup"), role="display"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host_w = QWidget()
        host_w.setObjectName("ScrollBody")  # so the QSS gives it the page bg
        self._cards_layout = QVBoxLayout(host_w)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(tokens.SP_3)
        for c in self.cleaners:
            self._cards_layout.addWidget(self._card(c))
        self._cards_layout.addStretch(1)
        scroll.setWidget(host_w)
        outer.addWidget(scroll, 1)

        self.total = label(t("Calculating reclaimable space…"), role="good")
        outer.addWidget(self.total)

        bar = QHBoxLayout()
        sel_all = GhostButton(t("Select all"))
        sel_all.clicked.connect(lambda: self._set_all(True))
        desel = GhostButton(t("Deselect all"))
        desel.clicked.connect(lambda: self._set_all(False))
        preview = GhostButton(t("Preview"))
        preview.clicked.connect(self.on_preview)
        recommend = GhostButton(t("Recommended clean"))
        recommend.clicked.connect(self.on_recommended)
        clean = PrimaryButton(t("Clean selected"))
        clean.clicked.connect(self.on_clean)
        for w in (sel_all, desel):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (preview, recommend, clean):
            bar.addWidget(w)
        outer.addLayout(bar)
        self.action_buttons = [preview, recommend, clean]

        # No "Analyze" button: sizes are computed automatically on launch (off
        # the UI thread) and the total is always shown. Cards are then sorted by
        # reclaimable size, biggest first. Deferred to the next event-loop tick
        # so the rest of the window (log panel, etc.) exists before it logs.
        QTimer.singleShot(0, self._analyze)

    def _card(self, c):
        card = Card()
        top = QHBoxLayout()
        chk = QCheckBox(t(c["label"]))
        chk.setChecked(False)  # nothing selected by default
        self.checks[c["key"]] = chk
        size = label("—", role="size")
        self.size_labels[c["key"]] = size
        top.addWidget(chk)
        top.addStretch(1)
        top.addWidget(size)
        card.body.addLayout(top)
        desc = label(t(c["desc"]), role="muted")
        desc.setWordWrap(True)
        card.body.addWidget(desc)
        self._cards[c["key"]] = card
        return card

    def _sort_cards(self):
        """Reorder the cards biggest-reclaimable-first using the latest sizes."""
        order = sorted(
            self.cleaners, key=lambda c: self._sizes.get(c["key"], 0), reverse=True
        )
        for index, c in enumerate(order):
            self._cards_layout.insertWidget(index, self._cards[c["key"]])

    def _set_all(self, value):
        for chk in self.checks.values():
            chk.setChecked(value)

    def _selected(self):
        return [c for c in self.cleaners if self.checks[c["key"]].isChecked()]

    def _analyze(self):
        """Compute every category's reclaimable size off-thread, show the total,
        and sort the cards biggest-first. Runs automatically on launch and after
        a clean — there's no manual Analyze button."""
        self.host.log(t("Analyzing… (read-only)"))

        def make(progress):
            def job():
                total = 0
                for c in self.cleaners:
                    if self.host.cancel_event.is_set():
                        break  # honour Cancel; show what we have so far
                    size, count = cleaners.analyze_cleaner(c)
                    total += size
                    progress((c["key"], size))
                return total

            return job

        def on_size(payload):
            key, size = payload
            self._sizes[key] = size
            self.size_labels[key].setText(human(size))

        def on_total(total):
            self.total.setText(t("Total reclaimable: {v}").format(v=human(total)))
            self.host.log(t("Total reclaimable: {v}").format(v=human(total)))
            self._sort_cards()

        self._run(make, on_result=on_total, on_progress=on_size)

    def on_preview(self):
        selected = self._selected()
        if not selected:
            chrome.notify(self, t("Nothing selected"), t("Tick at least one category."))
            return

        def make(progress):
            return lambda: [(c["label"], cleaners.preview_cleaner(c)) for c in selected]

        self._run(make, on_result=self._show_preview)

    def _show_preview(self, sections):
        dlg, col = chrome.frameless_dialog(self, t("Preview — what would be removed"))
        dlg.resize(760, 540)
        col.addWidget(
            label(
                t(
                    "Nothing is deleted here. This is exactly what "
                    "'Clean selected' would remove."
                ),
                role="muted",
            )
        )
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels([t("Category / path"), t("Size")])
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for cat_label, rows in sections:
            total = sum(sz for _p, sz in rows)
            head = QTreeWidgetItem(
                tree, [f"{t(cat_label)} — {len(rows)}", human(total)]
            )
            for path, sz in rows:
                QTreeWidgetItem(head, [str(path), human(sz)])
            if not rows:
                QTreeWidgetItem(head, [t("(nothing found)"), ""])
            head.setExpanded(True)
        col.addWidget(tree, 1)
        close = GhostButton(t("Close"))
        close.clicked.connect(dlg.accept)
        col.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()

    def on_recommended(self):
        for c in self.cleaners:
            self.checks[c["key"]].setChecked(c["key"] in config.RECOMMENDED_KEYS)
        self.on_clean()

    def on_clean(self):
        selected = self._selected()
        if not selected:
            chrome.notify(self, t("Nothing selected"), t("Tick at least one category."))
            return
        if (
            any(c["needs_admin"] for c in selected)
            and not winapi.is_admin()
            and config.IS_WINDOWS
        ):
            if not self._ask(
                "Administrator recommended",
                t(
                    "Some selected items need admin to clear fully.\n"
                    "Locked files are skipped.\n\nContinue anyway?"
                ),
            ):
                return
        names = "\n".join(f"   •  {t(c['label'])}" for c in selected)
        if not self._ask(
            "Confirm cleanup",
            t(
                "Permanently delete the contents of:\n\n{names}\n\n"
                "Files in use are skipped automatically.\n\nProceed?"
            ).format(names=names),
        ):
            return

        log = self.host.log
        log(t("Starting cleanup…"))

        def make(progress):
            def job():
                drive = config.SYSTEM_DRIVE if config.IS_WINDOWS else "/"
                before = disk_free(drive)
                total = 0
                for c in selected:
                    if self.host.cancel_event.is_set():
                        break
                    log(f"  {t(c['label'])}…")
                    total += cleaners.clean_cleaner(c, log)
                    progress((c["key"], 0))
                after = disk_free(drive)
                # Concise history line: amount + drive free before/after.
                settings.record_cleanup(
                    f"Freed {human(total)}.  {drive} free "
                    f"{human(before)} -> {human(after)}."
                )
                return total

            return job

        def cleared(payload):
            key, _ = payload
            self.size_labels[key].setText("—")

        def done(total):
            self.total.setText(t("Freed {v} this run").format(v=human(total)))
            self.host.toast(
                t("Cleanup complete.\nFreed approximately {v}.")
                .format(v=human(total))
                .replace("\n", " ")
            )
            self.host.log(
                t("Cleanup complete.\nFreed approximately {v}.")
                .format(v=human(total))
                .replace("\n", " ")
            )

        # Re-analyze afterward so sizes/total/order reflect what's left.
        self._run(make, on_result=done, on_progress=cleared, then=self._analyze)


# ----------------------------------------------------------------------------- #
#  Disk Analyzer (+ treemap)
# ----------------------------------------------------------------------------- #
class TreemapView(QWidget):
    """Paints squarified treemap tiles with QPainter; click a folder to drill in.

    Layout maths live in treemap.squarify (pure, tested); this only paints the
    rectangles it returns and hit-tests clicks. Emits `navigated` with the new
    node path so the page can update its breadcrumb/Up button.
    """

    navigated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.setMouseTracking(True)
        self._dir_sizes = {}
        self._root = None
        self._node = None
        self._tiles = []  # (QRectF, path, is_dir)

    def set_scan(self, root, dir_sizes):
        self._dir_sizes = dir_sizes
        self._root = root
        self._node = root
        self.update()
        self.navigated.emit(root)

    def go_up(self):
        if not self._node or self._node == self._root:
            return
        parent = os.path.dirname(self._node)
        if self._root and not parent.startswith(self._root):
            parent = self._root
        self._node = parent or self._root
        self.update()
        self.navigated.emit(self._node)

    def paintEvent(self, _event):
        self._tiles = []
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        pal = tokens.PALETTES[theme.active_theme()]
        painter.fillRect(self.rect(), QColor(pal["surface"]))
        if not self._node:
            return
        children = _dir_children(self._node, self._dir_sizes)
        cap = config.TREEMAP_CHILD_CAP
        total = self._dir_sizes.get(self._node, sum(c[0] for c in children)) or 1
        floor = total * config.TREEMAP_MIN_FRACTION
        big = [c for c in children[:cap] if c[0] >= floor]
        rest = sum(c[0] for c in children[len(big) :])
        items = [(c[0], c) for c in big]
        if rest > 0:
            items.append((rest, ("rest",)))
        rects = treemap.squarify(items, 2, 2, self.width() - 4, self.height() - 4)
        colors = tokens.TREEMAP_COLORS
        color_idx = 0
        for payload, x, y, w, h in rects:
            if w < 1 or h < 1:
                continue
            rect = QRectF(x, y, w - 1, h - 1)
            if payload[0] == "rest":
                # The catch-all tile stays neutral so it doesn't read as a category.
                fill, name, path, is_dir, size = (
                    pal["surface_alt"],
                    t("(smaller items)"),
                    None,
                    False,
                    rest,
                )
                text_color = pal["text"]
            else:
                size, path, is_dir, name = payload
                # One hue per tile, cycling the categorical palette, so the map
                # reads like a data-viz dashboard rather than a flat gold sheet.
                fill = colors[color_idx % len(colors)]
                color_idx += 1
                # Labels are always white on the saturated swatches — legible on
                # every hue regardless of the active (dark/light) theme.
                text_color = "#FFFFFF"
            painter.fillRect(rect, QColor(fill))
            painter.setPen(QColor(pal["bg"]))
            painter.drawRect(rect)
            if path is not None:
                self._tiles.append((rect, path, is_dir))
            if w > 54 and h > 26:
                painter.setPen(QColor(text_color))
                painter.drawText(
                    QRectF(x + 6, y + 5, w - 10, h - 8),
                    Qt.AlignLeft | Qt.AlignTop,
                    f"{name}\n{human(size)}",
                )
        painter.end()

    def mousePressEvent(self, event):
        pos = event.position()
        for rect, path, is_dir in self._tiles:
            if rect.contains(pos):
                if is_dir and os.path.isdir(path):
                    self._node = path
                    self.update()
                    self.navigated.emit(path)
                else:
                    _open_path(path)
                return


class AnalyzerPage(PageBase):
    def __init__(self, host):
        super().__init__(host)
        self.dir_sizes = {}

        outer = QVBoxLayout(self)
        # No top margin: the page title hugs the top of the content area.
        outer.setContentsMargins(
            tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN
        )
        outer.setSpacing(tokens.PAGE_SPACING)
        outer.addWidget(label(t("Disk Analyzer"), role="display"))

        row = QHBoxLayout()
        row.addWidget(label(t("Drive:")))
        # A drive picker rather than a free folder field: the analyzer maps whole
        # volumes, and drill-down into subfolders happens on the treemap itself.
        self.drive = QComboBox()
        self.drive.addItems(list_drives())
        row.addWidget(self.drive, 1)
        scan = PrimaryButton(t("Scan"))
        scan.clicked.connect(self.on_scan)
        row.addWidget(scan)
        outer.addLayout(row)
        self.action_buttons = [scan]

        tabs = QTabWidget()
        # Treemap
        tm_wrap = QWidget()
        tm_col = QVBoxLayout(tm_wrap)
        tm_bar = QHBoxLayout()
        self.tm_up = GhostButton(t("↑ Up"))
        self.tm_up.clicked.connect(lambda: self.treemap.go_up())
        self.tm_label = label(t("Scan a folder to see its treemap."), role="muted")
        tm_bar.addWidget(self.tm_up)
        tm_bar.addWidget(self.tm_label, 1)
        tm_col.addLayout(tm_bar)
        self.treemap = TreemapView()
        self.treemap.navigated.connect(self._on_tm_nav)
        tm_col.addWidget(self.treemap, 1)
        tabs.addTab(tm_wrap, t("Treemap"))

        # Folder tree
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([t("Folder / file"), t("Size"), t("% of parent")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemExpanded.connect(self._on_expand)
        self.tree.itemDoubleClicked.connect(
            lambda it, _c: _open_path(it.data(0, Qt.UserRole))
        )
        tabs.addTab(self.tree, t("Folder tree"))

        outer.addWidget(tabs, 1)
        self.status = label(
            t("Scan a drive to map every folder and file."), role="muted"
        )
        outer.addWidget(self.status)

    def on_scan(self):
        path = self.drive.currentText()
        if not os.path.isdir(path):
            chrome.notify(
                self, t("Invalid folder"), t("Not a folder:\n{path}").format(path=path)
            )
            return
        self.host.log(t("Scanning {p}…").format(p=path))

        def make(progress):
            return lambda: analyzer.build_size_map(
                path,
                on_progress=progress,
                should_cancel=self.host.cancel_event.is_set,
                excluded=settings.load().get("excluded_dirs", []),
            )

        def on_count(n):
            self.host.set_busy_text(t("Scanned {n} files…").format(n=f"{n:,}"))

        def on_result(result):
            self._populate(os.path.abspath(path), result)

        self._run(make, on_result=on_result, on_progress=on_count)

    def _populate(self, base, result):
        self.dir_sizes = result.dir_sizes
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, [base, human(result.total), "100%"])
        root.setData(0, Qt.UserRole, base)
        self._fill_node(root, base)
        root.setExpanded(True)
        self.treemap.set_scan(base, result.dir_sizes)
        self.status.setText(
            t("Scanned {n} files · {sz} total.").format(
                n=f"{result.scanned:,}", sz=human(result.total)
            )
        )
        self.host.log(
            t("Scanned {n} files · {sz} total.").format(
                n=f"{result.scanned:,}", sz=human(result.total)
            )
        )

    def _fill_node(self, item, path):
        parent = self.dir_sizes.get(path, 0) or 1
        for size, p, is_dir, name in _dir_children(path, self.dir_sizes)[
            : config.TREE_CHILD_CAP
        ]:
            pct = size / parent * 100 if parent else 0
            child = QTreeWidgetItem(item, [name or p, human(size), f"{pct:.0f}%"])
            child.setData(0, Qt.UserRole, p)
            if is_dir and size > 0:
                # Placeholder so the expand arrow shows; replaced on expand.
                QTreeWidgetItem(child, ["…", "", ""])

    def _on_expand(self, item):
        path = item.data(0, Qt.UserRole)
        if not path or not os.path.isdir(path):
            return
        children = item.takeChildren()
        # Only (re)populate if it still holds the placeholder.
        if len(children) == 1 and children[0].text(0) == "…":
            self._fill_node(item, path)
        else:
            for c in children:
                item.addChild(c)

    def _on_tm_nav(self, path):
        self.tm_up.setEnabled(path != self.treemap._root)
        self.tm_label.setText(f"{path}  —  {human(self.dir_sizes.get(path, 0))}")


# ----------------------------------------------------------------------------- #
#  Duplicates
# ----------------------------------------------------------------------------- #
class DuplicatesPage(PageBase):
    def __init__(self, host):
        super().__init__(host)
        outer = QVBoxLayout(self)
        # No top margin: the page title hugs the top of the content area.
        outer.setContentsMargins(
            tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN
        )
        outer.setSpacing(tokens.PAGE_SPACING)
        outer.addWidget(label(t("Duplicates"), role="display"))

        row = QHBoxLayout()
        row.addWidget(label(t("Folder:")))
        self.path = QLineEdit(_default_path())
        row.addWidget(self.path, 1)
        browse = GhostButton(t("Browse"))
        browse.clicked.connect(lambda: _browse_into(self, self.path))
        row.addWidget(browse)
        row.addWidget(label(t("Min size")))
        self.min_mb = QSpinBox()
        self.min_mb.setRange(1, 100000)
        self.min_mb.setValue(config.DUP_MIN_SIZE // (1024 * 1024))
        self.min_mb.setButtonSymbols(QSpinBox.NoButtons)  # no up/down arrows
        self.min_mb.setFixedWidth(72)  # fits up to "100000"
        self.min_mb.setAlignment(Qt.AlignCenter)  # centred in LTR + RTL
        row.addWidget(self.min_mb)
        row.addWidget(label(t("MB")))
        find = PrimaryButton(t("Find duplicates"))
        find.clicked.connect(self.on_find)
        row.addWidget(find)
        outer.addLayout(row)
        self.action_buttons = [find]

        # Post-scan filters over the found groups (no re-scan): a name/path search
        # and an extension picker populated from the results.
        self._groups = []
        frow = QHBoxLayout()
        frow.addWidget(label(t("Filter:")))
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText(t("Filter by name or path…"))
        self.filter_text.setClearButtonEnabled(True)
        self.filter_text.textChanged.connect(self._apply_filter)
        frow.addWidget(self.filter_text, 1)
        self.type_box = QComboBox()
        self.type_box.addItem(t("All types"))
        self.type_box.currentIndexChanged.connect(self._apply_filter)
        frow.addWidget(self.type_box)
        outer.addLayout(frow)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([t("Group / file"), t("Size")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        # Copies are picked via the per-file tick box (like the old-files table),
        # so no row-selection highlight and no keyboard-focus ring.
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.setFocusPolicy(Qt.NoFocus)
        self.area = ResultArea(
            self.tree, t("Scan a folder to find duplicate files."), "fa5s.clone"
        )
        outer.addWidget(self.area, 1)

        bar = QHBoxLayout()
        keep = GhostButton(t("Select all but one per group"))
        keep.clicked.connect(self._select_redundant)
        clear = GhostButton(t("Clear selection"))
        clear.clicked.connect(lambda: self._set_all_checks(False))
        move = DangerButton(t("Move selected to Recycle Bin"))
        move.clicked.connect(self.on_delete)
        bar.addWidget(keep)
        bar.addWidget(clear)
        bar.addStretch(1)
        bar.addWidget(move)
        outer.addLayout(bar)

        self.status = label(
            t(
                "Finds byte-identical copies. Keeps one, sends the rest to the "
                "Recycle Bin (undoable)."
            ),
            role="muted",
        )
        outer.addWidget(self.status)

    def on_find(self):
        folder = self.path.text()
        if not os.path.isdir(folder):
            chrome.notify(
                self,
                t("Invalid folder"),
                t("Not a folder:\n{path}").format(path=folder),
            )
            return
        min_size = self.min_mb.value() * 1024 * 1024
        self.host.log(t("Scanning for duplicates…"))

        def make(progress):
            return lambda: analyzer.find_duplicates(
                folder,
                min_size,
                on_progress=progress,
                should_cancel=self.host.cancel_event.is_set,
                excluded=settings.load().get("excluded_dirs", []),
            )

        def on_count(n):
            self.host.set_busy_text(
                t("Hashing… {n} candidate files").format(n=f"{n:,}")
            )

        self._run(make, on_result=self._set_results, on_progress=on_count)

    def _set_results(self, groups):
        """Store a fresh result set, reset the filters, and repopulate the type
        picker from the extensions actually present."""
        self._groups = groups
        exts = sorted(
            {
                os.path.splitext(p)[1].lower() or "(no ext)"
                for g in groups
                for p in g.paths
            }
        )
        self.type_box.blockSignals(True)
        self.type_box.clear()
        self.type_box.addItem(t("All types"))
        self.type_box.addItems(exts)
        self.type_box.setCurrentIndex(0)
        self.type_box.blockSignals(False)
        self.filter_text.blockSignals(True)
        self.filter_text.clear()
        self.filter_text.blockSignals(False)
        self.host.log(
            t("{n} duplicate groups · {sz} reclaimable.").format(
                n=f"{len(groups):,}",
                sz=human(sum(g.size * (len(g.paths) - 1) for g in groups)),
            )
        )
        self._render(groups)

    def _filtered(self):
        """The stored groups narrowed by the search text and the type picker. A
        group matches if any of its copies match (so all copies stay visible to
        choose from)."""
        text = self.filter_text.text().strip().lower()
        type_all = self.type_box.currentIndex() == 0
        chosen = self.type_box.currentText()
        out = []
        for g in self._groups:
            if text and not any(text in p.lower() for p in g.paths):
                continue
            if not type_all and not any(
                (os.path.splitext(p)[1].lower() or "(no ext)") == chosen
                for p in g.paths
            ):
                continue
            out.append(g)
        return out

    def _apply_filter(self, *_):
        self._render(self._filtered())

    def _render(self, groups):
        self.tree.clear()
        wasted = sum(g.size * (len(g.paths) - 1) for g in groups)
        for g in groups:
            reclaim = g.size * (len(g.paths) - 1)
            head = QTreeWidgetItem(
                self.tree,
                [
                    t("{n} copies · {sz} reclaimable").format(
                        n=len(g.paths), sz=human(reclaim)
                    ),
                    human(g.size),
                ],
            )
            for p in g.paths:
                child = QTreeWidgetItem(head, [os.path.basename(p), human(g.size)])
                child.setData(0, Qt.UserRole, p)
                child.setToolTip(0, p)  # full path on hover
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)  # pick copies to remove
            head.setExpanded(True)  # show the copies + boxes
        total = len(self._groups)
        if not groups:
            self.area.set_empty(
                True,
                (
                    t("No duplicates found.")
                    if not total
                    else t("No duplicates match the filter.")
                ),
            )
        else:
            self.area.set_empty(False)
        if total and len(groups) != total:
            self.status.setText(
                t("Showing {shown} of {total} groups · {sz} reclaimable.").format(
                    shown=len(groups), total=total, sz=human(wasted)
                )
            )
        else:
            self.status.setText(
                t("{n} duplicate groups · {sz} reclaimable.").format(
                    n=f"{len(groups):,}", sz=human(wasted)
                )
            )

    def _select_redundant(self):
        """Tick every copy except the first in each group (keep one)."""
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                head.child(j).setCheckState(0, Qt.Checked if j > 0 else Qt.Unchecked)

    def _set_all_checks(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                head.child(j).setCheckState(0, state)

    def _selected_paths(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                child = head.child(j)
                if child.checkState(0) == Qt.Checked:
                    p = child.data(0, Qt.UserRole)
                    if p:
                        out.append(p)
        return out

    def on_delete(self):
        paths = self._selected_paths()
        if not paths:
            chrome.notify(
                self,
                t("Nothing selected"),
                t("Select the duplicate files to remove first."),
            )
            return
        if not self._ask(
            "Move to Recycle Bin",
            t(
                "Move {n} duplicate file(s) to the Recycle Bin?\n\n"
                "They stay recoverable there until you empty it."
            ).format(n=len(paths)),
        ):
            return

        # Log each path + whether it resolves on disk, so a "freed 0 B" result
        # can be diagnosed straight from the activity log.
        missing = sum(1 for p in paths if not os.path.exists(p))
        self.host.log(f"Recycling {len(paths)} file(s); {missing} not found on disk.")
        for p in paths[:12]:
            self.host.log(f"  {'ok' if os.path.exists(p) else 'MISSING'}: {p!r}")

        def make(progress):
            return lambda: winapi.send_to_recycle_bin(paths)

        def done(freed):
            if freed:
                self.host.toast(
                    t("Moved {n} duplicates to Recycle Bin · freed {sz}.").format(
                        n=len(paths), sz=human(freed)
                    )
                )
            else:
                self.host.toast(
                    t(
                        "Nothing removed — the selected files weren't found "
                        "(in use, protected, or already gone)."
                    )
                )

        # Re-scan via `then` (after the busy state clears) so the removed copies
        # drop off — from on_result it would hit _run's busy guard and do nothing.
        self._run(make, on_result=done, then=self.on_find)


# ----------------------------------------------------------------------------- #
#  Claim old files
# ----------------------------------------------------------------------------- #
class OldFilesPage(PageBase):
    def __init__(self, host):
        super().__init__(host)
        outer = QVBoxLayout(self)
        # No top margin: the page title hugs the top of the content area.
        outer.setContentsMargins(
            tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN
        )
        outer.setSpacing(tokens.PAGE_SPACING)
        outer.addWidget(label(t("Claim old files"), role="display"))

        row = QHBoxLayout()
        row.addWidget(label(t("Folder:")))
        self.path = QLineEdit(locations.downloads_dir())
        row.addWidget(self.path, 1)
        browse = GhostButton(t("Browse"))
        browse.clicked.connect(lambda: _browse_into(self, self.path))
        row.addWidget(browse)
        row.addWidget(label(t("Older than")))
        self.months = QSpinBox()
        self.months.setRange(1, 99)
        self.months.setValue(config.DEFAULT_OLD_MONTHS)
        self.months.setButtonSymbols(QSpinBox.NoButtons)  # no up/down arrows
        self.months.setFixedWidth(48)  # just wide enough for "99"
        self.months.setAlignment(Qt.AlignCenter)
        row.addWidget(self.months)
        row.addWidget(label(t("months")))
        find = PrimaryButton(t("Find old files"))
        find.clicked.connect(self.on_find)
        row.addWidget(find)
        outer.addLayout(row)
        self.action_buttons = [find]

        # A leading tick-box column selects files; the rest sort on header click
        # (Size/Age numerically via _SortItem, File by name). The full path lives
        # in the File cell's UserRole — open/move/delete use it though only the
        # name shows. Selection is by checkbox, so row selection is off and the
        # only hover feedback is the full-path tooltip (no row highlight).
        self.table = _table(["", t("Size"), t("Age"), t("File")], 3)
        self.table.setColumnWidth(0, 34)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        # Mouse/checkbox-driven, so refuse keyboard focus — that stops the style
        # drawing the blue focus rectangle around whatever cell was last clicked.
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setSortingEnabled(True)
        self.table.itemDoubleClicked.connect(
            lambda it: _open_path(self.table.item(it.row(), 3).data(Qt.UserRole))
        )
        self.area = ResultArea(
            self.table, t("Find files you haven't used in a while."), "fa5s.clock"
        )
        outer.addWidget(self.area, 1)

        bar = QHBoxLayout()
        sel_all = GhostButton(t("Select all"))
        sel_all.clicked.connect(lambda: self._set_all_checks(True))
        clear = GhostButton(t("Clear selection"))
        clear.clicked.connect(lambda: self._set_all_checks(False))
        move = GhostButton(t("Move selected to another drive…"))
        move.clicked.connect(self.on_move)
        recycle = DangerButton(t("Move selected to Recycle Bin"))
        recycle.clicked.connect(self.on_delete)
        bar.addWidget(sel_all)
        bar.addWidget(clear)
        bar.addStretch(1)
        bar.addWidget(move)
        bar.addWidget(recycle)
        outer.addLayout(bar)

        self.status = label(
            t(
                "Lists files you haven't touched in a while. Relocate big files to "
                "another drive, or send them to the Recycle Bin (undoable)."
            ),
            role="muted",
        )
        outer.addWidget(self.status)

    def on_find(self):
        folder = self.path.text()
        if not os.path.isdir(folder):
            chrome.notify(
                self,
                t("Invalid folder"),
                t("Not a folder:\n{path}").format(path=folder),
            )
            return
        months = self.months.value()
        days = months * config.DAYS_PER_MONTH  # the finder works in days
        self.host.log(t("Finding old files…"))

        def make(progress):
            return lambda: find_old_files(
                folder,
                days,
                should_cancel=self.host.cancel_event.is_set,
                excluded=settings.load().get("excluded_dirs", []),
            )

        def done(results):
            now = time.time()
            # Sorting off during the bulk fill, else each insert re-sorts and the
            # row indices shift under us; re-enabled after — which re-applies the
            # header's current sort indicator, so the user's chosen column/order
            # is preserved across a refresh (e.g. after a move/delete re-scan).
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
            total = 0
            for sz, fp, mtime in results:
                total += sz
                self._add_old_row(sz, now - mtime, fp)
            self.table.setSortingEnabled(True)
            self.area.set_empty(not results, t("No files found."))
            self.status.setText(
                t("{n} files older than {m} months · {sz} total.").format(
                    n=f"{len(results):,}", m=months, sz=human(total)
                )
            )

        self._run(make, on_result=done)

    def _add_old_row(self, size, age_seconds, path):
        """One row: a tick box (col 0) to select the file, Size/Age sorting by
        their numeric value (bytes/seconds), and the File name. The full path is
        the File cell's UserRole (used by open/move/delete) and the tooltip on
        every cell, so hovering anywhere on the row reveals it."""
        r = self.table.rowCount()
        self.table.insertRow(r)
        check = QTableWidgetItem()
        check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        check.setCheckState(Qt.Unchecked)
        check.setTextAlignment(Qt.AlignCenter)
        size_item = _SortItem(human(size), size)
        age_item = _SortItem(months_old(age_seconds), age_seconds)
        name = QTableWidgetItem(os.path.basename(path))
        name.setData(Qt.UserRole, path)
        for it in (check, size_item, age_item, name):
            it.setToolTip(path)
        self.table.setItem(r, 0, check)
        self.table.setItem(r, 1, size_item)
        self.table.setItem(r, 2, age_item)
        self.table.setItem(r, 3, name)

    def _set_all_checks(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(state)

    def _selected_paths(self):
        return [
            self.table.item(r, 3).data(Qt.UserRole)
            for r in range(self.table.rowCount())
            if self.table.item(r, 0).checkState() == Qt.Checked
        ]

    def on_delete(self):
        paths = self._selected_paths()
        if not paths:
            chrome.notify(self, t("Nothing selected"), t("Select files first."))
            return
        if not self._ask(
            "Move to Recycle Bin",
            t(
                "Move {n} file(s) to the Recycle Bin?\n\n"
                "They stay recoverable there until you empty it."
            ).format(n=len(paths)),
        ):
            return

        def make(progress):
            return lambda: winapi.send_to_recycle_bin(paths)

        def done(freed):
            self.host.toast(
                t("Moved {n} files to Recycle Bin · freed {sz}.").format(
                    n=len(paths), sz=human(freed)
                )
            )

        # Re-scan via `then` (fires after the busy state clears) so the moved
        # files drop off the list — calling on_find from on_result would hit the
        # busy guard and silently do nothing. The re-scan keeps the sort order.
        self._run(make, on_result=done, then=self.on_find)

    def on_move(self):
        paths = self._selected_paths()
        _move_selected(self, paths, base=self.path.text(), after=self.on_find)


# ----------------------------------------------------------------------------- #
#  Shared helpers
# ----------------------------------------------------------------------------- #
def _default_path():
    return config.SYSTEM_DRIVE if config.IS_WINDOWS else os.path.expanduser("~")


def _dir_children(path, dir_sizes):
    """[(size, child_path, is_dir, name), ...] for a folder, biggest first, using
    cached scan sizes for subfolders. Shared by the folder tree and the treemap
    so the two views can't disagree; unreadable entries are skipped."""
    items = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        size, is_dir = dir_sizes.get(e.path, 0), True
                    else:
                        size, is_dir = e.stat(follow_symlinks=False).st_size, False
                except OSError:
                    continue
                items.append((size, e.path, is_dir, e.name))
    except OSError:
        return []
    items.sort(key=lambda x: x[0], reverse=True)
    return items


def _browse_into(widget, line_edit):
    chosen = QFileDialog.getExistingDirectory(
        widget, t("Browse"), line_edit.text() or "/"
    )
    if chosen:
        line_edit.setText(chosen)


def _open_path(path):
    if not path:
        return
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    try:
        if config.IS_WINDOWS:
            os.startfile(folder)  # noqa
    except Exception:
        pass


def _move_selected(page, paths, base, after=None):
    """Move-to-another-drive flow for the Claim-old-files table: confirm a
    destination, warn on same-drive, move off-thread, then toast the result and
    call `after` (e.g. to refresh the list). Kept as a module function (not a
    method) so the toast + optional refresh live in one place, away from the
    page's widget wiring."""
    if not paths:
        chrome.notify(page, t("Nothing selected"), t("Select files first."))
        return
    dest = QFileDialog.getExistingDirectory(
        page, t("Choose a destination folder (ideally on another drive)"), "/"
    )
    if not dest or not os.path.isdir(dest):
        return
    src_drive = os.path.splitdrive(os.path.abspath(paths[0]))[0].upper()
    dst_drive = os.path.splitdrive(os.path.abspath(dest))[0].upper()
    if src_drive == dst_drive and not page._ask(
        "Same drive",
        t(
            "The destination is on the same drive ({drive}).\n"
            "Moving here won't free space on that drive.\n\nMove anyway?"
        ).format(drive=dst_drive or "same volume"),
    ):
        return
    if not page._ask(
        "Move files",
        t(
            "Move {n} file(s) to:\n{dest}\n\nEach file is copied, then "
            "removed from its current location. Anything in use is "
            "skipped (and left where it is)."
        ).format(n=len(paths), dest=dest),
    ):
        return

    def make(progress):
        return lambda: move_files(paths, dest, base_dir=base, log=page.host.log)

    def done(res):
        moved, freed = res
        page.host.toast(
            t(
                "Moved {n} of {total} files to {dest} · "
                "freed {sz} on the source drive."
            ).format(n=moved, total=len(paths), dest=dest, sz=human(freed))
        )

    # `after` (e.g. re-scan) runs via `then`, after the busy state clears — from
    # on_result it would hit _run's busy guard and never fire.
    page._run(make, on_result=done, then=after)
