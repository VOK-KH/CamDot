"""Main window: Download and Grabber tabs, menus, and job controls."""
import os
import sys
import threading

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QPoint,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QKeySequence,
    QMouseEvent,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from app.core import icons, store, sysinfo, theme
from app.core.collect import cookies_from_browser_value, write_entries_csv
from app.core.cookies import write_netscape_cookies
from app.core.download import (
    ALL_MEDIA_KINDS, DEFAULT_FRAGMENTS, DEFAULT_WORKERS, OUTPUT_TEMPLATE,
    read_urls, resolve_filename_template, source_folder_name, tiktok_dateafter,
)
from app.gui.constants import (
    COLUMN_WIDTHS,
    EDGE_CURSORS,
    FIXED_COLUMNS,
    FLOAT_MARGIN,
    FRAME_MARGIN,
    GRABBER_HIDDEN,
    HIDDEN_BY_DEFAULT,
    PINNED_COLUMNS,
    STATS_INTERVAL_MS,
    TAB_DOWNLOAD,
    TAB_GRABBER,
)
from app.gui.dialogs.alert import alert
from app.gui.dialogs.links import AddLinksDialog
from app.gui.dialogs.platforms import PlatformsDialog
from app.gui.widgets.grabber import GrabberPanel
from app.gui.widgets.tray import TrayController
from app.gui.widgets.loader import ExtractLoader
from app.gui.widgets.views import ViewsPanel
from app.gui.dialogs.settings import SettingsDialog
from app.gui.helpers import derive_channel, remember_recent
from app.gui.jobs import JobWorker
from app.gui.widgets.header import CheckHeaderView
from app.gui.widgets.overview import OverviewPanel
from app.gui.widgets.properties import PropertiesPanel
from app.gui.widgets.progress import ProgressDelegate
from app.core.model import (
    COL_CHECK,
    COL_FILE,
    COL_HOST,
    COL_ID,
    COL_INDEX,
    COL_PROGRESS,
    COL_TITLE,
    COLUMNS,
    STATUS_LABELS,
    STATUSES,
    ReelFilterProxy,
    ReelModel,
    format_eta,
)
from app.core.runtime import (
    collect_csv_path,
    resolve_output_root,
    runtime_versions,
    schedule_auto_update,
    state_dir,
    sweep_download_folder,
    update_runtime,
)
from app.core.urls import (
    clean_url,
    extract_supported_urls,
    looks_shell_truncated,
    normalize_source_url,
    youtube_watch_with_list,
)


class MainWindow(QMainWindow):
    tools_checked = Signal(str)
    gpu_detected = Signal(str, str)

    def __init__(self, dark=theme.DEFAULT_DARK, settings=None):
        super().__init__()
        self.tools_checked.connect(self._append_log)
        self.gpu_detected.connect(self._on_gpu_detected)
        self.setWindowTitle("Reels Downloader")
        self.resize(1180, 680)
        # No native title bar: the menu strip carries the window controls, and
        # the outermost FRAME_MARGIN pixels resize the window (see _frame_event).
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMouseTracking(True)
        self._drag_origin = None
        self._frame_cursor = None
        self._thread = None
        self._worker = None
        self._collecting = False
        self._grabber_job = False
        self._restoring_list = False
        self._grab_current = ""
        self._grab_queue = []
        self._grab_added = 0
        self._grab_dupes = 0
        self._grab_aborted = False
        self._grab_manual = False
        self._dark = dark
        self._settings = settings or QSettings("facebook-reels-downloader", "gui")
        self._columns_locked = self._settings.value("columns_locked", False, bool)
        self._h_scrollbar = False
        self.grab_add_at_top = False
        self.grab_auto_confirm = False
        self.grab_autostart = False
        self._pending_auto_confirm = False
        self._quitting = False

        self.model = ReelModel(self)
        self.proxy = ReelFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.grab_model = ReelModel(self)
        self.grab_proxy = ReelFilterProxy(self)
        self.grab_proxy.setSourceModel(self.grab_model)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._build_source_field()
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("mainSplit")
        self.splitter.setHandleWidth(6)
        self.splitter.addWidget(self._build_pages())
        self.splitter.addWidget(self._build_log())
        self.splitter.addWidget(self._build_overview())
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)
        self.splitter.setCollapsible(2, True)
        self.splitter.setStretchFactor(0, 8)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([520, 90, 72])
        self.splitter.splitterMoved.connect(self._clamp_overview_size)
        outer.addWidget(self._build_toolbar())
        outer.addWidget(self.splitter, 1)
        outer.addWidget(self._build_properties())
        outer.addWidget(self._build_action_bar())
        self._on_page_changed(self.tabs.currentIndex())
        self._build_status_bar()
        self._build_menus()

        self._store_timer = QTimer(self)
        self._store_timer.setSingleShot(True)
        self._store_timer.setInterval(400)
        self._store_timer.timeout.connect(self._flush_store)
        self._cpu_meter = sysinfo.CpuMeter()
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(STATS_INTERVAL_MS)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._restore_settings()
        try:
            sweep_download_folder(self._output_root())
        except OSError:
            pass
        self._apply_theme()
        self._set_busy(False)
        self._update_counter()
        self._start_stats()
        if self.source_edit.text().strip():
            self._load_saved_list(self._channel())
        self.grab_panel = GrabberPanel(self)
        self.grab_panel.aborted.connect(self._cancel_grabber)
        geo = self._settings.value("grab_monitor")
        if geo:
            self.grab_panel.restoreGeometry(geo)
            self.grab_panel.user_placed = True
        self._grab_close_timer = QTimer(self)
        self._grab_close_timer.setSingleShot(True)
        self._grab_close_timer.setInterval(2500)
        self._grab_close_timer.timeout.connect(self._hide_grab_panel)
        QGuiApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        self.tray = TrayController(self)
        self._sync_close_tooltip()
        # The panels reach the window edge, so the resize band has to see the
        # presses they would otherwise swallow.
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ---------------------------------------------------------------- layout

    def _build_pages(self):
        """Download is the queue; Grabber extracts URLs into its own table first."""
        self.tabs = QTabWidget()
        self.tabs.setObjectName("workTabs")
        self.tabs.addTab(self._build_download_page(), "Download")
        self.tabs.addTab(self._build_grabber_page(), "Grabber")
        self.tabs.currentChanged.connect(self._on_page_changed)
        self.views = ViewsPanel(self)
        self.views.filter_changed.connect(self._apply_views_filter)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("workSplit")
        split.addWidget(self.tabs)
        split.addWidget(self.views)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)
        split.setSizes([940, 200])
        self.work_split = split
        return split

    def _build_download_page(self):
        page = QWidget()
        page.setObjectName("downloadPage")
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 4, 0, 0)
        col.setSpacing(6)
        self.table = self._make_table(self.proxy, HIDDEN_BY_DEFAULT)
        col.addWidget(self.table, 1)
        return page

    def _build_source_field(self):
        """URL recents live off the Grabber table; Add links / Extract still use them."""
        self.source_combo = QComboBox(self)
        self.source_combo.setEditable(True)
        self.source_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.source_combo.setMaxVisibleItems(12)
        self.source_combo.hide()
        self.source_edit = self.source_combo.lineEdit()
        self.source_edit.setClearButtonEnabled(True)
        self.source_edit.setPlaceholderText("Paste a post, channel, or playlist URL")
        self.collect_btn = self._pill("Extract", "collect", "blue", self._start_collect)
        self.collect_btn.setToolTip("Analyze this URL into the Grabber table")
        self.collect_btn.hide()

    def _build_grabber_page(self):
        page = QWidget()
        page.setObjectName("grabberPage")
        self.grab_page = page
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 4, 0, 0)
        col.setSpacing(6)
        self.grab_table = self._make_table(self.grab_proxy, GRABBER_HIDDEN)
        col.addWidget(self.grab_table, 1)
        self.extract_loader = ExtractLoader(page)
        self.extract_loader.aborted.connect(self._cancel)
        return page

    def _build_toolbar(self):
        """Icon strip under the menu, JDownloader-style job and list actions."""
        bar = QWidget()
        bar.setObjectName("toolBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.start_btn = self._tool_button(
            "play", "Start download (Ctrl+D)", self._toolbar_start)
        self.stop_btn = self._tool_button(
            "stop", "Cancel the current job (Esc)", self._cancel)
        self.up_btn = self._tool_button(
            "move-up", "Move selected rows up", lambda: self._move_selected(-1))
        self.down_btn = self._tool_button(
            "move-down", "Move selected rows down", lambda: self._move_selected(1))
        self.clip_btn = self._tool_button(
            "link", "Watch the clipboard for links (Ctrl+G)",
            self._toggle_grabber, checkable=True)
        self.add_links_btn = self._tool_button(
            "collect", "Paste links and extract into Grabber (F5)", self._add_links)
        self.add_list_btn = self._tool_button(
            "download", "Add Grabber rows to Download (Ctrl+Shift+D)",
            self._add_to_downloads)
        self.remove_btn = self._tool_button(
            "clear", "Remove selected rows (Delete)", self._remove_selected)
        self.settings_tool_btn = self._tool_button(
            "settings", "Settings (Ctrl+,)", self._open_settings)
        self.sites_btn = self._tool_button(
            "globe", "Supported platforms", self._show_supported_sites)

        for widget in (
            self.start_btn, self.stop_btn, self._tool_sep(),
            self.up_btn, self.down_btn, self._tool_sep(),
            self.clip_btn, self.add_links_btn, self.add_list_btn, self._tool_sep(),
            self.remove_btn, self._tool_sep(),
            self.settings_tool_btn, self.sites_btn,
        ):
            row.addWidget(widget)
        row.addStretch(1)
        return bar

    def _tool_sep(self):
        line = QFrame()
        line.setObjectName("toolSep")
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _on_page_changed(self, index):
        """The bottom bar follows the tab: Download vs Add to downloads."""
        on_list = index == TAB_DOWNLOAD
        self.download_btn.setVisible(on_list)
        self.add_btn.setVisible(not on_list)
        self._sync_header_check()
        self._update_counter()
        self._refresh_overview()
        self._refresh_views()
        self._fill_properties()
        self._place_extract_loader()

    def _build_window_controls(self):
        """Minimise, maximise and close, standing in for the native buttons."""
        bar = QWidget()
        bar.setObjectName("winControls")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.min_btn = self._icon_button("win-minimize", "Minimise", self.showMinimized)
        self.max_btn = self._icon_button("win-maximize", "Maximise", self._toggle_maximized)
        self.close_btn = self._icon_button("win-close", "Quit", self.close)
        for button in (self.min_btn, self.max_btn, self.close_btn):
            button.setObjectName("winBtn")
            row.addWidget(button)
        self.close_btn.setObjectName("winClose")
        return bar

    def _toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _sync_window_controls(self):
        """The middle button shows where it takes you, not where you are."""
        restore = self.isMaximized()
        self.max_btn.setProperty("iconName", "win-restore" if restore else "win-maximize")
        self.max_btn.setIcon(
            icons.icon(self.max_btn.property("iconName"), self._icon_color())
        )
        self.max_btn.setToolTip("Restore" if restore else "Maximise")

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange:
            return
        if hasattr(self, "max_btn"):
            self._sync_window_controls()
        if (
            self._close_to_tray_enabled()
            and not self._quitting
            and self.windowState() & Qt.WindowState.WindowMinimized
        ):
            QTimer.singleShot(0, self.hide)

    # ----------------------------------------------------------- frameless

    def _resize_edges(self, pos):
        """Which window edges `pos` grabs, if any."""
        if self.isMaximized():
            return Qt.Edge(0)
        edges = Qt.Edge(0)
        if pos.x() < FRAME_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - FRAME_MARGIN:
            edges |= Qt.Edge.RightEdge
        if pos.y() < FRAME_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - FRAME_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _frame_edges_for(self, watched, event):
        """Edges a mouse event grabs, or Qt.Edge(0) when it belongs to the content.

        The panels reach the window edge, so those presses land on them; this
        band stands in for the border the system would otherwise draw.
        """
        if not isinstance(event, QMouseEvent) or not isinstance(watched, QWidget):
            return Qt.Edge(0)
        if watched.window() is not self:       # dialogs keep their own edges
            return Qt.Edge(0)
        return self._resize_edges(self.mapFromGlobal(event.globalPosition().toPoint()))

    def _set_frame_cursor(self, shape):
        """Show the resize cursor over the band without touching child cursors."""
        if shape == self._frame_cursor:
            return
        if self._frame_cursor is not None:
            QGuiApplication.restoreOverrideCursor()
        if shape is not None:
            QGuiApplication.setOverrideCursor(shape)
        self._frame_cursor = shape

    def _frame_event(self, watched, event):
        """True when the event was spent on resizing the window."""
        kind = event.type()
        if kind == QEvent.Type.WindowDeactivate:
            self._set_frame_cursor(None)
            return False
        if kind not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            return False
        edges = self._frame_edges_for(watched, event)
        if kind == QEvent.Type.MouseMove:
            # Hovering belongs to the child; only the cursor is ours.
            self._set_frame_cursor(None if event.buttons() else EDGE_CURSORS.get(edges))
            return False
        if not edges or event.button() != Qt.MouseButton.LeftButton:
            return False
        self._set_frame_cursor(None)
        self.windowHandle().startSystemResize(edges)
        return True

    def eventFilter(self, watched, event):
        """Resize from the window's outer pixels; drag it by the menu strip."""
        if self._frame_event(watched, event):
            return True
        if watched is not self.menu_bar or not self._on_menu_gap(event):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self._toggle_maximized()
            return True
        if event.type() == QEvent.Type.MouseButtonPress:
            # Wait for real movement, so a double-click still registers.
            self._drag_origin = event.globalPosition().toPoint()
            return True
        if event.type() == QEvent.Type.MouseMove and self._drag_origin is not None:
            moved = event.globalPosition().toPoint() - self._drag_origin
            if moved.manhattanLength() > 6:
                self._drag_origin = None
                self.windowHandle().startSystemMove()
            return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._drag_origin = None
        return super().eventFilter(watched, event)

    def _on_menu_gap(self, event):
        """True for mouse events on the strip itself rather than on a menu title."""
        if not isinstance(event, QMouseEvent):
            return False
        return self.menu_bar.actionAt(event.position().toPoint()) is None

    def _pack(self):
        """The list the current tab is editing: download queue or Grabber."""
        grabber = (
            getattr(self, "tabs", None) is not None
            and self.tabs.currentIndex() == TAB_GRABBER
            and getattr(self, "grab_table", None) is not None
        )
        if grabber:
            return self.grab_model, self.grab_proxy, self.grab_table
        return self.model, self.proxy, getattr(self, "table", None)

    def _sync_header_check(self, *args):
        # Defer until the model has finished resetting; querying it from a
        # reset/layout slot can stall the Qt event loop.
        if getattr(self, "_header_sync_queued", False):
            return
        self._header_sync_queued = True
        QTimer.singleShot(0, self._flush_header_check)

    def _flush_header_check(self):
        self._header_sync_queued = False
        model, _proxy, table = self._pack()
        if table is None:
            return
        header = table.horizontalHeader()
        if isinstance(header, CheckHeaderView):
            header.set_check_state(model.check_state_for_rows(self._visible_source_rows()))

    def _make_table(self, proxy, hidden):
        table = QTableView()
        table.setModel(proxy)
        table.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(table))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setShowGrid(True)
        table.setDragEnabled(False)
        table.setAcceptDrops(False)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        table.doubleClicked.connect(self._open_reel)
        proxy.dataChanged.connect(self._sync_header_check)
        proxy.modelReset.connect(self._sync_header_check)
        proxy.layoutChanged.connect(self._sync_header_check)

        vertical = table.verticalHeader()
        vertical.setVisible(False)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultSectionSize(24)

        header = CheckHeaderView(table)
        table.setHorizontalHeader(header)
        header.setModel(proxy)
        header.check_clicked.connect(self._toggle_visible_checks)
        header.setStretchLastSection(False)
        header.setFirstSectionMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        table.selectionModel().selectionChanged.connect(self._fill_properties)
        table.setSortingEnabled(True)
        table.sortByColumn(COL_INDEX, Qt.SortOrder.AscendingOrder)
        self._reset_columns(table, hidden)
        return table

    # -------------------------------------------------------------- columns

    def _hidden_columns(self, table):
        return GRABBER_HIDDEN if table is getattr(self, "grab_table", None) else HIDDEN_BY_DEFAULT

    def _apply_column_modes(self, table=None):
        """Widths follow the lock: pinned columns are always fixed, Title stretches."""
        targets = [table] if table is not None else [
            item for item in (getattr(self, "table", None), getattr(self, "grab_table", None))
            if item is not None
        ]
        for view in targets:
            header = view.horizontalHeader()
            header.setSectionsMovable(not self._columns_locked)
            for column in range(len(COLUMNS)):
                if column == COL_TITLE:
                    mode = QHeaderView.ResizeMode.Stretch
                elif column in FIXED_COLUMNS or self._columns_locked:
                    mode = QHeaderView.ResizeMode.Fixed
                else:
                    mode = QHeaderView.ResizeMode.Interactive
                header.setSectionResizeMode(column, mode)

    def _set_columns_locked(self, locked):
        self._columns_locked = bool(locked)
        self._settings.setValue("columns_locked", self._columns_locked)
        self._apply_column_modes()

    def _reset_columns(self, table=None, hidden=None):
        view = table if table is not None else self._pack()[2]
        header = view.horizontalHeader()
        hidden = self._hidden_columns(view) if hidden is None else hidden
        for column in range(len(COLUMNS)):
            visual = header.visualIndex(column)
            if visual != column:
                header.moveSection(visual, column)
            view.setColumnHidden(column, column in hidden)
            if column in COLUMN_WIDTHS:
                view.setColumnWidth(column, COLUMN_WIDTHS[column])
        self._apply_column_modes(view)

    def _toggle_column(self, column, visible):
        _model, _proxy, table = self._pack()
        if not visible and not any(
            c for c in range(len(COLUMNS))
            if c not in PINNED_COLUMNS and c != column and not table.isColumnHidden(c)
        ):
            return                              # never leave only the row number
        table.setColumnHidden(column, not visible)
        if visible and not table.columnWidth(column):
            table.setColumnWidth(column, COLUMN_WIDTHS.get(column, 100))

    def _build_column_menu(self):
        """The header menu: one checkable item per column, then layout actions."""
        _model, _proxy, table = self._pack()
        header = table.horizontalHeader()
        menu = QMenu(self)
        handlers = {}
        for column in sorted(range(len(COLUMNS)), key=header.visualIndex):
            if column in PINNED_COLUMNS:
                continue
            action = menu.addAction(COLUMNS[column])
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(column))
            handlers[action] = lambda checked, c=column: self._toggle_column(c, checked)
        menu.addSeparator()
        color = self._icon_color()
        fit = menu.addAction(icons.icon("select-all", color), "Fit columns to content")
        handlers[fit] = lambda checked: table.resizeColumnsToContents()
        reset = menu.addAction(icons.icon("refresh", color), "Reset columns")
        handlers[reset] = lambda checked: self._reset_columns(table)
        lock = menu.addAction("Lock column layout")
        lock.setCheckable(True)
        lock.setChecked(self._columns_locked)
        handlers[lock] = self._set_columns_locked
        scroll = menu.addAction("Horizontal scrollbar")
        scroll.setCheckable(True)
        scroll.setChecked(self._h_scrollbar)
        handlers[scroll] = self._set_h_scrollbar
        return menu, handlers

    def _show_header_menu(self, point):
        menu, handlers = self._build_column_menu()
        chosen = menu.exec(self._pack()[2].horizontalHeader().mapToGlobal(point))
        if chosen is not None:
            handlers[chosen](chosen.isChecked())

    def _build_log(self):
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)   # bounded, so long runs stay responsive
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        self.log.setFont(mono)
        return self.log

    def _build_overview(self):
        """Totals for the tab you are on, over the bottom tools."""
        self.overview = OverviewPanel(self)
        self.overview.close_clicked.connect(self._toggle_overview)
        return self.overview

    def _clamp_overview_size(self, *_args):
        """Keep extra splitter space in the table, not a tall empty overview."""
        if not hasattr(self, "splitter") or not hasattr(self, "overview"):
            return
        if self.overview.isHidden():
            return
        sizes = self.splitter.sizes()
        if len(sizes) < 3:
            return
        cap = self.overview.maximumHeight()
        floor = self.overview.minimumHeight()
        ov = sizes[2]
        if floor <= ov <= cap:
            return
        extra = ov - cap if ov > cap else ov - floor
        sizes[2] = cap if ov > cap else floor
        sizes[0] = max(0, sizes[0] + extra)
        self.splitter.blockSignals(True)
        self.splitter.setSizes(sizes)
        self.splitter.blockSignals(False)

    def _refresh_overview(self):
        """The Download tab counts bytes; the Grabber tab counts what it listed."""
        if not hasattr(self, "overview") or self.overview.isHidden():
            return
        if self.tabs.currentIndex() == TAB_GRABBER:
            self.overview.show_readings("Grabber Overview", self._grabber_readings())
        else:
            self.overview.show_readings("Download Overview", self._download_readings())

    def _download_readings(self):
        data = self.model.overview()
        counts = data["counts"]
        return (
            ("Links", str(data["links"])),
            ("Done", str(counts.get("done", 0))),
            ("Speed", f"{sysinfo.human_bytes(data['speed'])}/s"),
            ("Left", sysinfo.human_bytes(data["bytes_left"])),
            ("ETA", format_eta(data["eta"]) if data["eta"] else "-"),
        )

    def _grabber_readings(self):
        data = self.grab_model.overview()
        return (
            ("Links", str(data["links"])),
            ("Checked", str(data["checked"])),
            ("Known", str(data["sized"])),
            ("Unknown", str(data["unsized"])),
        )

    def _toggle_overview(self):
        self.overview.setVisible(self.overview.isHidden())
        self._refresh_overview()
        self._clamp_overview_size()
        self._sync_stats_timer()
        self._sync_menu_state()

    def _build_properties(self):
        """JD-style File Properties above the bottom tools."""
        self.properties = PropertiesPanel(self)
        self.properties.close_clicked.connect(self._toggle_properties)
        self.properties.fields_edited.connect(self._commit_properties)
        self.properties.hide()
        return self.properties

    def _fill_properties(self, *_args):
        if not hasattr(self, "properties"):
            return
        _model, _proxy, table = self._pack()
        if table is None:
            return
        reels = self._selected_reels()
        self.properties.load_reel(reels[0] if reels else None)

    def _commit_properties(self):
        url = self.properties.download_from.text().strip()
        if not url:
            return
        model, _proxy, _table = self._pack()
        if model.update_reel(url, **self.properties.fields()):
            if model is self.model:
                self._schedule_store()

    def _toggle_properties(self, checked=None):
        visible = self.properties.isHidden() if checked is None else bool(checked)
        self.properties.setVisible(visible)
        self._settings.setValue("properties_visible", visible)
        if visible:
            self._fill_properties()
        self._sync_menu_state()

    def _set_sidebar_visible(self, visible, persist=True):
        if hasattr(self, "views"):
            self.views.setVisible(bool(visible))
        if persist:
            self._settings.setValue("sidebar_visible", bool(visible))
        self._sync_menu_state()

    def _toggle_sidebar(self):
        if not hasattr(self, "views"):
            return
        self._set_sidebar_visible(self.views.isHidden())

    def _set_h_scrollbar(self, enabled):
        self._h_scrollbar = bool(enabled)
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn if self._h_scrollbar
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        for view in (getattr(self, "table", None), getattr(self, "grab_table", None)):
            if view is not None:
                view.setHorizontalScrollBarPolicy(policy)
        self._settings.setValue("h_scrollbar", self._h_scrollbar)

    def _build_action_bar(self):
        """Bottom strip: add links on the left, save path, then the job buttons."""
        bar = QWidget()
        bar.setObjectName("actionBar")
        self.action_bar = bar
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(6)

        self.add_new_btn = self._bar_pill(
            "Add New Links", "plus", "blue", self._add_links, self._build_add_menu())
        self.add_new_btn.setToolTip("Paste posts, channels, or playlists, one per line (F5)")
        self.clip_toggle = self._tool_button(
            "link", "Watch the clipboard for links (Ctrl+G)",
            self._toggle_grabber, checkable=True)
        row.addWidget(self.add_new_btn)
        row.addWidget(self.clip_toggle)
        row.addWidget(self._tool_sep())
        row.addWidget(self._build_save_path(), 1)
        row.addWidget(self._tool_sep())

        self.status = QLabel("Idle")
        self.status.hide()
        self.counter = QLabel("0 ● 0")
        self.counter.setObjectName("jobCounter")
        row.addWidget(self.counter)

        self.continue_btn = self._bar_pill(
            "Continue login", "login", "orange", self._continue_login)
        self.cancel_btn = self._bar_pill("Cancel", "cancel", "red", self._cancel)
        self.add_btn = self._bar_pill(
            "Add to downloads", "download", "green", self._add_to_downloads)
        self.add_btn.setToolTip("Move Grabber rows into the Download tab")
        self.download_btn = self._bar_pill(
            "Start all Downloads", "play", "green",
            lambda _=False: self._start_download(), self._build_start_menu())
        self.download_btn.setToolTip(
            "Download remaining items. Finished files are skipped; partial files resume."
        )
        for button in (self.continue_btn, self.cancel_btn, self.add_btn, self.download_btn):
            row.addWidget(button)
        self.options_btn = self._tool_button(
            "settings", "Download and Grabber options", lambda: None)
        self.options_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.options_menu = QMenu(self)
        self.options_btn.setMenu(self.options_menu)
        self.options_menu.aboutToShow.connect(self._populate_options_menu)
        row.addWidget(self.options_btn)
        self._apply_filter()
        return bar

    def _build_save_path(self):
        """Browse the folder new downloads are saved into."""
        group = QWidget()
        group.setObjectName("savePath")
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.save_path_btn = self._tool_button(
            "folder", "Browse download folder", self._browse_save_path)
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setObjectName("savePathEdit")
        self.save_path_edit.setPlaceholderText("Save to…")
        self.save_path_edit.setToolTip("Download save path")
        self.save_path_edit.editingFinished.connect(self._commit_save_path)
        row.addWidget(self.save_path_btn)
        row.addWidget(self.save_path_edit, 1)
        return group

    def _browse_save_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Save downloads to", self._output_root(),
        )
        if not path:
            return
        self.save_path_edit.setText(os.path.normpath(path))
        self._commit_save_path()

    def _commit_save_path(self):
        path = self.save_path_edit.text().strip() or self._output_root()
        path = os.path.normpath(path)
        self._settings.setValue("output_root", path)
        if self.save_path_edit.text() != path:
            self.save_path_edit.setText(path)

    def _sync_save_path_edit(self):
        if getattr(self, "save_path_edit", None) is None:
            return
        current = self._output_root()
        if self.save_path_edit.text() != current:
            self.save_path_edit.setText(current)

    def _apply_views_filter(self):
        panel = getattr(self, "views", None)
        if panel is None:
            return
        kinds = panel.checked_kinds()
        hosts = panel.checked_hosts()
        for proxy in (self.proxy, self.grab_proxy):
            proxy.set_kinds(kinds)
            proxy.set_hosts(hosts)
        self._sync_header_check()

    def _refresh_views(self):
        """Rebuild Video/Music/Image and host checks from the active table."""
        panel = getattr(self, "views", None)
        if panel is None or not hasattr(self, "tabs"):
            return
        model, _proxy, _table = self._pack()
        hosts, kinds = model.host_kind_counts()
        panel.set_counts(hosts, kinds)
        self._apply_views_filter()

    def _apply_filter(self, *args):
        """Views (kind + host) filter the tables; the text proxy stays empty."""
        for proxy in (self.proxy, self.grab_proxy):
            proxy.set_field("all")
            proxy.set_text("")
        self._apply_views_filter()
        self._sync_header_check()

    def _build_add_menu(self):
        """The arrow beside Add New Links: the other ways links get in."""
        menu = QMenu(self)
        for icon_name, text, slot in (
            ("collect", "Paste links…", self._add_links),
            ("link", "Add links from the clipboard", self._add_from_clipboard),
            ("folder", "Open download folder", self._open_folder),
        ):
            action = menu.addAction(text)
            action.setProperty("iconName", icon_name)
            action.triggered.connect(slot)
        return menu

    def _build_start_menu(self):
        """The arrow beside the start button: which rows the job takes."""
        menu = QMenu(self)
        for icon_name, text, slot in (
            ("play", "Start all downloads", lambda: self._start_download(ignore_checks=True)),
            ("select-all", "Start checked only", self._start_download),
            ("cancel", "Cancel job", self._cancel),
        ):
            action = menu.addAction(text)
            action.setProperty("iconName", icon_name)
            action.triggered.connect(lambda _checked=False, run=slot: run())
        return menu

    def _build_options_menu(self):
        """Rebuild and return the tab-aware gear menu (also used by tests)."""
        self._populate_options_menu()
        return self.options_menu

    def _populate_options_menu(self):
        """Gear contents follow the current tab: Grabber extract options vs download."""
        menu = self.options_menu
        menu.clear()
        on_download = self.tabs.currentIndex() == TAB_DOWNLOAD
        if on_download:
            self._add_download_option_widgets(menu)
        else:
            self._add_grabber_option_actions(menu)
        menu.addSeparator()
        props = menu.addAction("Package or Link Properties")
        props.setCheckable(True)
        props.setChecked(not self.properties.isHidden())
        props.toggled.connect(self._toggle_properties)
        overview = menu.addAction("Overview Panel visible")
        overview.setCheckable(True)
        overview.setChecked(not self.overview.isHidden())
        overview.toggled.connect(lambda checked: (
            self.overview.setVisible(checked),
            self._refresh_overview(),
            self._clamp_overview_size(),
            self._sync_stats_timer(),
            self._settings.setValue("overview_visible", checked),
            self._sync_menu_state(),
        ))
        if not on_download:
            sidebar = menu.addAction("Sidebar visible")
            sidebar.setCheckable(True)
            sidebar.setChecked(hasattr(self, "views") and not self.views.isHidden())
            sidebar.toggled.connect(self._set_sidebar_visible)
            customize = menu.addAction("Customize this Bottom Panel")
            customize.triggered.connect(self._open_settings)

    def _add_grabber_option_actions(self, menu):
        top = menu.addAction("Add at top")
        top.setCheckable(True)
        top.setChecked(self.grab_add_at_top)
        top.toggled.connect(self._set_grab_add_at_top)
        confirm = menu.addAction("Auto confirm")
        confirm.setCheckable(True)
        confirm.setChecked(self.grab_auto_confirm)
        confirm.toggled.connect(self._set_grab_auto_confirm)
        start = menu.addAction("Autostart Download")
        start.setCheckable(True)
        start.setChecked(self.grab_autostart)
        start.toggled.connect(self._set_grab_autostart)

    def _add_download_option_widgets(self, menu):
        get = self._settings.value
        chunks = QSpinBox()
        chunks.setRange(1, 32)
        chunks.setValue(int(get("fragments", DEFAULT_FRAGMENTS)))
        chunks.setToolTip("Max chunks per download (yt-dlp -N)")
        chunks.valueChanged.connect(lambda value: self._settings.setValue("fragments", value))
        self._add_menu_labeled_widget(menu, "Max chunks per download", chunks)

        workers = QSpinBox()
        workers.setRange(1, 16)
        workers.setValue(int(get("workers", DEFAULT_WORKERS)))
        workers.setToolTip("Max simultaneous downloads")
        workers.valueChanged.connect(lambda value: self._settings.setValue("workers", value))
        self._add_menu_labeled_widget(menu, "Max simultaneous downloads", workers)

        limit_on = QCheckBox("Speed limit")
        limit_on.setChecked(get("speed_limit_on", False, bool))
        rate = QLineEdit()
        rate.setPlaceholderText("50K")
        rate.setText(get("speed_limit", "", str))
        rate.setMaximumWidth(72)
        rate.setEnabled(limit_on.isChecked())

        def persist_limit():
            self._settings.setValue("speed_limit_on", limit_on.isChecked())
            self._settings.setValue("speed_limit", rate.text().strip())
            rate.setEnabled(limit_on.isChecked())

        limit_on.toggled.connect(lambda _=False: persist_limit())
        rate.editingFinished.connect(persist_limit)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)
        layout.addWidget(limit_on)
        layout.addWidget(rate)
        action = QWidgetAction(menu)
        action.setDefaultWidget(row)
        menu.addAction(action)

    def _add_menu_labeled_widget(self, menu, label, widget):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)
        caption = QLabel(label)
        layout.addWidget(caption, 1)
        layout.addWidget(widget)
        action = QWidgetAction(menu)
        action.setDefaultWidget(row)
        menu.addAction(action)

    def _set_grab_add_at_top(self, enabled):
        self.grab_add_at_top = bool(enabled)
        self._settings.setValue("grab_add_at_top", self.grab_add_at_top)

    def _set_grab_auto_confirm(self, enabled):
        self.grab_auto_confirm = bool(enabled)
        self._settings.setValue("grab_auto_confirm", self.grab_auto_confirm)

    def _set_grab_autostart(self, enabled):
        self.grab_autostart = bool(enabled)
        self._settings.setValue("grab_autostart", self.grab_autostart)

    def _add_from_clipboard(self):
        """Read the clipboard once, without turning the watcher on."""
        urls = extract_supported_urls(QGuiApplication.clipboard().text())
        if not urls:
            alert(
                self, "info", "Nothing to add",
                "The clipboard holds no link from a supported site.",
            )
            return
        self.tabs.setCurrentIndex(TAB_GRABBER)
        if not self.add_grab_urls(urls):
            self._append_log("Clipboard links are already listed.")

    def _build_status_bar(self):
        """Bottom strip: what the machine has left, and what the app is doing."""
        bar = QStatusBar()
        bar.setObjectName("statusStrip")
        bar.setSizeGripEnabled(True)
        self.stats = {}
        self._stat_cells = {}
        # The sample text reserves room for the widest reading, so a section
        # never shoves its neighbours sideways while the numbers tick.
        for key, name, tooltip, sample in (
            ("gpu", "gpu", "Looking for a graphics adapter…", "Intel HD Graphics 630"),
            ("cpu", "cpu", sysinfo.cpu_label(), "100%"),
            ("ram", "ram", "Memory in use on this machine", "888.8 GB / 888.8 GB"),
            ("disk", "disk", "Free space on the download drive", "888.8 GB free on C:"),
        ):
            bar.addWidget(self._stat(key, name, tooltip, sample))
        # Permanent widgets sit on the right, away from the machine readings.
        for key, name, tooltip, sample in (
            ("grabber", "link", "Clipboard Link Grabber", "Grabber off"),
            ("process", "app", "Memory and threads used by this app", "888 MB · 88 thread(s)"),
            ("jobs", "activity", "Running work and its combined speed", "88 downloading · 88.8 MB/s"),
        ):
            bar.addPermanentWidget(self._stat(key, name, tooltip, sample))
        self.setStatusBar(bar)
        return bar

    def _stat(self, key, icon_name, tooltip, sample=""):
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        glyph = QLabel()
        glyph.setProperty("iconName", icon_name)
        value = QLabel("—")
        if sample:
            value.setMinimumWidth(value.fontMetrics().horizontalAdvance(sample))
        row.addWidget(glyph)
        row.addWidget(value)
        self.stats[key] = value
        self._stat_cells[key] = cell
        self._set_stat(key, "—", tooltip)
        return cell

    def _set_stat(self, key, text, tooltip=""):
        self.stats[key].setText(text)
        if not tooltip:
            return
        cell = self._stat_cells[key]
        cell.setToolTip(tooltip)
        for label in cell.findChildren(QLabel):
            label.setToolTip(tooltip)

    def _start_stats(self):
        """Fill the strip now, then keep it ticking while it is on screen."""
        threading.Thread(target=self._detect_gpu, daemon=True).start()
        self._refresh_stats()
        self._sync_stats_timer()

    def _sync_stats_timer(self):
        """Poll only while a panel is showing the readings."""
        if self.statusBar().isHidden() and self.overview.isHidden():
            self._stats_timer.stop()
        else:
            self._stats_timer.start()

    def _detect_gpu(self):
        self.gpu_detected.emit(*sysinfo.gpu_summary())

    @Slot(str, str)
    def _on_gpu_detected(self, label, tooltip):
        self._set_stat("gpu", label, tooltip)

    @Slot()
    def _refresh_stats(self):
        percent = self._cpu_meter.percent()
        cores = os.cpu_count() or 0
        self._set_stat(
            "cpu",
            "—" if percent is None else f"{percent:.0f}%",
            f"CPU load across {cores} logical core(s)" if cores else "CPU load",
        )

        ram = sysinfo.memory()
        if ram and ram[1]:
            used, total = ram
            self._set_stat(
                "ram",
                f"{sysinfo.human_bytes(used)} / {sysinfo.human_bytes(total)}"
                if used else sysinfo.human_bytes(total),
                f"{sysinfo.human_bytes(used)} of {sysinfo.human_bytes(total)} in use"
                f" ({used / total:.0%})" if used else
                f"{sysinfo.human_bytes(total)} of memory installed",
            )

        root = self._output_root()
        space = sysinfo.disk(root)
        if space:
            free, total = space
            self._set_stat(
                "disk",
                f"{sysinfo.human_bytes(free)} free on {sysinfo.volume_name(root)}",
                f"Downloads: {root}\n"
                f"{sysinfo.human_bytes(free)} free of {sysinfo.human_bytes(total)}",
            )

        self._set_stat("grabber", *self._grabber_stats())
        self._set_stat("process", *sysinfo.process_summary())
        self._set_stat("jobs", *self._job_stats())
        self._refresh_overview()

    def _grabber_stats(self):
        """(label, tooltip) for the clipboard watcher, which has no button now."""
        if self.act_grabber.isChecked():
            return "Grabber on", "Collecting supported links you copy (Ctrl+G)"
        return "Grabber off", "Not watching the clipboard (Ctrl+G)"

    def _job_stats(self):
        """(label, tooltip) for the work this window is running right now."""
        active, speed = self.model.active()
        counts = self.model.counts()
        tooltip = ", ".join(
            f"{STATUS_LABELS[s]}: {counts.get(s, 0)}" for s in STATUSES
        )
        if active:
            return f"{active} downloading · {sysinfo.human_bytes(speed)}/s", tooltip
        if self._thread is None:
            return "Idle", tooltip
        if self._grabber_job:
            return "Link Grabber…", tooltip
        return ("Extracting…" if self._collecting else "Working…"), tooltip

    def _action(self, menu, text, slot, shortcut=None, icon="", checkable=False):
        action = QAction(text, self)
        if icon:
            action.setProperty("iconName", icon)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _build_menus(self):
        """Window menu above the toolbar; it owns the shortcuts so they are discoverable."""
        bar = QMenuBar(self)
        bar.setNativeMenuBar(False)
        self.setMenuBar(bar)
        self.menu_bar = bar

        # The logo rides in the menu strip's left corner, ahead of File.
        self.logo = QLabel()
        self.logo.setObjectName("logo")
        self.logo.setPixmap(icons.icon("app", "#1877f2", 64).pixmap(18, 18))
        self.logo.setContentsMargins(6, 0, 4, 0)
        bar.setCornerWidget(self.logo, Qt.Corner.TopLeftCorner)
        self.win_controls = self._build_window_controls()
        bar.setCornerWidget(self.win_controls, Qt.Corner.TopRightCorner)
        bar.installEventFilter(self)

        file_menu = bar.addMenu("&File")
        self.act_collect = self._action(
            file_menu, "&Extract list", self._start_collect,
            QKeySequence.StandardKey.Refresh, "collect")
        self.act_add = self._action(
            file_menu, "Add to down&loads", self._add_to_downloads, "Ctrl+Shift+D",
            "download")
        self.act_download = self._action(
            file_menu, "&Download", self._start_download, "Ctrl+D", "download")
        self.act_cancel = self._action(
            file_menu, "C&ancel job", self._cancel, "Esc", "cancel")
        file_menu.addSeparator()
        self.act_folder = self._action(
            file_menu, "Open download &folder", self._open_folder, None, "folder")
        file_menu.addSeparator()
        self.act_settings = self._action(
            file_menu, "&Settings…", self._open_settings, "Ctrl+,", "settings")
        file_menu.addSeparator()
        self.act_exit = self._action(
            file_menu, "E&xit", self._quit_application, "Ctrl+Q")

        edit_menu = bar.addMenu("&Edit")
        self._action(
            edit_menu, "Select &all", self._select_all,
            QKeySequence.StandardKey.SelectAll, "select-all")
        self._action(edit_menu, "&Invert checks", self._toggle_visible_checks)
        edit_menu.addSeparator()
        self._action(edit_menu, "&Copy URL", self._copy_urls, "Ctrl+C", "copy")
        self._action(edit_menu, "Copy c&aption", self._copy_captions, None, "copy")
        self._action(
            edit_menu, "&Open in browser", self._open_selected, None, "external")
        edit_menu.addSeparator()
        self._action(
            edit_menu, "&Remove selected", self._remove_selected,
            QKeySequence.StandardKey.Delete, "clear")
        self._action(edit_menu, "Remove a&ll", self._remove_all, None, "clear")
        edit_menu.addSeparator()
        self._action(edit_menu, "Move &up", lambda _=False: self._move_selected(-1), None, "move-up")
        self._action(edit_menu, "Move &down", lambda _=False: self._move_selected(1), None, "move-down")

        view_menu = bar.addMenu("&View")
        self.act_log = self._action(
            view_menu, "Show &log", self._toggle_log, "Ctrl+L", "log", checkable=True)
        self.act_status = self._action(
            view_menu, "Show status &bar", self._toggle_status, "Ctrl+B", checkable=True)
        self.act_overview = self._action(
            view_menu, "Show o&verview", self._toggle_overview, "Ctrl+Shift+O",
            checkable=True)
        self.act_properties = self._action(
            view_menu, "Package or &Link Properties", self._toggle_properties,
            checkable=True)
        self.act_sidebar = self._action(
            view_menu, "Show &sidebar", self._toggle_sidebar, checkable=True)
        self.act_action_bar = self._action(
            view_menu, "Show bottom &tools", self._toggle_action_bar, "Ctrl+Shift+B",
            checkable=True)
        self.act_theme = self._action(
            view_menu, "&Dark theme", self._toggle_theme, "Ctrl+T", checkable=True)
        view_menu.addSeparator()
        self.act_lock_columns = self._action(
            view_menu, "Loc&k column layout", self._set_columns_locked, checkable=True)
        self._action(view_menu, "Reset col&umns", lambda _=False: self._reset_columns())

        tools_menu = bar.addMenu("&Tools")
        self.act_grabber = self._action(
            tools_menu, "Link &Grabber", self._toggle_grabber, "Ctrl+G", "link",
            checkable=True)
        self._action(
            tools_menu, "Show grabber &monitor", self._show_grab_monitor, None, "activity")
        tools_menu.addSeparator()
        self._action(tools_menu, "Check for tool &updates", self._check_tool_updates)
        self._action(tools_menu, "Open app &data folder", self._open_state_folder)

        help_menu = bar.addMenu("&Help")
        self._action(help_menu, "&Supported sites", self._show_supported_sites)
        self._action(help_menu, "&About", self._show_about)
        self._sync_menu_state()

    def _sync_menu_state(self):
        """Mirror the panels in the menu's checkable items."""
        if not hasattr(self, "act_log"):
            return
        for action, checked in (
            (self.act_log, not self.log.isHidden()),
            (self.act_status, not self.statusBar().isHidden()),
            (self.act_overview, not self.overview.isHidden()),
            (self.act_properties, not self.properties.isHidden()),
            (self.act_sidebar, hasattr(self, "views") and not self.views.isHidden()),
            (self.act_action_bar, not self.action_bar.isHidden()),
            (self.act_theme, self._dark),
            (self.act_lock_columns, self._columns_locked),
        ):
            action.blockSignals(True)
            action.setChecked(checked)
            action.blockSignals(False)
        self._sync_grabber_ui()

    def _copy_urls(self):
        reels = self._selected_reels() or []
        if reels:
            QGuiApplication.clipboard().setText("\n".join(r.url for r in reels))

    def _copy_captions(self):
        text = "\n".join(
            r.description or r.title
            for r in self._selected_reels() if r.description or r.title
        )
        if text:
            QGuiApplication.clipboard().setText(text)

    def _open_selected(self):
        for reel in self._selected_reels()[:5]:
            QDesktopServices.openUrl(QUrl(reel.url))

    def _remove_all(self):
        model, _proxy, _table = self._pack()
        reels = [model.reel_at(row) for row in range(model.rowCount())]
        if not reels:
            return
        self._delete_reel_files(
            reels,
            "Delete file?",
            "Remove all items from the list.\n\nAlso delete the file(s) from disk?",
        )
        count = len(reels)
        self.clear_rows()
        self._append_log(f"Removed {count} item(s) from the list.")

    def _open_state_folder(self):
        path = state_dir()
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _check_tool_updates(self):
        self._append_log("Checking yt-dlp and FFmpeg for updates…")
        threading.Thread(target=self._run_tool_update, daemon=True).start()

    def _run_tool_update(self):
        ok = update_runtime(force=True)
        versions = runtime_versions()
        self.tools_checked.emit(
            f"yt-dlp {versions['yt_dlp'] or 'missing'} · "
            f"FFmpeg {'ready' if versions['ffmpeg'] else 'missing'}"
            + ("" if ok else " (update could not run)")
        )

    def _show_supported_sites(self):
        PlatformsDialog(self).exec()

    def _show_about(self):
        versions = runtime_versions()
        QMessageBox.about(
            self,
            "About Reels Downloader",
            "Reels Downloader\n\n"
            f"yt-dlp {versions['yt_dlp'] or 'missing'}\n"
            f"FFmpeg: {versions['ffmpeg'] or 'missing'}\n"
            f"Downloads: {self._output_root()}",
        )

    def _icon_button(self, name, tooltip, slot):
        button = QToolButton()
        button.setProperty("iconName", name)
        button.setToolTip(tooltip)
        button.clicked.connect(slot)
        return button

    def _tool_button(self, name, tooltip, slot, checkable=False):
        # No icon size or padding of our own: the style's tool button metrics.
        button = self._icon_button(name, tooltip, slot)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        return button

    def _pill(self, text, name, accent, slot):
        button = QPushButton(text)
        button.setProperty("iconName", name)
        if accent:
            button.setProperty("accent", accent)
        button.clicked.connect(slot)
        return button

    def _bar_pill(self, text, name, accent, slot, menu=None):
        """A labelled bottom-bar button; with `menu` it splits into button + arrow."""
        button = QToolButton()
        button.setText(text)
        button.setProperty("iconName", name)
        if accent:
            button.setProperty("accent", accent)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(15, 15))
        button.clicked.connect(slot)
        if menu is not None:
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        return button

    # ----------------------------------------------------------------- rows

    def set_urls(self, urls):
        self.model.set_urls(urls)
        self.table.sortByColumn(COL_INDEX, Qt.SortOrder.AscendingOrder)
        self.table.scrollToTop()
        self._sync_header_check()
        self._update_counter()
        self._schedule_store()

    def add_grab_urls(self, urls):
        """Append extracted items to the Grabber table, skipping duplicates."""
        urls = list(urls)
        added = self.grab_model.add_entries(urls, prepend=self.grab_add_at_top)
        if self._grabber_job or self._collecting:
            self._grab_added += added
            self._grab_dupes += len(urls) - added
            self._show_grab_panel(
                "Analyzing…" if self._grabber_job else "Extracting…"
            )
            self._sync_extract_loader()
        if added:
            self.grab_table.sortByColumn(COL_INDEX, Qt.SortOrder.AscendingOrder)
            self._sync_header_check()
            self._update_counter()
            self._append_log(f"Grabber listed {added} item(s).")
        return added

    def add_urls(self, urls):
        return self.add_grab_urls(urls)

    def clear_rows(self):
        model, _proxy, table = self._pack()
        model.clear()
        table.sortByColumn(COL_INDEX, Qt.SortOrder.AscendingOrder)
        self._sync_header_check()
        self._update_counter()
        if model is self.model and not self._collecting:
            self._schedule_store()

    def _visible_source_rows(self):
        _model, proxy, _table = self._pack()
        return [proxy.mapToSource(proxy.index(row, 0)).row()
                for row in range(proxy.rowCount())]

    def _toggle_visible_checks(self):
        model, _proxy, _table = self._pack()
        rows = self._visible_source_rows()
        all_on = model.check_state_for_rows(rows) == Qt.CheckState.Checked
        model.set_checked_rows(rows, not all_on)
        self._sync_header_check()

    def _select_all(self):
        model, _proxy, table = self._pack()
        rows = self._visible_source_rows()
        model.set_checked_rows(rows, True)
        table.selectAll()
        self._sync_header_check()

    def _remove_selected(self):
        model, _proxy, _table = self._pack()
        reels = self._selected_reels()
        if not reels:
            reels = [model.reel_at(row) for row in range(model.rowCount())
                      if model.reel_at(row).checked]
        if not reels:
            return
        self._delete_reel_files(
            reels,
            "Delete file?",
            "Remove from the list.\n\nAlso delete the file(s) from disk?",
        )
        removed = model.remove_urls([reel.url for reel in reels])
        if removed:
            self._append_log(f"Removed {removed} item(s) from the list.")
            if model is self.model:
                self._schedule_store()
        self._sync_header_check()
        self._update_counter()

    def _move_selected(self, delta):
        model, proxy, table = self._pack()
        rows = [
            proxy.mapToSource(proxy.index(index.row(), 0)).row()
            for index in table.selectionModel().selectedRows()
        ]
        moved = model.move_rows(rows, delta)
        if not moved:
            return
        table.clearSelection()
        flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        for row in moved:
            mapped = proxy.mapFromSource(model.index(row, 0))
            if mapped.isValid():
                table.selectionModel().select(mapped, flags)
        current = proxy.mapFromSource(model.index(moved[0], 0))
        if current.isValid():
            table.setCurrentIndex(current)
        if model is self.model:
            self._schedule_store()

    def _ask_links(self, current=""):
        """Ask for a paste of links; None when the dialog was cancelled."""
        dialog = AddLinksDialog(current, self)
        return dialog.text() if dialog.exec() else None

    def _add_links(self):
        """Take the Add New Links paste: one link extracts, a batch goes to the grabber."""
        self.tabs.setCurrentIndex(TAB_GRABBER)
        text = self._ask_links(self.source_edit.text())
        if not text:
            return
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        links, unusable = [], 0
        for line in lines:
            found = extract_supported_urls(line)
            if found:
                links.extend(found)
            else:
                unusable += 1
        if len(lines) == 1 and len(links) < 2:
            # One line keeps the old path: Extract repairs the URL, asks the
            # playlist question, and reports why an unusable link was refused.
            self.source_edit.setText(links[0] if links else lines[0])
            self._start_collect()
            return
        if not links:
            alert(
                self, "warning", "Nothing to add",
                "No supported link found. Paste one link per line from Facebook, "
                "Instagram, TikTok, YouTube, X, Bilibili, Douyin, Kuaishou, Pinterest, "
                "or any other video URL.",
            )
            return
        self._add_links_in_background(links, unusable)

    def _add_links_in_background(self, links, unusable=0):
        """Hand a batch to the grabber queue: analyzed one by one, no modal per link."""
        self._grab_manual = True
        queued = self._queue_grab_urls(links)
        skipped = len(links) - queued + unusable
        if skipped:
            self._append_log(f"Skipped {skipped} link(s) already listed or unsupported.")
        if not queued:
            self._grab_manual = False

    def _toolbar_start(self):
        """Play starts the queue; on Grabber it adds listed rows first."""
        if self.tabs.currentIndex() == TAB_GRABBER and self.grab_model.rowCount():
            self._add_to_downloads()
        self._start_download()

    def _update_counter(self):
        self._refresh_overview()
        self._refresh_views()
        if hasattr(self, "tabs") and self.tabs.currentIndex() == TAB_GRABBER:
            total = self.grab_model.rowCount()
            if self._collecting:
                self.counter.setText(f"{total} listed")
                self.counter.setToolTip("Links extracted so far into Grabber")
            else:
                self.counter.setText(f"{total} ready")
                self.counter.setToolTip("Items waiting to be added to Download")
            return
        counts = self.model.counts()
        total = self.model.rowCount()
        failed = counts.get("failed", 0) + counts.get("cancelled", 0)
        self.counter.setText(f"{total} ● {failed}")
        self.counter.setToolTip(
            ", ".join(f"{STATUS_LABELS[s]}: {counts.get(s, 0)}" for s in STATUSES)
        )
        self._refresh_download_label()

    def _refresh_download_label(self):
        done = self.model.counts().get("done", 0)
        pending = self.model.rowCount() - done
        if done and pending > 0:
            self.download_btn.setText("Continue Downloads")
        else:
            self.download_btn.setText("Start all Downloads")

    @Slot(str, dict)
    def _on_progress(self, url, event):
        on_grab = self.grab_model.apply_event(url, event)
        on_list = self.model.apply_event(url, event)
        if (on_grab or on_list) and event.get("status") not in (None, "downloading"):
            self._update_counter()
        status = event.get("status")
        if on_list:
            if status in ("done", "failed", "cancelled"):
                self._flush_store()
            else:
                self._schedule_store()

    def _selected_reels(self):
        model, proxy, table = self._pack()
        rows = {index.row() for index in table.selectionModel().selectedRows()}
        return [model.reel_at(proxy.mapToSource(proxy.index(r, 0)).row())
                for r in sorted(rows)]

    def _context_action(self, menu, text, slot, icon=""):
        color = self._icon_color()
        action = menu.addAction(icons.icon(icon, color), text) if icon else menu.addAction(text)
        if icon:
            action.setProperty("iconName", icon)
        action.triggered.connect(slot)
        return action

    def _set_selected_checks(self, checked):
        model, proxy, table = self._pack()
        rows = [
            proxy.mapToSource(proxy.index(row, 0)).row()
            for row in {index.row() for index in table.selectionModel().selectedRows()}
        ]
        model.set_checked_rows(rows, checked)
        self._sync_header_check()

    def _reveal_selected(self):
        reels = self._selected_reels()
        if reels:
            self._reveal(reels[0])

    def _open_directory_selected(self):
        """Open the folder that holds the selected download (or the channel folder)."""
        reels = self._selected_reels()
        if reels:
            self._open_directory(reels[0])
            return
        self._open_folder()

    def _context_menu_for(self, table):
        """Build the table context menu without showing it (for tests and exec)."""
        grabber = table is self.grab_table
        model = self.grab_model if grabber else self.model
        selected = bool(table.selectionModel() and table.selectionModel().selectedRows())
        menu = QMenu(self)
        if selected:
            if grabber:
                self._context_action(
                    menu, "Add to downloads", self._add_to_downloads, "download")
                menu.addSeparator()
            self._context_action(menu, "Copy URL", self._copy_urls, "copy")
            self._context_action(menu, "Copy caption", self._copy_captions, "copy")
            open_label = "Open in browser" if grabber else "Open reel in browser"
            self._context_action(menu, open_label, self._open_selected, "external")
            if not grabber:
                self._context_action(
                    menu, "Show downloaded file", self._reveal_selected, "folder")
                self._context_action(
                    menu, "Open directory", self._open_directory_selected, "folder")
            menu.addSeparator()
            self._context_action(
                menu, "Check selected", lambda _=False: self._set_selected_checks(True))
            self._context_action(
                menu, "Uncheck selected", lambda _=False: self._set_selected_checks(False))
            if grabber:
                self._context_action(menu, "Invert checks", self._toggle_visible_checks)
                menu.addSeparator()
                self._context_action(
                    menu, "Move up", lambda _=False: self._move_selected(-1), "move-up")
                self._context_action(
                    menu, "Move down", lambda _=False: self._move_selected(1), "move-down")
            menu.addSeparator()
            self._context_action(menu, "Remove from list", self._remove_selected, "clear")
            if model.rowCount():
                self._context_action(
                    menu, "Remove all from list", self._remove_all, "clear")
        else:
            if grabber:
                self._context_action(menu, "Add new links", self._add_links, "plus")
                self._context_action(
                    menu, "Paste from clipboard", self._add_from_clipboard, "link")
            if model.rowCount():
                self._context_action(
                    menu, "Remove all from list", self._remove_all, "clear")
        return menu

    def _show_context_menu(self, point):
        table = self.sender()
        if table not in (getattr(self, "table", None), getattr(self, "grab_table", None)):
            table = self._pack()[2]
        if table is None:
            return
        index = table.indexAt(point)
        if index.isValid() and not table.selectionModel().isSelected(index):
            table.selectRow(index.row())
        menu = self._context_menu_for(table)
        if menu.isEmpty():
            return
        menu.exec(table.viewport().mapToGlobal(point))

    def _open_reel(self, index):
        if index.column() == COL_CHECK:
            return
        model, proxy, _table = self._pack()
        row = proxy.mapToSource(index).row()
        QDesktopServices.openUrl(QUrl(model.reel_at(row).url))

    def _reveal(self, reel):
        folder = os.path.abspath(os.path.join(self._output_root(), self._channel()))
        files = store.list_output_files(folder, reel.rid, reel.filepath)
        if files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(files[0]))
            return
        self._open_folder()

    def _open_directory(self, reel):
        """Open the directory of a saved file; fall back to the channel download folder."""
        folder = os.path.abspath(os.path.join(self._output_root(), self._channel()))
        files = store.list_output_files(folder, reel.rid, reel.filepath)
        if files:
            parent = os.path.dirname(os.path.abspath(files[0]))
            if os.path.isdir(parent):
                QDesktopServices.openUrl(QUrl.fromLocalFile(parent))
                return
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _files_for_reels(self, reels):
        folder = os.path.abspath(os.path.join(self._output_root(), self._channel()))
        files, rids = [], []
        seen = set()
        for reel in reels:
            for path in store.list_output_files(folder, reel.rid, reel.filepath):
                if path not in seen:
                    seen.add(path)
                    files.append(path)
            if reel.rid:
                rids.append(reel.rid)
        return files, rids

    def _delete_reel_files(self, reels, title, text, statuses=None):
        """Ask whether leftover files should be deleted. Yes deletes; No keeps them."""
        if statuses is not None:
            reels = [reel for reel in reels if reel.status in statuses]
        files, rids = self._files_for_reels(reels)
        if not files:
            return False
        names = "\n".join(os.path.basename(path) for path in files[:8])
        extra = f"\n…and {len(files) - 8} more" if len(files) > 8 else ""
        answer = alert(
            self, "question", title,
            f"{text}\n\n{names}{extra}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        deleted = 0
        for path in files:
            try:
                os.remove(path)
                deleted += 1
            except OSError as exc:
                self._append_log(f"Could not delete {path}: {exc}")
        store.forget_archive_ids(
            store.archive_path(self._output_root(), self._channel()),
            rids,
        )
        if deleted:
            self._append_log(f"Deleted {deleted} file(s) from disk.")
        return True

    def _notify_downloads_finished(self, message=""):
        """Popup after a download job so a finished run is obvious even if the window is behind."""
        counts = self.model.counts()
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        total = self.model.rowCount()
        if message == "Cancelled." or cancelled and not done and not failed:
            kind, title = "warning", "Downloads cancelled"
        elif failed:
            kind, title = "warning", "Downloads finished"
        else:
            kind, title = "info", "Downloads finished"
        lines = [f"{done} of {total} item(s) downloaded."]
        if failed:
            lines.append(f"{failed} failed.")
        if cancelled:
            lines.append(f"{cancelled} cancelled.")
        alert(self, kind, title, "\n".join(lines), stay_on_top=True)

    # -------------------------------------------------------------- actions

    def _append_log(self, text):
        self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def _channel(self):
        preferred = self._settings.value("channel", "", str)
        return derive_channel(self.source_edit.text().strip(), preferred)

    def _output_root(self):
        return resolve_output_root(self._settings.value("output_root", "", str))

    def _csv_path(self, channel):
        return collect_csv_path(channel)

    def _schedule_store(self):
        if self._restoring_list or (self._collecting and not self.model.rowCount()):
            return
        self._store_timer.start()

    def _flush_store(self):
        self._store_timer.stop()
        if self._restoring_list or (self._collecting and not self.model.rowCount()):
            return
        channel = self._channel()
        if not channel:
            return
        entries = self.model.entries()
        root = self._output_root()
        store.save_list(store.list_path(root, channel), entries)
        write_entries_csv(self._csv_path(channel), entries)

    def _load_saved_list(self, channel):
        root = self._output_root()
        entries = store.load_list(store.list_path(root, channel))
        if not entries:
            path = self._csv_path(channel)
            if os.path.isfile(path):
                entries = [{"url": url} for url in read_urls(path)]
        if not entries:
            return False
        entries = store.reconcile_entries(
            entries,
            os.path.join(root, channel),
            store.archive_path(root, channel),
        )
        self._restoring_list = True
        try:
            self.set_urls(entries)
        finally:
            self._restoring_list = False
        done = sum(1 for item in entries if item.get("status") == "done")
        pending = len(entries) - done
        self._append_log(
            f"Loaded {len(entries)} item(s)"
            + (f" — {done} done, {pending} remaining." if done else ".")
        )
        return True

    def _open_folder(self):
        path = os.path.abspath(os.path.join(self._output_root(), self._channel()))
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _toggle_log(self):
        # isHidden(), not isVisible(): the panel keeps its state before show().
        self.log.setVisible(self.log.isHidden())
        self._sync_menu_state()

    def _toggle_status(self):
        bar = self.statusBar()
        bar.setVisible(bar.isHidden())
        # A hidden strip keeps no counters warm, so stop polling with it.
        if not bar.isHidden():
            self._refresh_stats()
        self._sync_stats_timer()
        self._sync_menu_state()

    def _toggle_action_bar(self):
        self.action_bar.setVisible(self.action_bar.isHidden())
        self._sync_menu_state()

    def _sync_grabber_ui(self):
        if not hasattr(self, "act_grabber") or not hasattr(self, "clip_btn"):
            return
        checked = self.act_grabber.isChecked()
        for button in (self.clip_btn, self.clip_toggle):
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)
        if getattr(self, "tray", None):
            self.tray.sync_grabber()

    def _toggle_grabber(self, enabled=None):
        enabled = self.act_grabber.isChecked() if enabled is None else bool(enabled)
        self.act_grabber.setChecked(enabled)
        self._sync_grabber_ui()
        self._set_stat("grabber", *self._grabber_stats())
        self._settings.setValue("link_grabber", enabled)
        self._append_log(f"Clipboard Link Grabber {'enabled' if enabled else 'disabled'}.")
        if not enabled:
            self._grab_queue.clear()
            self._grab_manual = False
            self.grab_panel.hide()
        elif self._thread is None:
            self._start_next_grab()

    # ------------------------------------------------------- grabber monitor

    def _grab_readings(self, status):
        """What the floating monitor shows while links sync in behind the UI."""
        return {
            "Found Link(s)": str(self._grab_added),
            "Duplicate(s)": str(self._grab_dupes),
            "Link queue": str(len(self._grab_queue)),
            "Grabber list": str(self.grab_model.rowCount()),
            "Download queue": str(self.model.rowCount()),
            "Status": status,
        }

    def _show_grab_panel(self, status, begin=False):
        panel = self.grab_panel
        readings = self._grab_readings(status)
        if begin or (self._collecting and panel.isHidden()):
            panel.begin_run(readings, self._grab_current)
        elif not panel.isHidden():
            panel.set_readings(readings, self._grab_current)
        self._place_grab_panel()

    def _end_grab_panel(self, status):
        self.grab_panel.end_run(self._grab_readings(status), self._grab_current)
        self._place_grab_panel()

    def _hide_grab_panel(self):
        """The pin keeps the last run's numbers on screen until it is unpinned."""
        if not self.grab_panel.is_pinned():
            self.grab_panel.hide()

    def _show_grab_monitor(self):
        """Bring the monitor back: the last run's numbers until a new one starts."""
        self._grab_close_timer.stop()
        self.grab_panel.show()
        self._show_grab_panel("Analyzing…" if self._grabber_job else "Idle")

    def _place_grab_panel(self):
        """Show the monitor as a desktop tool window, parked once near this app."""
        panel = getattr(self, "grab_panel", None)
        if panel is None or panel.isHidden():
            return
        panel.adjustSize()
        panel.raise_()
        if panel.user_placed:
            return
        floor = self.height()
        for widget in (self.overview, self.action_bar):
            if widget is not None and not widget.isHidden():
                floor = min(floor, widget.mapTo(self, QPoint(0, 0)).y())
        corner = self.mapToGlobal(QPoint(
            self.width() - FLOAT_MARGIN,
            max(floor - FLOAT_MARGIN, FLOAT_MARGIN),
        ))
        panel.move(corner.x() - panel.width(), corner.y() - panel.height())

    def _extract_status_text(self):
        if getattr(self, "continue_btn", None) is not None and self.continue_btn.isEnabled():
            return "Waiting for login", "Log in in Chrome, then click Continue login."
        title = "Link Grabber" if self._grabber_job else "Extracting links"
        detail = self._grab_current or "Looking for links…"
        return title, detail

    def _sync_extract_loader(self, waiting_login=False):
        loader = getattr(self, "extract_loader", None)
        if loader is None:
            return
        if not self._collecting:
            self._hide_extract_loader()
            return
        self.tabs.setCurrentIndex(TAB_GRABBER)
        if waiting_login:
            title, detail = (
                "Waiting for login",
                "Log in in Chrome, then click Continue login.",
            )
        else:
            title, detail = self._extract_status_text()
        listed = self.grab_model.rowCount()
        count = f"{listed} listed" if listed else "Looking for links…"
        loader.show_busy(title, detail, count)
        self._place_extract_loader()

    def _place_extract_loader(self):
        loader = getattr(self, "extract_loader", None)
        table = getattr(self, "grab_table", None)
        page = getattr(self, "grab_page", None)
        if loader is None or table is None or page is None or loader.isHidden():
            return
        origin = table.mapTo(page, QPoint(0, 0))
        loader.setGeometry(origin.x(), origin.y(), table.width(), table.height())
        loader.raise_()

    def _hide_extract_loader(self):
        loader = getattr(self, "extract_loader", None)
        if loader is not None:
            loader.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_extract_loader()

    @Slot()
    def _on_clipboard_changed(self):
        if self.act_grabber.isChecked():
            self._queue_grab_urls(
                extract_supported_urls(QGuiApplication.clipboard().text())
            )

    def _queue_grab_urls(self, urls):
        urls = list(urls)
        known = set(self.model.urls()) | set(self.grab_model.urls()) | set(self._grab_queue)
        if self._grab_current:
            known.add(self._grab_current)
        added = []
        for url in urls:
            if url not in known:
                known.add(url)
                added.append(url)
        self._grab_dupes += len(urls) - len(added)
        if not added:
            self._show_grab_panel("Analyzing…")
            return 0
        self._grab_queue.extend(added)
        self._append_log(f"Link Grabber queued {len(added)} link(s).")
        if self._thread is None and self._grabbing_allowed():
            self._start_next_grab()
        elif self._grabber_job:
            self._show_grab_panel("Analyzing…")
        return len(added)

    def _cancel_grabber(self):
        self._grab_aborted = True
        self._grab_manual = False
        self._grab_queue.clear()
        self._cancel()
        self._end_grab_panel("Aborted")
        self._grab_close_timer.start()
        self._append_log("Link Grabber cancelled.")

    def _grabbing_allowed(self):
        """The watcher drains the queue while it is on; a pasted batch always does."""
        return self.act_grabber.isChecked() or self._grab_manual

    def _start_next_grab(self):
        if self._thread is not None or not self._grabbing_allowed() or not self._grab_queue:
            return
        self._grab_current = self._grab_queue.pop(0)
        if not self._grab_queue:
            self._grab_manual = False
        # A copied link can name a playlist; the background grabber never opens a
        # modal, so it takes the video and says how to get the list.
        pair = youtube_watch_with_list(self._grab_current)
        if pair:
            self._grab_current = pair[0]
            self._append_log(
                "Link Grabber took the single video; paste the playlist on the "
                "Grabber tab and press Extract to take the whole list."
            )
        self._grabber_job = True
        self._collecting = True
        self._grab_aborted = False
        self._grab_close_timer.stop()
        self._show_grab_panel("Analyzing…", begin=True)
        self._append_log(f"Link Grabber collecting: {self._grab_current}")
        self._run(
            JobWorker(
                "collect",
                derive_channel(self._grab_current),
                url=self._grab_current,
                **self._speed(),
            ),
            merge=True,
        )

    def _open_settings(self):
        dialog = SettingsDialog(self._settings, self)
        if dialog.exec():
            self._restore_tool_settings()
            self._sync_save_path_edit()
            self._apply_theme()
            self._sync_menu_state()
            self._sync_close_tooltip()
            if getattr(self, "tray", None):
                self.tray.reload_controls()

    # --------------------------------------------------------------- theme

    def _icon_color(self):
        return "#e7ecf3" if self._dark else "#1c1e21"

    def _toggle_theme(self):
        self._dark = not self._dark
        self._apply_theme()

    def _apply_theme(self):
        app = QApplication.instance()
        if app:
            # Set the color scheme first: it decides the native title bar and
            # resets the style's standard palette used as the base below.
            app.styleHints().setColorScheme(theme.color_scheme(self._dark))
            app.setPalette(theme.palette(self._dark, app.style().standardPalette()))
            app.setStyleSheet(theme.stylesheet(self._dark))
        self.model.set_dark(self._dark)
        self.grab_model.set_dark(self._dark)
        self.setWindowIcon(icons.icon("app", "#1877f2", 64))
        if getattr(self, "tray", None):
            self.tray.refresh_icon()

        # Toolbar icons follow the window text color; icons on an accented pill
        # sit on a colored button, which stays dark in both themes.
        for button in self.findChildren(QToolButton):
            name = button.property("iconName")
            if name:
                accent = button.property("accent")
                button.setIcon(
                    icons.icon(name, "#eef2f7", 15) if accent
                    else icons.icon(name, self._icon_color())
                )
        for button in self.findChildren(QPushButton):
            name = button.property("iconName")
            if name:
                button.setIcon(icons.icon(name, "#eef2f7", 15))
        for label in self.findChildren(QLabel):
            name = label.property("iconName")
            if name:
                label.setPixmap(icons.icon(name, self._icon_color(), 13).pixmap(13, 13))
        for action in self.findChildren(QAction):
            name = action.property("iconName")
            if name:
                action.setIcon(icons.icon(name, self._icon_color()))
        if hasattr(self, "views"):
            self.views.apply_icons(self._icon_color())
        self._sync_menu_state()
        self._sync_window_controls()

    # ----------------------------------------------------------------- jobs

    def _start_collect(self):
        self.tabs.setCurrentIndex(TAB_GRABBER)
        channel, raw_url = self._channel(), self.source_edit.text().strip()
        if not raw_url:
            alert(self, "warning", "Missing URL", "Paste a post, channel, or playlist URL.")
            return
        if looks_shell_truncated(raw_url):
            self._append_log("URL looks truncated; adding the reels tab automatically.")
        try:
            url = normalize_source_url(raw_url)
        except ValueError as exc:
            alert(self, "error", "Invalid URL", str(exc))
            return
        choice = self._playlist_choice(url)
        if choice is None:
            return
        url, feed = choice
        if url != clean_url(raw_url):
            self.source_edit.setText(url)
            self._append_log(f"Using URL: {url}")
        self._remember_url(url)
        self._collecting = True
        self._grab_current = url
        self._grab_added = 0
        self._grab_dupes = 0
        self._grab_aborted = False
        self._run(
            JobWorker("collect", channel, url=url, feed=feed, **self._speed()),
            merge=True,
        )

    def _add_to_downloads(self):
        """Move Grabber rows into the Download queue, then open that tab."""
        self.tabs.setCurrentIndex(TAB_GRABBER)
        reels = self._selected_reels()
        if not reels:
            reels = [self.grab_model.reel_at(row) for row in range(self.grab_model.rowCount())
                      if self.grab_model.reel_at(row).checked]
        if not reels:
            reels = [self.grab_model.reel_at(row) for row in range(self.grab_model.rowCount())]
        if not reels:
            alert(
                self, "warning", "Nothing to add",
                "Extract a URL into the Grabber table first.",
            )
            return
        entries = []
        for reel in reels:
            entry = reel.as_entry()
            entry["status"] = "queued"
            entry["percent"] = 0
            entry["filepath"] = ""
            entries.append(entry)
        added = self.model.add_entries(entries)
        self.grab_model.remove_urls([reel.url for reel in reels])
        skipped = len(entries) - added
        self._sync_header_check()
        self._update_counter()
        if added:
            self._schedule_store()
            self._append_log(f"Added {added} item(s) to Download.")
        if skipped:
            self._append_log(f"Skipped {skipped} item(s) already in Download.")
        self.tabs.setCurrentIndex(TAB_DOWNLOAD)
        self._update_counter()
        if added and self.grab_autostart:
            self._start_download(ignore_checks=True)

    def _playlist_choice(self, url):
        """Ask whether a video-inside-a-playlist link means one video or the list."""
        pair = youtube_watch_with_list(url)
        if not pair:
            return url, None
        video_url, list_url = pair
        box = QMessageBox(self)
        box.setWindowTitle("Playlist link")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("This YouTube link points at a video inside a playlist.")
        box.setInformativeText("Collect only this video, or every video in the list?")
        video_btn = box.addButton("This video", QMessageBox.ButtonRole.AcceptRole)
        list_btn = box.addButton("Whole playlist", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(video_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is video_btn:
            return video_url, False
        if clicked is list_btn:
            return list_url, True
        return None

    def _start_download(self, ignore_checks=False):
        self.tabs.setCurrentIndex(TAB_DOWNLOAD)
        channel = self._channel()
        if not self.model.rowCount() and not self._load_saved_list(channel):
            alert(
                self, "warning", "Nothing to download",
                "Extract items on the Grabber tab, then Add to downloads.",
            )
            return
        selected = None if ignore_checks else (self.model.checked_urls() or None)
        urls = self.model.pending_urls(selected)
        if not urls:
            alert(
                self, "info", "Nothing left",
                "Checked items are already downloaded." if selected is not None
                else "Every item in the list is already downloaded.",
            )
            return
        if selected is not None:
            self._append_log(f"Continuing {len(urls)} checked item(s).")
        elif self.model.counts().get("done"):
            self._append_log(f"Continuing {len(urls)} remaining item(s).")
        wanted = set(urls)
        folders = {
            reel.url: source_folder_name(reel.title, reel.description, reel.rid)
            for reel in (self.model.reel_at(row) for row in range(self.model.rowCount()))
            if reel.url in wanted
        }
        self._run(JobWorker(
            "download", channel, urls=urls, source_folders=folders, **self._speed(),
        ))

    def _speed(self):
        get = self._settings.value
        kinds = ALL_MEDIA_KINDS
        panel = getattr(self, "views", None)
        if panel is not None:
            kinds = panel.checked_kinds() or ALL_MEDIA_KINDS
        return {
            "workers": int(get("workers", DEFAULT_WORKERS)),
            "fragments": int(get("fragments", DEFAULT_FRAGMENTS)),
            "output_root": self._output_root(),
            "filename_template": resolve_filename_template(
                get("filename_template", OUTPUT_TEMPLATE, str)
            ),
            "chrome_binary": get("chrome_binary", "", str),
            "ffmpeg_location": get("ffmpeg_location", "", str),
            "cookies_browser": cookies_from_browser_value(
                get("cookies_browser", "", str),
                get("cookies_profile", "", str),
            ),
            "cookies_file": write_netscape_cookies(get("cookies_curl", "", str)),
            "dateafter": tiktok_dateafter(get("tiktok_age_days", "", str)),
            "limit_rate": (
                get("speed_limit", "", str).strip()
                if get("speed_limit_on", False, bool) else ""
            ),
            "media_kinds": kinds,
        }

    def _run(self, worker, merge=False):
        if self._thread is not None:
            return
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_line.connect(self._append_log)
        worker.waiting_login.connect(self._on_waiting_login)
        worker.urls_ready.connect(self.add_grab_urls if merge else self.set_urls)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(lambda _: thread.quit())
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        self._set_busy(True)
        self.status.setText(
            "Link Grabber collecting…"
            if self._grabber_job
            else ("Extracting…" if self._collecting else "Downloading…")
        )
        if self._collecting:
            if not self._grabber_job:
                self._grab_close_timer.stop()
                self._show_grab_panel("Extracting…", begin=True)
            self._sync_extract_loader()
        thread.start()
        self._set_stat("jobs", *self._job_stats())

    def _set_busy(self, busy):
        idle = not busy
        for widget in (
            self.collect_btn, self.download_btn, self.add_btn, self.add_new_btn,
            self.source_combo, self.start_btn, self.up_btn, self.down_btn,
            self.add_links_btn, self.add_list_btn, self.remove_btn,
            self.settings_tool_btn, self.save_path_edit,
            self.save_path_btn,
        ):
            widget.setEnabled(idle)
        for action in (self.act_collect, self.act_download, self.act_add, self.act_settings):
            action.setEnabled(idle)
        self.act_cancel.setEnabled(busy)
        self.cancel_btn.setEnabled(busy)
        self.stop_btn.setEnabled(busy)
        if getattr(self, "tray", None):
            self.tray.set_busy(busy)
        if not busy:
            self.continue_btn.setEnabled(False)

    @Slot()
    def _on_waiting_login(self):
        self.continue_btn.setEnabled(True)
        self.status.setText("Log in in Chrome, then click Continue login.")
        self._show_grab_panel("Waiting for login")
        self._sync_extract_loader(waiting_login=True)

    @Slot()
    def _continue_login(self):
        if self._worker:
            self._worker.continue_login()
        self.continue_btn.setEnabled(False)
        self.status.setText("Extracting reels…")
        self._show_grab_panel("Extracting…")
        self._sync_extract_loader()

    @Slot()
    def _cancel(self):
        if self._worker:
            self._worker.request_stop()
            self.status.setText("Cancelling…")
        self.continue_btn.setEnabled(False)

    @Slot(str)
    def _on_finished(self, message):
        if message:
            self._append_log(message)
        grab_ok = self._grab_run_succeeded(message)
        if getattr(self._worker, "mode", "") == "download":
            leftovers = [
                self.model.reel_at(row) for row in range(self.model.rowCount())
                if self.model.reel_at(row).status in ("failed", "cancelled")
            ]
            self._delete_reel_files(
                leftovers,
                "Download failed",
                "A download failed or was cancelled.\n\n"
                "Delete leftover file(s) from disk?",
                statuses=("failed", "cancelled"),
            )
            self._notify_downloads_finished(message)
        if self._grabber_job:
            message = "Done" if not message else message
            # More queued links keep the run going, so only the last one is done.
            if self._grab_aborted:
                self._end_grab_panel("Aborted")
            elif self._grab_queue:
                self._show_grab_panel("Analyzing…")
            else:
                self._end_grab_panel("Done!")
        elif self._collecting:
            if self._grab_aborted or message == "Cancelled.":
                self._end_grab_panel("Aborted")
            elif message:
                self._end_grab_panel("Failed")
            else:
                self._end_grab_panel("Done!")
                message = "Done"
            self._grab_close_timer.start()
        keep_loader = (
            self._grabber_job and self._grab_queue and not self._grab_aborted
        )
        self._collecting = False
        if not keep_loader:
            self._hide_extract_loader()
        self.status.setText(message or "Done")
        self.counter.setToolTip(message or "Done")
        self._update_counter()
        self._pending_auto_confirm = grab_ok

    def _grab_run_succeeded(self, message):
        """True when Extract / Link Grabber finished without cancel or error."""
        if self._grab_aborted or message == "Cancelled.":
            return False
        if getattr(self._worker, "mode", "") == "download":
            return False
        if self._collecting:
            return not message
        if self._grabber_job:
            return not self._grab_queue and not message
        return False

    def _apply_pending_auto_confirm(self):
        if not self._pending_auto_confirm:
            return
        self._pending_auto_confirm = False
        if self._grabber_job:
            return
        if self.grab_auto_confirm and self.grab_model.rowCount():
            self._add_to_downloads()

    @Slot()
    def _on_thread_finished(self):
        if self._worker:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None
        was_grabbing = self._grabber_job
        self._grabber_job = False
        self._grab_current = ""
        self._set_busy(False)
        self._set_stat("jobs", *self._job_stats())
        self._start_next_grab()
        if was_grabbing and not self._grabber_job:
            # Nothing left to analyze: leave the result on screen for a moment.
            self._grab_close_timer.start()
            self._grab_added = 0
            self._grab_dupes = 0
        self._apply_pending_auto_confirm()

    # ------------------------------------------------------------- settings

    def _recent_urls(self):
        raw = self._settings.value("recent_urls", [])
        if not raw:
            return []
        if isinstance(raw, str):
            return [raw] if raw.strip() else []
        return [str(item).strip() for item in raw if str(item).strip()]

    def _fill_recent_combo(self, current=""):
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItems(self._recent_urls())
        self.source_combo.setEditText(current)
        self.source_combo.blockSignals(False)

    def _remember_url(self, url):
        urls = remember_recent(self._recent_urls(), url)
        self._settings.setValue("recent_urls", urls)
        self._fill_recent_combo(url.strip() if url else self.source_edit.text())

    def _restore_settings(self):
        get = self._settings.value
        source = get("source", "", str)
        self._fill_recent_combo(source)
        self._restore_tool_settings()
        self._dark = get("dark", self._dark, bool)
        self.log.setVisible(get("log_visible", False, bool))
        self.overview.setVisible(get("overview_visible", True, bool))
        self.action_bar.setVisible(get("action_bar_visible", True, bool))
        self.properties.setVisible(get("properties_visible", False, bool))
        self._set_sidebar_visible(get("sidebar_visible", True, bool), persist=False)
        self._h_scrollbar = get("h_scrollbar", False, bool)
        self._set_h_scrollbar(self._h_scrollbar)
        self.grab_add_at_top = get("grab_add_at_top", False, bool)
        self.grab_auto_confirm = get("grab_auto_confirm", False, bool)
        self.grab_autostart = get("grab_autostart", False, bool)
        self.act_grabber.setChecked(get("link_grabber", True, bool))
        geometry = get("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        split = get("work_split")
        if split and hasattr(self, "work_split"):
            self.work_split.restoreState(split)
        main = get("main_split")
        if main and hasattr(self, "splitter"):
            self.splitter.restoreState(main)
            self._clamp_overview_size()
        self._sync_save_path_edit()
        state = get("header_v6")
        if state:
            self.table.horizontalHeader().restoreState(state)
            self._apply_column_modes()

    def _restore_tool_settings(self):
        get = self._settings.value
        self._dark = get("dark", self._dark, bool)
        self.log.setVisible(get("log_visible", self.log.isVisible(), bool))
        self.act_grabber.setChecked(
            get("link_grabber", self.act_grabber.isChecked(), bool)
        )
        self.grab_add_at_top = get("grab_add_at_top", self.grab_add_at_top, bool)
        self.grab_auto_confirm = get("grab_auto_confirm", self.grab_auto_confirm, bool)
        self.grab_autostart = get("grab_autostart", self.grab_autostart, bool)

    def _save_settings(self):
        put = self._settings.setValue
        source = self.source_edit.text().strip()
        put("source", source)
        if source:
            put("recent_urls", remember_recent(self._recent_urls(), source))
        put("dark", self._dark)
        put("log_visible", self.log.isVisible())
        put("status_visible", not self.statusBar().isHidden())
        put("overview_visible", not self.overview.isHidden())
        put("action_bar_visible", not self.action_bar.isHidden())
        put("properties_visible", not self.properties.isHidden())
        put("sidebar_visible", hasattr(self, "views") and not self.views.isHidden())
        put("h_scrollbar", self._h_scrollbar)
        put("grab_add_at_top", self.grab_add_at_top)
        put("grab_auto_confirm", self.grab_auto_confirm)
        put("grab_autostart", self.grab_autostart)
        put("link_grabber", self.act_grabber.isChecked())
        put("geometry", self.saveGeometry())
        if hasattr(self, "work_split"):
            put("work_split", self.work_split.saveState())
        if hasattr(self, "splitter"):
            put("main_split", self.splitter.saveState())
        put("header_v6", self.table.horizontalHeader().saveState())
        put("columns_locked", self._columns_locked)
        if getattr(self, "grab_panel", None):
            put("grab_monitor", self.grab_panel.saveGeometry())

    def _close_to_tray_enabled(self):
        return (
            not self._quitting
            and getattr(self, "tray", None) is not None
            and TrayController._can_show()
            and self._settings.value("close_to_tray", True, bool)
        )

    def _sync_close_tooltip(self):
        if not hasattr(self, "close_btn"):
            return
        self.close_btn.setToolTip(
            "Close to tray" if self._close_to_tray_enabled() else "Quit"
        )

    def _hide_to_tray(self):
        self.hide()

    def _quit_application(self):
        self._quitting = True
        if getattr(self, "tray", None):
            self.tray.hide_icon()
        self._shutdown()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _shutdown(self):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._set_frame_cursor(None)
        # Stop watching the clipboard first: a closing window must not start
        # another grab while it is shutting its job down.
        try:
            QGuiApplication.clipboard().dataChanged.disconnect(self._on_clipboard_changed)
        except (RuntimeError, TypeError):
            pass
        self._grab_queue.clear()
        self._grab_close_timer.stop()
        if getattr(self, "grab_panel", None):
            self.grab_panel.hide()
        self._stats_timer.stop()
        self._flush_store()
        self._save_settings()
        if getattr(self, "tray", None):
            self.tray.hide_icon()
        if self._worker:
            self._worker.request_stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

    def closeEvent(self, event):
        if self._close_to_tray_enabled():
            event.ignore()
            self._hide_to_tray()
            return
        self._quitting = True
        self._shutdown()
        event.accept()


def run_gui(argv=None):
    argv = argv if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet(theme.DEFAULT_DARK))
    settings = QSettings("facebook-reels-downloader", "gui")
    if QSystemTrayIcon.isSystemTrayAvailable():
        app.setQuitOnLastWindowClosed(False)
    schedule_auto_update(settings.value("auto_update", True, bool))
    window = MainWindow(settings=settings)
    window.show()
    return app.exec()


def main():
    return run_gui()
