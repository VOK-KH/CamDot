"""Main window: Download and Grabber tabs, menus, and job controls."""
import json
import os
import sys
import threading
import time
from collections import deque

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
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from app.core import icons, store, sysinfo, telegram_notify, theme
from app.core.collect import cookies_from_browser_value, write_entries_csv
from app.core.cookies import prepare_cookies_file
from app.core.download import (
    ALL_MEDIA_KINDS, DEFAULT_FRAGMENTS, DEFAULT_WORKERS, OUTPUT_TEMPLATE,
    read_urls, resolve_filename_template, source_folder_name, tiktok_dateafter,
)
from app.gui.constants import (
    COLUMN_WIDTHS,
    CUSTOM_WINDOW_CHROME,
    EDGE_CURSORS,
    FIXED_COLUMNS,
    FRAME_MARGIN,
    GRABBER_HIDDEN,
    GRAB_SYNC_CHUNK,
    GRAB_SYNC_MS,
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
from app.gui.notifications import notify, use_grabber_notifications
from app.gui.instance import InstanceGuard
from app.gui.jobs import JobWorker
from app.gui.widgets.empty import EmptyTableHint
from app.gui.widgets.header import CheckHeaderView
from app.gui.widgets.log_panel import LogPanel
from app.gui.widgets.overview import OverviewPanel
from app.gui.widgets.properties import PropertiesPanel
from app.gui.widgets.delegates import HosterDelegate, TextRowDelegate, VariantDelegate
from app.gui.widgets.progress import ProgressDelegate
from app.gui.widgets.reel_tree import ReelTreeProxy
from app.core.model import (
    COL_CHECK,
    COL_FILE,
    COL_HOST,
    COL_ICON,
    COL_ID,
    COL_INDEX,
    COL_PROGRESS,
    COL_TITLE,
    COL_VARIANT,
    COLUMNS,
    MEDIA_KINDS,
    STATUS_LABELS,
    STATUSES,
    ReelFilterProxy,
    ReelModel,
    extract_package_rows,
    format_eta,
    IMAGE_QUALITIES,
    media_output_files,
    output_folder,
    primary_output_files,
)
from app import __version__
from app.core.fonts import parse_families, setup_app_font, ui_font
from app.core.i18n import apply_language, tr
from app.core.runtime import (
    APP_NAME,
    append_app_log,
    collect_csv_path,
    gui_settings,
    logs_dir,
    quiet_qt_logs,
    resolve_output_root,
    runtime_versions,
    schedule_auto_update,
    state_dir,
    sweep_download_folder,
    update_runtime,
)
from app.core.updates import (
    GITHUB_CHECK_INTERVAL_MS,
    check_for_update,
    format_update_message,
    format_update_prompt,
    should_offer_update,
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
    app_update_found = Signal(object)
    app_update_uptodate = Signal()
    notify_poll_done = Signal(object)
    app_update_downloaded = Signal(str, object)
    open_url = Signal(str)

    def __init__(self, dark=theme.DEFAULT_DARK, settings=None):
        super().__init__()
        self.tools_checked.connect(self._append_log)
        self.open_url.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.gpu_detected.connect(self._on_gpu_detected)
        self.app_update_found.connect(self._prompt_app_update)
        self.app_update_uptodate.connect(self._show_app_uptodate)
        self.app_update_downloaded.connect(self._prompt_restart_for_update)
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 680)
        self._custom_chrome = CUSTOM_WINDOW_CHROME
        if self._custom_chrome:
            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMinimizeButtonHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )
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
        self._primary = theme.DEFAULT_PRIMARY
        self._settings = settings or gui_settings()
        self._apply_locale()
        self._columns_locked = self._settings.value("columns_locked", False, bool)
        self._h_scrollbar = False
        self.grab_add_at_top = False
        self.grab_auto_confirm = False
        self.grab_autostart = False
        self._pending_auto_confirm = False
        self._quitting = False
        self._grab_sync = deque()

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
        self.splitter.addWidget(self._build_overview())
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)
        self.splitter.setStretchFactor(0, 8)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([560, 72])
        self.splitter.splitterMoved.connect(self._clamp_overview_size)
        outer.addWidget(self._build_toolbar())
        outer.addWidget(self.splitter, 1)
        self._build_log()
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
        self._app_update_timer = QTimer(self)
        self._app_update_timer.setInterval(GITHUB_CHECK_INTERVAL_MS)
        self._app_update_timer.timeout.connect(self._poll_github_app_update)
        self._restore_settings()
        try:
            sweep_download_folder(self._output_root())
        except OSError:
            pass
        self._apply_theme()
        self._set_busy(False)
        self._update_counter()
        self._start_stats()
        self._sync_app_update_timer()
        self.notify_poll_done.connect(self._on_notify_poll_done)
        self._notify_timer = QTimer(self)
        self._notify_timer.setInterval(20000)
        self._notify_timer.timeout.connect(self._poll_telegram_notify)
        self._notify_busy = False
        self._sync_notify_timer()
        if self.source_edit.text().strip():
            self._load_saved_list(self._channel())
        self.grab_panel = GrabberPanel(self)
        self.grab_panel.aborted.connect(self._cancel_grabber)
        self._grab_close_timer = QTimer(self)
        self._grab_close_timer.setSingleShot(True)
        self._grab_close_timer.setInterval(2500)
        self._grab_close_timer.timeout.connect(self._hide_grab_panel)
        self._grab_sync_timer = QTimer(self)
        self._grab_sync_timer.setInterval(GRAB_SYNC_MS)
        self._grab_sync_timer.timeout.connect(self._flush_grab_chunk)
        QGuiApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        self.tray = TrayController(self)
        self._sync_close_tooltip()
        # The panels reach the window edge, so the resize band has to see the
        # presses they would otherwise swallow.
        if self._custom_chrome:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)

    # ---------------------------------------------------------------- layout

    def _build_pages(self):
        """Download is the queue; Grabber extracts URLs into its own table first."""
        self.tabs = QTabWidget()
        self.tabs.setObjectName("workTabs")
        self.tabs.addTab(self._build_download_page(), tr("Download"))
        self.tabs.addTab(self._build_grabber_page(), tr("Grabber"))
        self.tabs.currentChanged.connect(self._on_page_changed)
        self.views = ViewsPanel(self)
        self.views.filter_changed.connect(self._persist_views_kinds)
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
        self.table = self._make_table(self.proxy, HIDDEN_BY_DEFAULT, "No downloads")
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
        self.collect_btn = self._pill("Extract", "collect", self._start_collect)
        self.collect_btn.setToolTip("Analyze this URL into the Grabber table")
        self.collect_btn.hide()

    def _build_grabber_page(self):
        page = QWidget()
        page.setObjectName("grabberPage")
        self.grab_page = page
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 4, 0, 0)
        col.setSpacing(6)
        self.grab_table = self._make_table(self.grab_proxy, GRABBER_HIDDEN, "No links")
        col.addWidget(self.grab_table, 1)
        self.extract_loader = ExtractLoader(page)
        self.extract_loader.aborted.connect(self._cancel)
        return page

    def _build_toolbar(self):
        """Icon strip under the menu for job and list actions."""
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
        self.min_btn = self._icon_button("win-minimize", "Minimise to the taskbar", self.showMinimized)
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
        if not self._custom_chrome:
            return
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

    # ----------------------------------------------------------- frameless

    def _frame_host(self, watched):
        """The frameless window this event belongs to, if we draw its edges."""
        if not isinstance(watched, QWidget):
            return None
        window = watched.window()
        if window is self:
            return self
        dock = getattr(self, "log_dock", None)
        if dock is not None and window is dock and dock.isFloating():
            return dock
        return None

    def _resize_edges(self, pos, widget=None):
        """Which window edges `pos` grabs, if any."""
        widget = widget or self
        if widget.isMaximized():
            return Qt.Edge(0)
        edges = Qt.Edge(0)
        if pos.x() < FRAME_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= widget.width() - FRAME_MARGIN:
            edges |= Qt.Edge.RightEdge
        if pos.y() < FRAME_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= widget.height() - FRAME_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _frame_edges_for(self, watched, event):
        """Edges a mouse event grabs, or Qt.Edge(0) when it belongs to the content.

        The panels reach the window edge, so those presses land on them; this
        band stands in for the border the system would otherwise draw.
        """
        if not isinstance(event, QMouseEvent):
            return Qt.Edge(0)
        host = self._frame_host(watched)
        if host is None:
            return Qt.Edge(0)
        return self._resize_edges(host.mapFromGlobal(event.globalPosition().toPoint()), host)

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
        host = self._frame_host(watched)
        handle = host.windowHandle() if host is not None else None
        if handle is None:
            return False
        self._set_frame_cursor(None)
        handle.startSystemResize(edges)
        return True

    def eventFilter(self, watched, event):
        """Resize from the window's outer pixels; drag it by the menu strip."""
        if not self._custom_chrome:
            return super().eventFilter(watched, event)
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
        header = table.header()
        if isinstance(header, CheckHeaderView):
            header.set_check_state(model.check_state_for_rows(self._visible_source_rows()))

    def _tree_for(self, table):
        if table is getattr(self, "grab_table", None):
            return getattr(self, "grab_tree", None)
        if table is getattr(self, "table", None):
            return getattr(self, "download_tree", None)
        return None

    def _map_index_to_source(self, table, index):
        tree = self._tree_for(table)
        if tree is not None and index.model() is tree:
            index = tree.mapToSource(index)
        filter_proxy = self.grab_proxy if table is getattr(self, "grab_table", None) else self.proxy
        return filter_proxy.mapToSource(index)

    def _map_source_to_view(self, table, source_index):
        filter_proxy = self.grab_proxy if table is getattr(self, "grab_table", None) else self.proxy
        mid = filter_proxy.mapFromSource(source_index)
        tree = self._tree_for(table)
        if tree is not None:
            return tree.mapFromSource(mid)
        return mid

    def _make_table(self, proxy, hidden, empty_message="No items"):
        tree = ReelTreeProxy(self)
        proxy.set_tree_mode(True)
        tree.setSourceModel(proxy)
        if proxy is self.proxy:
            self.download_tree = tree
        else:
            self.grab_tree = tree

        table = QTreeView()
        table.setModel(tree)
        table.setItemDelegate(TextRowDelegate(table))
        table.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(table))
        table.setItemDelegateForColumn(COL_HOST, HosterDelegate(table))
        variant_delegate = VariantDelegate(table)
        variant_delegate.quality_chosen.connect(self._on_variant_quality_chosen)
        table.setItemDelegateForColumn(COL_VARIANT, variant_delegate)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setRootIsDecorated(True)
        table.setUniformRowHeights(True)
        table.setExpandsOnDoubleClick(False)
        table.setIconSize(QSize(16, 16))
        table.setDragEnabled(False)
        table.setAcceptDrops(False)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        proxy.dataChanged.connect(self._sync_header_check)
        proxy.modelReset.connect(self._sync_header_check)
        proxy.layoutChanged.connect(self._sync_header_check)

        header = CheckHeaderView(table)
        table.setHeader(header)
        header.setModel(tree)
        header.check_clicked.connect(self._toggle_visible_checks)
        header.setStretchLastSection(False)
        header.setFirstSectionMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        table.selectionModel().selectionChanged.connect(self._fill_properties)
        table.setSortingEnabled(False)
        self._reset_columns(table, hidden)
        table.empty_hint = EmptyTableHint(table, tr(empty_message))
        return table

    def _on_variant_quality_chosen(self, index, quality):
        delegate = self.sender()
        table = delegate.parent() if delegate is not None else None
        if table not in (getattr(self, "grab_table", None), getattr(self, "table", None)):
            return
        if not index.isValid():
            return
        src = self._map_index_to_source(table, index)
        model = self.grab_model if table is self.grab_table else self.model
        reel = model.reel_at(src.row())
        model.update_reel(reel.url, match_variant="image", image_quality=quality)
        if model is self.model:
            model.update_reel(reel.url, match_variant="", image_quality=quality)
        self._fill_properties()

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
            header = view.header()
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
        header = view.header()
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
        header = table.header()
        menu = QMenu(self)
        handlers = {}
        for column in sorted(range(len(COLUMNS)), key=header.visualIndex):
            if column in PINNED_COLUMNS:
                continue
            action = menu.addAction(tr(COLUMNS[column]))
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(column))
            handlers[action] = lambda checked, c=column: self._toggle_column(c, checked)
        menu.addSeparator()
        color = self._icon_color()
        fit = menu.addAction(icons.icon("select-all", color), tr("Fit columns to content"))
        handlers[fit] = lambda checked: table.resizeColumnsToContents()
        reset = menu.addAction(icons.icon("refresh", color), tr("Reset columns"))
        handlers[reset] = lambda checked: self._reset_columns(table)
        lock = menu.addAction(tr("Lock column layout"))
        lock.setCheckable(True)
        lock.setChecked(self._columns_locked)
        handlers[lock] = self._set_columns_locked
        scroll = menu.addAction(tr("Horizontal scrollbar"))
        scroll.setCheckable(True)
        scroll.setChecked(self._h_scrollbar)
        handlers[scroll] = self._set_h_scrollbar
        return menu, handlers

    def _show_header_menu(self, point):
        menu, handlers = self._build_column_menu()
        chosen = menu.exec(self._pack()[2].header().mapToGlobal(point))
        if chosen is not None:
            handlers[chosen](chosen.isChecked())

    def _build_log(self):
        """Dockable log: drag to split, float to a window, or close. Drag back to dock."""
        self.log_panel = LogPanel(self)
        self.log = self.log_panel.view
        self.log_panel.float_requested.connect(self._toggle_log_float)
        self.log_panel.export_requested.connect(self._export_log)
        self.log_panel.folder_requested.connect(self._open_logs_folder)
        self.log_panel.close_requested.connect(self._close_log)
        dock = QDockWidget("Log", self)
        dock.setObjectName("logDock")
        dock.setWidget(self.log_panel)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setTitleBarWidget(self.log_panel.bar)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.topLevelChanged.connect(self._on_log_float_changed)
        dock.visibilityChanged.connect(lambda _visible: self._sync_menu_state())
        self.log_dock = dock
        return dock

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
        if len(sizes) < 2:
            return
        cap = self.overview.maximumHeight()
        floor = self.overview.minimumHeight()
        ov = sizes[-1]
        if floor <= ov <= cap:
            return
        extra = ov - cap if ov > cap else ov - floor
        sizes[-1] = cap if ov > cap else floor
        sizes[0] = max(0, sizes[0] + extra)
        self.splitter.blockSignals(True)
        self.splitter.setSizes(sizes)
        self.splitter.blockSignals(False)

    def _refresh_overview(self):
        """The Download tab counts bytes; the Grabber tab counts what it listed."""
        if not hasattr(self, "overview") or self.overview.isHidden():
            return
        if self.tabs.currentIndex() == TAB_GRABBER:
            self.overview.show_readings(tr("Grabber Overview"), self._grabber_readings())
        else:
            self.overview.show_readings(tr("Download Overview"), self._download_readings())

    def _download_readings(self):
        data = self.model.overview()
        counts = data["counts"]
        return (
            (tr("Links"), str(data["links"])),
            (tr("Done"), str(counts.get("done", 0))),
            (tr("Speed"), f"{sysinfo.human_bytes(data['speed'])}/s"),
            (tr("Left"), sysinfo.human_bytes(data["bytes_left"])),
            (tr("ETA"), format_eta(data["eta"]) if data["eta"] else "-"),
        )

    def _grabber_readings(self):
        data = self.grab_model.overview()
        return (
            (tr("Links"), str(data["links"])),
            (tr("Checked"), str(data["checked"])),
            (tr("Known"), str(data["sized"])),
            (tr("Unknown"), str(data["unsized"])),
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
            "Add New Links", "plus", self._add_links, self._build_add_menu())
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
            "Continue login", "login", self._continue_login)
        self.cancel_btn = self._bar_pill("Cancel", "cancel", self._cancel)
        self.add_btn = self._bar_pill(
            "Add to downloads", "download", self._add_to_downloads)
        self.add_btn.setToolTip("Move Grabber rows into the Download tab")
        self.download_btn = self._bar_pill(
            "Start all Downloads", "play",
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

    def _persist_views_kinds(self):
        panel = getattr(self, "views", None)
        if panel is None:
            return
        self._settings.setValue("views_kinds", ",".join(sorted(panel.checked_kinds())))
        self._settings.setValue("views_folder_group", panel.folder_group_enabled())
        for key, path in panel.kind_folders().items():
            self._settings.setValue(f"views_folder_{key}", path)
        self._apply_kind_folders_to_models()

    def _kind_folders(self):
        panel = getattr(self, "views", None)
        return panel.kind_folders() if panel is not None else {}

    def _folder_group(self):
        panel = getattr(self, "views", None)
        return panel.folder_group_enabled() if panel is not None else False

    def _stamp_entry(self, item):
        data = dict(item) if isinstance(item, dict) else {"url": item}
        root = self._output_root()
        if not str(data.get("save_dir") or "").strip():
            data["save_dir"] = root
        variant = data.get("variant") or ""
        dest = str(self._kind_folders().get(variant) or "").strip()
        if variant and dest:
            data["save_dir"] = dest
        return data

    def _apply_kind_folders_to_models(self):
        folders = self._kind_folders()
        root = self._output_root()
        for model in (getattr(self, "model", None), getattr(self, "grab_model", None)):
            if model is None:
                continue
            for row in range(model.rowCount()):
                reel = model.reel_at(row)
                if not reel.variant:
                    if not reel.save_dir:
                        model.update_reel(reel.url, save_dir=root, match_variant="")
                    continue
                dest = str(folders.get(reel.variant) or "").strip()
                if dest and dest != reel.save_dir:
                    model.update_reel(reel.url, save_dir=dest, match_variant=reel.variant)

    def _views_layout_key(self):
        folders = self._kind_folders()
        return (
            self._folder_group(),
            tuple(sorted((key, folders.get(key, "")) for key, _label in MEDIA_KINDS)),
        )

    def _sync_views_layout(self):
        """Rebuild package rows when Folder group or per-type save folders change."""
        key = self._views_layout_key()
        if key == getattr(self, "_last_views_layout", None):
            return False
        self._last_views_layout = key
        folder_group, _folders = key
        kind_folders = self._kind_folders()
        for tree in (getattr(self, "download_tree", None), getattr(self, "grab_tree", None)):
            if tree is not None:
                tree.set_folder_group(folder_group)
        for model in (getattr(self, "model", None), getattr(self, "grab_model", None)):
            if model is not None and model.rowCount():
                model.reshape_folder_layout(folder_group, kind_folders)
        for table in (getattr(self, "table", None), getattr(self, "grab_table", None)):
            if table is not None:
                self._collapse_tree(table)
        return True

    def _apply_views_filter(self):
        panel = getattr(self, "views", None)
        if panel is None:
            return
        kinds = panel.checked_kinds()
        hosts = panel.checked_hosts()
        for proxy in (self.proxy, self.grab_proxy):
            proxy.set_kinds(kinds)
            proxy.set_hosts(hosts)
        self._sync_views_layout()
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
            action = menu.addAction(tr(text))
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
            action = menu.addAction(tr(text))
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
        props = menu.addAction(tr("Package or Link Properties"))
        props.setCheckable(True)
        props.setChecked(not self.properties.isHidden())
        props.toggled.connect(self._toggle_properties)
        overview = menu.addAction(tr("Overview Panel visible"))
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
            sidebar = menu.addAction(tr("Sidebar visible"))
            sidebar.setCheckable(True)
            sidebar.setChecked(hasattr(self, "views") and not self.views.isHidden())
            sidebar.toggled.connect(self._set_sidebar_visible)
            customize = menu.addAction(tr("Customize this Bottom Panel"))
            customize.triggered.connect(self._open_settings)

    def _add_grabber_option_actions(self, menu):
        self._context_action(menu, "Add New Links", self._add_links, "plus")
        self._context_action(menu, "Paste Links", self._add_from_clipboard, "link")
        self._context_action(menu, "Import list…", self._import_list, "plus")
        self._context_action(
            menu, "Start all Downloads", self._start_all_downloads, "play")
        menu.addSeparator()
        top = menu.addAction(tr("Add at top"))
        top.setCheckable(True)
        top.setChecked(self.grab_add_at_top)
        top.toggled.connect(self._set_grab_add_at_top)
        confirm = menu.addAction(tr("Auto confirm"))
        confirm.setCheckable(True)
        confirm.setChecked(self.grab_auto_confirm)
        confirm.toggled.connect(self._set_grab_auto_confirm)
        start = menu.addAction(tr("Autostart Download"))
        start.setCheckable(True)
        start.setChecked(self.grab_autostart)
        start.toggled.connect(self._set_grab_autostart)
        menu.addSeparator()
        self._context_action(menu, "Sort by Hoster", self._sort_by_hoster)
        menu.addMenu(self._cleanup_menu())

    def _add_download_option_widgets(self, menu):
        get = self._settings.value
        chunks = QSpinBox()
        chunks.setRange(1, 32)
        chunks.setValue(int(get("fragments", DEFAULT_FRAGMENTS)))
        chunks.setToolTip("Max chunks per download")
        chunks.valueChanged.connect(lambda value: self._settings.setValue("fragments", value))
        self._add_menu_labeled_widget(menu, "Max chunks per download", chunks)

        workers = QSpinBox()
        workers.setRange(1, 16)
        workers.setValue(int(get("workers", DEFAULT_WORKERS)))
        workers.setToolTip("Max simultaneous downloads")
        workers.valueChanged.connect(lambda value: self._settings.setValue("workers", value))
        self._add_menu_labeled_widget(menu, "Max simultaneous downloads", workers)

        limit_on = QCheckBox(tr("Speed limit"))
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
        caption = QLabel(tr(label))
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

    def _other_grabber_menu(self):
        menu = QMenu(tr("Other"), self)
        top = menu.addAction(tr("Add at top"))
        top.setCheckable(True)
        top.setChecked(self.grab_add_at_top)
        top.toggled.connect(self._set_grab_add_at_top)
        confirm = menu.addAction(tr("Auto confirm"))
        confirm.setCheckable(True)
        confirm.setChecked(self.grab_auto_confirm)
        confirm.toggled.connect(self._set_grab_auto_confirm)
        start = menu.addAction(tr("Autostart Download"))
        start.setCheckable(True)
        start.setChecked(self.grab_autostart)
        start.toggled.connect(self._set_grab_autostart)
        menu.addSeparator()
        expand = menu.addAction(tr("Expand all packages"))
        expand.triggered.connect(lambda _=False: self._set_grab_packages_expanded(True))
        collapse = menu.addAction(tr("Collapse all packages"))
        collapse.triggered.connect(lambda _=False: self._set_grab_packages_expanded(False))
        return menu

    def _cleanup_menu(self, table=None):
        menu = QMenu(tr("Clean Up..."), self)
        if table is getattr(self, "grab_table", None):
            model = self.grab_model
        elif table is getattr(self, "table", None):
            model = self.model
        else:
            model, _proxy, table = self._pack()
        selected = bool(
            table is not None
            and table.selectionModel()
            and table.selectionModel().selectedRows()
        )
        act_sel = menu.addAction(tr("Delete selected links"))
        act_sel.setEnabled(selected)
        act_sel.triggered.connect(lambda _=False: self._cleanup_links(True))
        act_all = menu.addAction(tr("Delete all links"))
        act_all.setEnabled(model.rowCount() > 0)
        act_all.triggered.connect(lambda _=False: self._cleanup_links(False))
        return menu

    def _sort_by_hoster(self):
        _model, _proxy, table = self._pack()
        if table is not None:
            table.sortByColumn(COL_HOST, Qt.SortOrder.AscendingOrder)

    def _start_all_downloads(self):
        """Add Grabber rows if needed, then start every remaining download."""
        if self.tabs.currentIndex() == TAB_GRABBER and self.grab_model.rowCount():
            was = self.grab_autostart
            self.grab_autostart = False
            try:
                self._add_to_downloads()
            finally:
                self.grab_autostart = was
        self._start_download(ignore_checks=True)

    def _confirm_cleanup(self, action, count, remaining):
        if self._settings.value("cleanup_skip_confirm", False, bool):
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Are you sure?")
        box.setText(
            f"Do you really want to perform this clean up action:\n{action}?"
        )
        box.setInformativeText(
            f"Delete {count} link(s) — {remaining} link(s) remaining."
        )
        box.setIconPixmap(icons.art("botty", "robot_del", 64))
        skip = QCheckBox("Don't show this again")
        box.setCheckBox(skip)
        cont = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cont)
        box.exec()
        if box.clickedButton() is not cont:
            return False
        if skip.isChecked():
            self._settings.setValue("cleanup_skip_confirm", True)
        return True

    def _cleanup_links(self, selected=True):
        model, _proxy, _table = self._pack()
        if selected:
            reels = self._selected_reels()
            action = "Delete Selected Links"
        else:
            reels = [model.reel_at(row) for row in range(model.rowCount())]
            action = "Delete All Links"
        if not reels:
            return
        remaining = max(0, model.rowCount() - len(reels))
        if not self._confirm_cleanup(action, len(reels), remaining):
            return
        if model is self.model:
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
        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setObjectName("versionLabel")
        self.version_label.setToolTip(f"{APP_NAME} {__version__}")
        bar.addPermanentWidget(self.version_label)
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
            return tr("Grabber on"), "Collecting supported links you copy (Ctrl+G)"
        return tr("Grabber off"), "Not watching the clipboard (Ctrl+G)"

    def _job_stats(self):
        """(label, tooltip) for the work this window is running right now."""
        active, speed = self.model.active()
        counts = self.model.counts()
        tooltip = ", ".join(
            f"{tr(STATUS_LABELS[s])}: {counts.get(s, 0)}" for s in STATUSES
        )
        if active:
            return (
                f"{active} {tr('downloading')} · {sysinfo.human_bytes(speed)}/s",
                tooltip,
            )
        if self._thread is None:
            return tr("Idle"), tooltip
        if self._grabber_job:
            return tr("Link Grabber…"), tooltip
        return (tr("Extracting…") if self._collecting else tr("Working…")), tooltip

    def _action(self, menu, text, slot, shortcut=None, icon="", checkable=False):
        action = QAction(tr(text), self)
        if icon:
            action.setProperty("iconName", icon)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _build_logo(self):
        logo = QLabel()
        logo.setObjectName("logo")
        logo.setPixmap(icons.icon("app", self._primary, 64).pixmap(22, 22))
        logo.setContentsMargins(6, 0, 4, 0)
        return logo

    def _embed_toolbar_logo(self):
        """On macOS the menus live in the system bar; keep the logo on the tool strip."""
        bar = self.start_btn.parentWidget()
        layout = bar.layout()
        layout.insertWidget(0, self.logo)
        layout.insertWidget(1, self._tool_sep())

    def _build_menus(self):
        """Window menu above the toolbar; it owns the shortcuts so they are discoverable."""
        bar = QMenuBar(self)
        bar.setNativeMenuBar(not self._custom_chrome)
        self.setMenuBar(bar)
        self.menu_bar = bar

        self.logo = self._build_logo()
        if self._custom_chrome:
            bar.setCornerWidget(self.logo, Qt.Corner.TopLeftCorner)
            self.win_controls = self._build_window_controls()
            bar.setCornerWidget(self.win_controls, Qt.Corner.TopRightCorner)
            bar.installEventFilter(self)
        else:
            self.win_controls = None
            self._embed_toolbar_logo()

        file_menu = bar.addMenu(tr("&File"))
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
        self._action(file_menu, "E&xport list…", self._export_list, None, "csv")
        self._action(file_menu, "Import list…", self._import_list, None, "plus")
        self._action(file_menu, "Retry &failed items", self._retry_failed_items, None, "refresh")
        file_menu.addSeparator()
        self.act_settings = self._action(
            file_menu, "&Settings…", self._open_settings, "Ctrl+,", "settings")
        file_menu.addSeparator()
        self.act_exit = self._action(
            file_menu, "E&xit", self._quit_application, "Ctrl+Q")

        edit_menu = bar.addMenu(tr("&Edit"))
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

        view_menu = bar.addMenu(tr("&View"))
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

        tools_menu = bar.addMenu(tr("&Tools"))
        self.act_grabber = self._action(
            tools_menu, "Link &Grabber", self._toggle_grabber, "Ctrl+G", "link",
            checkable=True)
        self._action(
            tools_menu, "Show grabber &monitor", self._show_grab_monitor, None, "activity")
        tools_menu.addSeparator()
        self._action(tools_menu, "Check for tool &updates", self._check_tool_updates)
        self._action(tools_menu, "Check for app &updates", self._check_app_updates)
        self._action(tools_menu, "Open app &data folder", self._open_state_folder)

        help_menu = bar.addMenu(tr("&Help"))
        self._action(help_menu, "&Supported sites", self._show_supported_sites)
        self._action(help_menu, "Send &feedback…", self._send_feedback)
        self._action(help_menu, "&About", self._show_about)
        self._sync_menu_state()

    def _sync_menu_state(self):
        """Mirror the panels in the menu's checkable items."""
        if not hasattr(self, "act_log"):
            return
        for action, checked in (
            (self.act_log, not self.log_dock.isHidden()),
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
        self._append_log("Checking download tools for updates…")
        threading.Thread(target=self._run_tool_update, daemon=True).start()

    def _check_app_updates(self):
        self._append_log(f"Checking GitHub for {APP_NAME} updates…")
        threading.Thread(
            target=self._run_app_update_check,
            kwargs={"prompt_update": True, "notify_uptodate": True},
            daemon=True,
            name="github-update-check",
        ).start()

    def _poll_github_app_update(self):
        if not self._settings.value("check_app_updates", True, bool):
            return
        threading.Thread(
            target=self._run_app_update_check,
            kwargs={"prompt_update": True, "notify_uptodate": False},
            daemon=True,
            name="github-update-poll",
        ).start()

    def _sync_app_update_timer(self):
        timer = getattr(self, "_app_update_timer", None)
        if timer is None:
            return
        if self._settings.value("check_app_updates", True, bool):
            if not timer.isActive():
                timer.start()
        else:
            timer.stop()

    def _run_app_update_check(self, *, prompt_update=False, notify_uptodate=False):
        info = check_for_update()
        if not info:
            if notify_uptodate:
                self.app_update_uptodate.emit()
            return
        self.tools_checked.emit(format_update_message(info))
        if prompt_update and should_offer_update(info, self._settings):
            self.app_update_found.emit(info)

    @Slot()
    def _show_app_uptodate(self):
        alert(
            self,
            "info",
            "Up to date",
            f"{APP_NAME} {__version__} is up to date.",
        )

    @Slot(object)
    def _prompt_app_update(self, info):
        from app.core.app_updater import is_installed_build

        tag = info.get("tag") or info.get("latest") or ""
        can_install = is_installed_build() and bool(info.get("download_url"))
        extra = (
            "\n\nDownload this version, then close CamDot and install? "
            "The app will reopen after setup."
            if can_install
            else "\n\nOpen the GitHub release page to download it?"
        )
        clicked = alert(
            self,
            "question",
            "Update available",
            f"{format_update_prompt(info)}{extra}",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Ignore,
            QMessageBox.StandardButton.Yes,
        )
        latest = info.get("latest", "")
        if clicked == QMessageBox.StandardButton.Yes:
            if can_install:
                self._append_log(f"Downloading {tag} from GitHub…")
                threading.Thread(
                    target=self._download_app_update,
                    args=(info,),
                    daemon=True,
                    name="github-update-download",
                ).start()
            else:
                url = info.get("page_url") or info.get("download_url")
                if url:
                    QDesktopServices.openUrl(QUrl(url))
        elif clicked == QMessageBox.StandardButton.Ignore:
            self._settings.setValue("skipped_update_version", latest)
            self._settings.sync()
            self._append_log(f"Skipped update {latest}.")
        else:
            self._settings.setValue("update_remind_after", time.time() + 3 * 86400)
            self._settings.sync()
            self._append_log("Update reminder snoozed for 3 days.")

    def _download_app_update(self, info):
        try:
            from app.core.app_updater import download_update

            path = download_update(info)
            self.app_update_downloaded.emit(path, info)
        except Exception as exc:
            self.tools_checked.emit(f"Update download failed: {exc}")
            url = info.get("download_url") or info.get("page_url")
            if url:
                self.open_url.emit(url)

    @Slot(str, object)
    def _prompt_restart_for_update(self, path, info):
        from app.core.app_updater import launch_installer

        tag = info.get("tag") or info.get("latest") or ""
        clicked = alert(
            self,
            "question",
            "Restart to finish update",
            f"{APP_NAME} {tag} is downloaded.\n\n"
            "Close CamDot now and install the new version? "
            "Setup will reopen the app when it finishes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if clicked != QMessageBox.StandardButton.Yes:
            self._append_log(f"Installer saved to {path}")
            return
        if not launch_installer(path):
            self._append_log(f"Could not start installer: {path}")
            return
        self._append_log(f"Installing {os.path.basename(path)}…")
        self._quit_application()

    def _export_list(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export list", "", "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        payload = self.model.entries()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        self._append_log(f"Exported {len(payload)} item(s) to {path}")

    def _import_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import list", "", "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            alert(self, "warning", "Import failed", "The file is not a valid list.")
            return
        entries = [item for item in payload if isinstance(item, dict) and item.get("url")]
        if not entries:
            alert(self, "warning", "Import failed", "No URLs were found in the file.")
            return
        model, _proxy, _table = self._pack()
        model.add_entries(entries)
        self._append_log(f"Imported {len(entries)} item(s) from {path}")
        self._update_counter()
        if model is self.model:
            self._schedule_store()

    def _retry_failed_items(self):
        count = self.model.requeue_failed()
        if not count:
            alert(self, "info", "Nothing to retry", "There are no failed items in the list.")
            return
        self._append_log(f"Requeued {count} failed item(s).")
        self._update_counter()

    def _run_tool_update(self):
        ok = update_runtime(force=True, source="manual")
        versions = runtime_versions()
        if getattr(sys, "frozen", False) and not ok:
            self.tools_checked.emit(
                "Download tools are bundled with this install and cannot be updated here."
            )
            return
        self.tools_checked.emit(
            f"Engine {versions['yt_dlp'] or 'missing'} · "
            f"FFmpeg {'ready' if versions['ffmpeg'] else 'missing'}"
            + ("" if ok else " (update could not run)")
        )

    def _show_supported_sites(self):
        PlatformsDialog(self).exec()

    def _device_id(self):
        from app.core.telegram_report import device_id_from_settings

        return device_id_from_settings(self._settings)

    def _send_feedback(self):
        from app.gui.dialogs.feedback import FeedbackDialog

        dialog = FeedbackDialog(
            device_id=self._device_id(),
            log_text=self.log.toPlainText(),
            parent=self,
        )
        if dialog.exec():
            self._append_log("Feedback sent. Thank you.")

    def _show_about(self):
        versions = runtime_versions()
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"{APP_NAME} {__version__}\n\n"
            f"Engine: {versions['yt_dlp'] or 'missing'}\n"
            f"FFmpeg: {versions['ffmpeg'] or 'missing'}\n"
            f"Downloads: {self._output_root()}",
        )

    def _icon_button(self, name, tooltip, slot):
        button = QToolButton()
        button.setProperty("iconName", name)
        button.setToolTip(tr(tooltip))
        button.clicked.connect(slot)
        return button

    def _tool_button(self, name, tooltip, slot, checkable=False):
        # No icon size or padding of our own: the style's tool button metrics.
        button = self._icon_button(name, tooltip, slot)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        return button

    def _pill(self, text, name, slot):
        button = QPushButton(tr(text))
        button.setProperty("iconName", name)
        button.setProperty("pill", True)
        button.clicked.connect(slot)
        return button

    def _bar_pill(self, text, name, slot, menu=None):
        """A labelled bottom-bar button; with `menu` it splits into button + arrow."""
        button = QToolButton()
        button.setText(tr(text))
        button.setProperty("iconName", name)
        button.setProperty("pill", True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(13, 13))
        button.clicked.connect(slot)
        if menu is not None:
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        return button

    # ----------------------------------------------------------------- rows

    def set_urls(self, urls):
        self.model.set_urls([self._stamp_entry(item) for item in urls])
        if self.model.rowCount():
            self.model.reshape_folder_layout(
                self._folder_group(), self._kind_folders(),
            )
        self._last_views_layout = self._views_layout_key()
        for url in self.model.urls():
            self._sync_output_tree(url)
        self.table.sortByColumn(COL_INDEX, Qt.SortOrder.AscendingOrder)
        self.table.scrollToTop()
        self._sync_header_check()
        self._update_counter()
        self._schedule_store()

    def add_grab_urls(self, urls):
        """Append extracted items to the Grabber table, skipping duplicates."""
        return self._insert_grab_urls(urls, light=False)

    @Slot(list)
    def _enqueue_grab_urls(self, urls):
        """Queue collect results and paint them in chunks so the table stays responsive."""
        if not urls:
            return
        self._grab_sync.extend(urls)
        if self._grab_sync_timer.isActive():
            return
        self._flush_grab_chunk()
        if self._grab_sync:
            self._grab_sync_timer.start()

    def _flush_grab_chunk(self):
        if not self._grab_sync:
            self._grab_sync_timer.stop()
            self._finish_grab_sync()
            return
        chunk = []
        while self._grab_sync and len(chunk) < GRAB_SYNC_CHUNK:
            chunk.append(self._grab_sync.popleft())
        self._insert_grab_urls(chunk, light=True)
        if self._grab_sync:
            return
        self._grab_sync_timer.stop()
        self._finish_grab_sync()
        if self._thread is None:
            self._apply_pending_auto_confirm()

    def _drain_grab_sync(self):
        """Paint every queued package now (end of a collect run, or tests)."""
        self._grab_sync_timer.stop()
        while self._grab_sync:
            chunk = []
            while self._grab_sync and len(chunk) < GRAB_SYNC_CHUNK:
                chunk.append(self._grab_sync.popleft())
            self._insert_grab_urls(chunk, light=True)
        self._finish_grab_sync()

    def _finish_grab_sync(self):
        self.grab_table.sortByColumn(COL_INDEX, Qt.SortOrder.AscendingOrder)
        self.grab_proxy.invalidate()
        self._collapse_tree(self.grab_table)
        self._sync_header_check()
        self._update_counter()

    def _collapse_tree(self, table):
        """Keep package folders collapsed; flat single-file rows stay as-is."""
        if table is None:
            return
        table.collapseAll()

    def _insert_grab_urls(self, urls, light=False):
        known = set(self.grab_model.urls())
        requested = []
        for item in urls:
            url = item.get("url") if isinstance(item, dict) else item
            if url and url not in requested:
                requested.append(url)
        dupes = sum(1 for url in requested if url in known)
        expanded = []
        folders = self._kind_folders()
        kinds = None
        if hasattr(self, "views") and self.views is not None:
            kinds = self.views.checked_kinds() or {"video"}
        for item in urls:
            expanded.extend(extract_package_rows(
                self._stamp_entry(item),
                kinds=kinds,
                kind_folders=folders,
                folder_group=self._folder_group(),
            ))
        table = self.grab_table
        table.setUpdatesEnabled(False)
        try:
            added_rows = self.grab_model.add_entries(expanded, prepend=self.grab_add_at_top)
        finally:
            table.setUpdatesEnabled(True)
        added = len(set(self.grab_model.urls()) - known)
        if self._grabber_job or self._collecting:
            self._grab_added += added
            self._grab_dupes += dupes
            self._show_grab_panel(
                "Analyzing…" if self._grabber_job else "Extracting…"
            )
            self._sync_extract_loader()
        if added_rows and not light:
            self.grab_table.sortByColumn(COL_INDEX, Qt.SortOrder.AscendingOrder)
            self.grab_proxy.invalidate()
            self._sync_header_check()
            self._update_counter()
            self._append_log(f"Grabber listed {added} item(s).")
        elif added_rows and light and self.tabs.currentIndex() == TAB_GRABBER:
            self.counter.setText(
                tr("{n} listed").format(n=self.grab_model.package_count())
            )
        return added

    def _set_grab_packages_expanded(self, expanded):
        self.grab_model.set_all_expanded(expanded)
        if expanded:
            self.grab_table.expandAll()
        else:
            self._collapse_tree(self.grab_table)

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
            self._map_index_to_source(table, index).row()
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
            mapped = self._map_source_to_view(table, model.index(row, 0))
            if mapped.isValid():
                table.selectionModel().select(mapped, flags)
        current = self._map_source_to_view(table, model.index(moved[0], 0))
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
        if len(lines) == 1 and len(links) == 1:
            # One supported link: Extract repairs the URL and asks playlist questions.
            self.source_edit.setText(links[0])
            self._start_collect()
            return
        if not links:
            alert(
                self, "warning", "Nothing to add",
                "No supported link found. Paste one link per line from Facebook, "
                "Instagram, TikTok, YouTube, X, Bilibili, Douyin, Kuaishou, or Pinterest.",
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
            total = self.grab_model.package_count()
            if self._collecting:
                self.counter.setText(tr("{n} listed").format(n=total))
                self.counter.setToolTip("Links extracted so far into Grabber")
            else:
                self.counter.setText(tr("{n} ready").format(n=total))
                self.counter.setToolTip("Items waiting to be added to Download")
            return
        counts = self.model.counts()
        total = self.model.rowCount()
        failed = counts.get("failed", 0) + counts.get("cancelled", 0)
        self.counter.setText(f"{total} ● {failed}")
        self.counter.setToolTip(
            ", ".join(f"{tr(STATUS_LABELS[s])}: {counts.get(s, 0)}" for s in STATUSES)
        )
        self._refresh_download_label()

    def _refresh_download_label(self):
        done = self.model.counts().get("done", 0)
        pending = self.model.rowCount() - done
        if done and pending > 0:
            self.download_btn.setText(tr("Continue Downloads"))
        else:
            self.download_btn.setText(tr("Start all Downloads"))

    @Slot(str, dict)
    def _on_progress(self, url, event):
        on_grab = self.grab_model.apply_event(url, event)
        on_list = self.model.apply_event(url, event)
        if (on_grab or on_list) and event.get("status") not in (None, "downloading"):
            self._update_counter()
        if event.get("filepath") or event.get("status") == "done":
            self._sync_output_tree(url)
        status = event.get("status")
        if on_list:
            if status in ("done", "failed", "cancelled"):
                self._flush_store()
            else:
                self._schedule_store()

    def _sync_output_tree(self, url):
        """Show the save folder as the parent and files in that folder as children."""
        for model, table in ((self.model, self.table), (self.grab_model, self.grab_table)):
            reel = model.package_reel(url)
            if reel is None:
                continue
            folder = self._folder_for_reel(reel)
            raw = [
                path for path in store.list_output_files(folder, reel.rid, reel.filepath)
                if os.path.isfile(path)
                and not path.endswith((".part", ".ytdl"))
            ]
            if not raw:
                continue
            model.attach_output_files(
                url, folder, raw, expand=False, folder_group=self._folder_group(),
            )
            if model is self.model:
                self.proxy.invalidate()
                self._collapse_tree(table)
            else:
                self.grab_proxy.invalidate()
                self._collapse_tree(table)

    def _selected_reels(self):
        model, _proxy, table = self._pack()
        rows = sorted({
            self._map_index_to_source(table, index).row()
            for index in table.selectionModel().selectedRows()
        })
        return [model.reel_at(row) for row in rows]

    def _context_action(self, menu, text, slot, icon=""):
        color = self._icon_color()
        label = tr(text)
        action = menu.addAction(icons.icon(icon, color), label) if icon else menu.addAction(label)
        if icon:
            action.setProperty("iconName", icon)
        action.triggered.connect(slot)
        return action

    def _set_selected_checks(self, checked):
        model, _proxy, table = self._pack()
        rows = [
            self._map_index_to_source(table, index).row()
            for index in table.selectionModel().selectedRows()
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
                menu.addMenu(self._variant_menu())
            else:
                self._context_action(
                    menu, "Start selected", self._start_selected, "play")
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
            menu.addMenu(self._properties_menu())
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
                self._context_action(menu, "Sort by Hoster", self._sort_by_hoster)
                menu.addMenu(self._other_grabber_menu())
                menu.addMenu(self._cleanup_menu(table))
            else:
                menu.addSeparator()
                self._context_action(menu, "Remove from list", self._remove_selected, "clear")
                if model.rowCount():
                    self._context_action(
                        menu, "Remove all from list", self._remove_all, "clear")
        else:
            if grabber:
                self._context_action(menu, "Add New Links", self._add_links, "plus")
                self._context_action(menu, "Paste Links", self._add_from_clipboard, "link")
                self._context_action(menu, "Import list…", self._import_list, "plus")
                self._context_action(
                    menu, "Start all Downloads", self._start_all_downloads, "play")
                menu.addSeparator()
                menu.addMenu(self._properties_menu())
                sort = self._context_action(menu, "Sort by Hoster", self._sort_by_hoster)
                sort.setEnabled(model.rowCount() > 0)
                open_link = self._context_action(
                    menu, "Open in browser", self._open_selected, "external")
                open_link.setEnabled(False)
                menu.addSeparator()
                menu.addMenu(self._other_grabber_menu())
                menu.addMenu(self._cleanup_menu(table))
                self._context_action(menu, "Settings…", self._open_settings, "settings")
            elif model.rowCount():
                self._context_action(
                    menu, "Remove all from list", self._remove_all, "clear")
        return menu

    def _properties_menu(self):
        menu = QMenu(tr("Properties"), self)
        self._context_action(menu, "Rename…", self._rename_selected)
        self._context_action(
            menu, "Set download directory…", self._set_download_directory, "folder")
        self._context_action(menu, "Set comment…", self._set_comment_selected)
        menu.addSeparator()
        self._context_action(
            menu, "Show properties panel", lambda _=False: self._toggle_properties(True))
        return menu

    def _variant_menu(self):
        menu = QMenu(tr("Change Variant"), self)
        add = menu.addAction(tr("Add additional variants"))
        add.triggered.connect(self._add_missing_variants)
        menu.addSeparator()
        for key, label in IMAGE_QUALITIES:
            action = menu.addAction(f"{tr('Image')}: {label}")
            action.triggered.connect(
                lambda _checked=False, quality=key: self._set_image_quality(quality)
            )
        return menu

    def _set_image_quality(self, quality):
        model, _proxy, _table = self._pack()
        for reel in self._selected_reels():
            url = reel.url
            match = reel.variant if reel.variant == "image" else "image"
            model.update_reel(url, match_variant=match, image_quality=quality)
        self._fill_properties()

    def _add_missing_variants(self):
        urls = {reel.url for reel in self._selected_reels()}
        if not urls:
            return
        extras = []
        have = set()
        bases = {}
        for row in range(self.grab_model.rowCount()):
            reel = self.grab_model.reel_at(row)
            have.add((reel.url, reel.variant or ""))
            if reel.url in urls and (reel.url not in bases or not reel.variant):
                bases[reel.url] = reel.as_entry()
        for url in urls:
            base = dict(bases.get(url) or {"url": url})
            base.pop("variant", None)
            kinds = self.views.checked_kinds() if hasattr(self, "views") else None
            for item in extract_package_rows(
                base,
                kinds=kinds,
                kind_folders=self._kind_folders(),
                folder_group=self._folder_group(),
            ):
                key = (item.get("url"), item.get("variant") or "")
                if key not in have:
                    extras.append(item)
        if extras:
            self.grab_model.add_entries(extras)

    def _start_selected(self):
        self.tabs.setCurrentIndex(TAB_DOWNLOAD)
        self._set_selected_checks(True)
        self._start_download()

    def _rename_selected(self):
        reels = self._selected_reels()
        if not reels:
            return
        text, ok = QInputDialog.getText(
            self, "Rename", "Name", QLineEdit.EchoMode.Normal, reels[0].title or "",
        )
        if not ok:
            return
        title = text.strip()
        model, _proxy, _table = self._pack()
        for reel in reels:
            model.update_reel(reel.url, title=title)
        self._fill_properties()
        if model is self.model:
            self._schedule_store()

    def _set_comment_selected(self):
        reels = self._selected_reels()
        if not reels:
            return
        text, ok = QInputDialog.getText(
            self, "Comment", "Comment", QLineEdit.EchoMode.Normal, reels[0].comment or "",
        )
        if not ok:
            return
        model, _proxy, _table = self._pack()
        for reel in reels:
            model.update_reel(reel.url, comment=text)
        self._fill_properties()
        if model is self.model:
            self._schedule_store()

    def _set_download_directory(self):
        reels = self._selected_reels()
        if not reels:
            return
        start = reels[0].save_dir or self._output_root()
        path = QFileDialog.getExistingDirectory(self, "Set download directory", start)
        if path:
            self._apply_save_dir(os.path.normpath(path), reels)

    def _apply_save_dir(self, path, reels=None):
        """Point selected (or given) rows at one folder instead of grouping them."""
        reels = list(reels or self._selected_reels())
        if not path or not reels:
            return
        model, _proxy, _table = self._pack()
        for reel in reels:
            model.update_reel(reel.url, save_dir=path)
        self._fill_properties()
        if model is self.model:
            self._schedule_store()

    def _folder_for_reel(self, reel):
        folder = output_folder(reel)
        if folder:
            return os.path.abspath(folder)
        return os.path.abspath(os.path.join(self._output_root(), self._channel()))

    def _show_context_menu(self, point):
        table = self.sender()
        if table not in (getattr(self, "table", None), getattr(self, "grab_table", None)):
            table = self._pack()[2]
        if table is None:
            return
        index = table.indexAt(point)
        if index.isValid() and not table.selectionModel().isSelected(index):
            table.selectionModel().select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        menu = self._context_menu_for(table)
        if menu.isEmpty():
            return
        menu.exec(table.viewport().mapToGlobal(point))

    def _reveal(self, reel):
        folder = self._folder_for_reel(reel)
        files = store.list_output_files(folder, reel.rid, reel.filepath)
        if files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(files[0]))
            return
        self._open_folder_path(folder)

    def _open_directory(self, reel):
        """Open the row's save folder, or the finished file's parent."""
        folder = self._folder_for_reel(reel)
        files = store.list_output_files(folder, reel.rid, reel.filepath)
        if files:
            parent = os.path.dirname(os.path.abspath(files[0]))
            if os.path.isdir(parent):
                QDesktopServices.openUrl(QUrl.fromLocalFile(parent))
                return
        self._open_folder_path(folder)

    def _open_folder_path(self, folder):
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _files_for_reels(self, reels):
        files, rids = [], []
        seen = set()
        for reel in reels:
            folder = self._folder_for_reel(reel)
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
            kind, title = "done", "Downloads finished"
        lines = [f"{done} of {total} item(s) downloaded."]
        if failed:
            lines.append(f"{failed} failed.")
        if cancelled:
            lines.append(f"{cancelled} cancelled.")
        alert(self, kind, title, "\n".join(lines), stay_on_top=True)
        telegram_notify.notify_download_done(self._settings, title, "\n".join(lines))

    # -------------------------------------------------------------- actions

    def _append_log(self, text):
        self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        try:
            append_app_log(text)
        except OSError:
            pass

    def _export_log(self):
        folder = logs_dir()
        os.makedirs(folder, exist_ok=True)
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export log",
            os.path.join(folder, "camdot-log.txt"),
            "Log files (*.txt *.log);;All files (*.*)",
        )
        if not path:
            return
        self._write_log_export(path)
        self._append_log(f"Exported log to {path}")

    def _write_log_export(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.log.toPlainText())
        return path

    def _open_logs_folder(self):
        folder = logs_dir()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _close_log(self):
        self.log_dock.hide()
        self._sync_menu_state()

    def _toggle_log_float(self):
        dock = self.log_dock
        if dock.isHidden():
            dock.show()
        if dock.isFloating():
            self._set_log_frameless(False)
            dock.setFloating(False)
        else:
            dock.setFloating(True)
            if dock.isFloating():
                dock.resize(680, 380)
                dock.raise_()
        self._on_log_float_changed(dock.isFloating())

    def _set_log_frameless(self, frameless):
        """Drop the system title bar while the log is its own window."""
        if not self._custom_chrome:
            return
        dock = self.log_dock
        flag = Qt.WindowType.FramelessWindowHint
        enabled = bool(dock.windowFlags() & flag)
        if enabled == bool(frameless):
            return
        dock.setWindowFlag(flag, bool(frameless))
        if frameless and dock.isFloating():
            dock.show()

    def _on_log_float_changed(self, floating):
        floating = bool(floating)
        self.log_panel.set_floating(floating)
        if floating:
            self._set_log_frameless(True)
        if hasattr(self, "_icon_color"):
            button = self.log_panel.float_btn
            name = button.property("iconName")
            if name:
                button.setIcon(icons.icon(name, self._icon_color()))
        self._sync_menu_state()

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
        self.log_dock.setVisible(self.log_dock.isHidden())
        if self.log_dock.isVisible() and self.log_dock.isFloating():
            self.log_dock.raise_()
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
            "Grabber list": str(self.grab_model.package_count()),
            "Download queue": str(self.model.rowCount()),
            "Status": status,
        }

    def _grab_panel_visible(self):
        panel = self.grab_panel
        return not panel.isHidden() or panel.is_pinned()

    def _grab_notification_text(self, status):
        readings = self._grab_readings(status)
        return (
            f"{readings['Found Link(s)']} found · {readings['Duplicate(s)']} duplicates\n"
            f"{readings['Grabber list']} in grabber · "
            f"{readings['Download queue']} in download"
        )

    def _show_grab_panel(self, status, begin=False):
        panel = self.grab_panel
        readings = self._grab_readings(status)
        if use_grabber_notifications() and not self._grab_panel_visible():
            if begin:
                notify(self, "Parse Clipboard", status)
            elif status == "Waiting for login":
                notify(
                    self,
                    "Parse Clipboard",
                    "Log in in Chrome, then click Continue login.",
                )
            return
        if begin or (self._collecting and panel.isHidden()):
            panel.begin_run(readings, self._grab_current)
        elif not panel.isHidden():
            panel.set_readings(readings, self._grab_current)
        self._place_grab_panel()

    def _end_grab_panel(self, status):
        if use_grabber_notifications() and not self._grab_panel_visible():
            if status in ("Done!", "Aborted", "Failed", "Idle"):
                notify(
                    self,
                    f"Parse Clipboard — {status}",
                    self._grab_notification_text(status),
                )
            return
        self.grab_panel.end_run(self._grab_readings(status), self._grab_current)
        self._place_grab_panel()
        if status in ("Done!", "Aborted", "Idle"):
            self._hide_grab_panel()

    def _hide_grab_panel(self):
        """The pin keeps the last run's numbers on screen until it is unpinned."""
        if self.grab_panel.is_pinned():
            return
        self.grab_panel.slide_hide()

    def _show_grab_monitor(self):
        """Bring the monitor back: the last run's numbers until a new one starts."""
        self._grab_close_timer.stop()
        self.grab_panel.show()
        self._show_grab_panel("Analyzing…" if self._grabber_job else "Idle")

    def _place_grab_panel(self):
        """Keep the monitor on the screen's bottom-right unless the user dragged it."""
        panel = getattr(self, "grab_panel", None)
        if panel is None or panel.isHidden() or panel.user_placed or panel.is_sliding():
            return
        panel.dock_bottom_right(animate=False)

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
                tr("Waiting for login"),
                tr("Log in in Chrome, then click Continue login."),
            )
        else:
            title, detail = self._extract_status_text()
            title, detail = tr(title), tr(detail)
        listed = self.grab_model.package_count()
        count = (
            tr("{n} listed").format(n=listed) if listed else tr("Looking for links…")
        )
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
        raw = self._grab_queue.pop(0)
        if not self._grab_queue:
            self._grab_manual = False
        if youtube_watch_with_list(raw):
            if getattr(self, "tray", None):
                self.tray.show_window()
            else:
                self.show()
                self.raise_()
                self.activateWindow()
        choice = self._playlist_choice(raw)
        if choice is None:
            self._grab_current = ""
            self._append_log("Link Grabber skipped a YouTube playlist link (cancelled).")
            QTimer.singleShot(0, self._start_next_grab)
            return
        url, feed = choice
        self._grab_current = url
        self._grabber_job = True
        self._collecting = True
        self._grab_aborted = False
        self._grab_close_timer.stop()
        self._show_grab_panel("Analyzing…", begin=True)
        kind = "playlist" if feed else ("video" if feed is False else "link")
        self._append_log(f"Link Grabber collecting {kind}: {url}")
        self._run(
            JobWorker(
                "collect",
                derive_channel(url),
                url=url,
                feed=feed,
                **self._speed(),
            ),
            merge=True,
        )

    def _open_settings(self):
        dialog = SettingsDialog(self._settings, self)
        if dialog.exec():
            self._restore_tool_settings()
            self._sync_app_update_timer()
            self._sync_save_path_edit()
            self._apply_theme()
            self._apply_locale()
            self._sync_menu_state()
            self._sync_close_tooltip()
            if getattr(self, "tray", None):
                self.tray.reload_controls()
            self._sync_notify_timer()

    # --------------------------------------------------------------- theme

    def _apply_locale(self):
        """Language follows Windows unless Settings picks one. Extra fonts sit ahead of the system font."""
        apply_language(self._settings.value("ui_language", "system", str))
        font = ui_font(parse_families(self._settings.value("ui_fonts", "", str)))
        app = QApplication.instance()
        if app is not None:
            app.setFont(font)
        self.setFont(font)
        self._refresh_locale_text()

    def _refresh_locale_text(self):
        if not hasattr(self, "tabs"):
            return
        self.tabs.setTabText(TAB_DOWNLOAD, tr("Download"))
        self.tabs.setTabText(TAB_GRABBER, tr("Grabber"))
        for table, key in (
            (getattr(self, "table", None), "No downloads"),
            (getattr(self, "grab_table", None), "No links"),
        ):
            hint = getattr(table, "empty_hint", None) if table is not None else None
            if hint is not None:
                hint.set_message(tr(key))
        if hasattr(self, "add_new_btn"):
            self.add_new_btn.setText(tr("Add New Links"))
            self.add_btn.setText(tr("Add to downloads"))
            self.continue_btn.setText(tr("Continue login"))
            self.cancel_btn.setText(tr("Cancel"))
            self._refresh_download_label()
        if hasattr(self, "log_panel"):
            self.log_panel.refresh_text()
        for model in (getattr(self, "model", None), getattr(self, "grab_model", None)):
            if model is None or model.columnCount() <= 0:
                continue
            model.headerDataChanged.emit(
                Qt.Orientation.Horizontal, 0, model.columnCount() - 1,
            )
            if model.rowCount():
                model.dataChanged.emit(
                    model.index(0, 0),
                    model.index(model.rowCount() - 1, model.columnCount() - 1),
                    [Qt.ItemDataRole.DisplayRole],
                )
        if hasattr(self, "overview") and not self.overview.isHidden():
            self._refresh_overview()
        if hasattr(self, "counter"):
            self._update_counter()
        if hasattr(self, "_cpu_meter"):
            self._refresh_stats()

    def _icon_color(self):
        return theme.icon_fg(self._dark)

    def _button_icon_color(self, button):
        if button.property("pill"):
            return theme.icon_fg(self._dark)
        return self._icon_color()

    def _toggle_theme(self):
        self._dark = not self._dark
        self._apply_theme()

    def _apply_theme(self):
        self._primary = theme.set_primary(self._primary)
        app = QApplication.instance()
        if app:
            # Set the color scheme first: it decides the native title bar and
            # resets the style's standard palette used as the base below.
            app.styleHints().setColorScheme(theme.color_scheme(self._dark))
            app.setPalette(theme.palette(self._dark, app.style().standardPalette(), self._primary))
            app.setStyleSheet(theme.stylesheet(self._dark, self._primary))
        self.model.set_dark(self._dark)
        self.grab_model.set_dark(self._dark)
        self.setWindowIcon(icons.icon("app", self._primary, 64))
        if getattr(self, "logo", None):
            self.logo.setPixmap(icons.icon("app", self._primary, 64).pixmap(22, 22))
        if getattr(self, "tray", None):
            self.tray.refresh_icon()

        for button in self.findChildren(QToolButton):
            name = button.property("iconName")
            if name:
                button.setIcon(icons.icon(name, self._button_icon_color(button)))
        for button in self.findChildren(QPushButton):
            name = button.property("iconName")
            if name:
                button.setIcon(icons.icon(name, self._button_icon_color(button)))
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
        default_dir = ""
        if getattr(self, "save_path_edit", None) is not None:
            default_dir = self.save_path_edit.text().strip()
        selected_keys = {(reel.url, reel.variant or "") for reel in reels}
        want_all = {url for url, variant in selected_keys if not variant}
        kinds_by_url = {}
        quality_by_url = {}
        templates = {}
        view_kinds = self.views.checked_kinds() if hasattr(self, "views") else set()
        for row in range(self.grab_model.rowCount()):
            reel = self.grab_model.reel_at(row)
            if reel.url not in {item[0] for item in selected_keys}:
                continue
            if not reel.variant:
                templates[reel.url] = reel
                continue
            selected_child = (reel.url, reel.variant) in selected_keys
            if selected_child or (
                reel.url in want_all and (not view_kinds or reel.variant in view_kinds)
            ):
                kinds_by_url.setdefault(reel.url, set()).add(reel.variant)
                if reel.variant == "image":
                    quality_by_url[reel.url] = reel.image_quality or "best"
                templates.setdefault(reel.url, reel)
        folders = self._kind_folders()
        folder_group = self._folder_group()
        entries = []
        for url, reel in templates.items():
            base = reel.as_entry()
            base["status"] = "queued"
            base["percent"] = 0
            base["filepath"] = ""
            kinds = kinds_by_url.get(url) or set(view_kinds) or {"video"}
            base["media_kinds"] = kinds
            base["image_quality"] = quality_by_url.get(url, "")
            if not base.get("save_dir"):
                base["save_dir"] = default_dir
            for item in extract_package_rows(
                base,
                kinds=tuple(sorted(kinds)),
                kind_folders=folders,
                folder_group=folder_group,
            ):
                item["status"] = "queued"
                item["percent"] = 0
                item["filepath"] = ""
                entries.append(item)
        added = self.model.add_entries(entries)
        self.grab_model.remove_urls(list(templates))
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
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
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
        per_link_folders = (
            self._settings.value("group_downloads", False, bool)
            or self._folder_group()
        )
        view_kinds = (
            self.views.checked_kinds() if hasattr(self, "views") else None
        ) or {"video"}
        folders = {}
        url_media_kinds = {}
        for row in range(self.model.rowCount()):
            reel = self.model.reel_at(row)
            if reel.url not in wanted:
                continue
            if reel.variant:
                if reel.variant in view_kinds:
                    url_media_kinds.setdefault(reel.url, set()).add(reel.variant)
            elif reel.media_kinds:
                picked = set(reel.media_kinds) & view_kinds
                if picked:
                    url_media_kinds.setdefault(reel.url, set()).update(picked)
        for url in wanted:
            pkg = self.model.package_reel(url)
            if pkg is None:
                continue
            dest = (pkg.save_dir or "").strip()
            if per_link_folders:
                name = source_folder_name(pkg.title, pkg.description, pkg.rid)
                dest = os.path.join(dest, name) if dest else name
            folders[url] = dest
            if url not in url_media_kinds:
                stored = set(pkg.media_kinds or ()) & view_kinds
                url_media_kinds[url] = stored or set(view_kinds)
            else:
                url_media_kinds[url] = set(url_media_kinds[url]) & view_kinds
                if not url_media_kinds[url]:
                    url_media_kinds[url] = set(view_kinds)
        self._run(JobWorker(
            "download",
            channel,
            urls=urls,
            source_folders=folders,
            group_by_source=False,
            url_media_kinds=url_media_kinds,
            **self._speed(),
        ))

    def _speed(self):
        get = self._settings.value
        kinds = {"video"}
        panel = getattr(self, "views", None)
        if panel is not None:
            kinds = panel.checked_kinds() or {"video"}
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
            "cookies_file": prepare_cookies_file(
                curl_text=get("cookies_curl", "", str),
                json_path=get("cookies_json", "", str),
                profile_id=get("cookies_json_profile", "", str),
            ),
            "dateafter": tiktok_dateafter(get("tiktok_age_days", "", str)),
            "limit_rate": (
                get("speed_limit", "", str).strip()
                if get("speed_limit_on", False, bool) else ""
            ),
            "media_kinds": kinds,
            "kind_folders": self._kind_folders(),
        }

    def _run(self, worker, merge=False):
        if self._thread is not None:
            return
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_line.connect(self._append_log)
        worker.waiting_login.connect(self._on_waiting_login)
        worker.urls_ready.connect(self._enqueue_grab_urls if merge else self.set_urls)
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
        self._drain_grab_sync()
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
        self._drain_grab_sync()
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
        self._primary = theme.normalize_hex(get("theme_primary", self._primary, str))
        self.log_dock.setVisible(get("log_visible", False, bool))
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
        if hasattr(self, "views"):
            raw = get("views_kinds")
            if raw is None:
                keys = ["video"]
            elif isinstance(raw, (list, tuple)):
                keys = [str(item).strip() for item in raw if str(item).strip()]
            else:
                keys = [part.strip() for part in str(raw).split(",") if part.strip()]
            self.views.set_checked_kinds(keys, emit=False)
            folders = {}
            for key, _label in MEDIA_KINDS:
                folders[key] = get(f"views_folder_{key}", "", str)
            self.views.set_kind_folders(folders)
            self.views.set_folder_group(get("views_folder_group", False, bool), emit=False)
            self._apply_kind_folders_to_models()
            self._apply_views_filter()
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
        dock_state = get("dock_state")
        if dock_state:
            self.restoreState(dock_state)
        self.log_dock.setVisible(get("log_visible", False, bool))
        self._sync_save_path_edit()
        state = get("header_v8")
        if state:
            self.table.header().restoreState(state)
            self._apply_column_modes()

    def _restore_tool_settings(self):
        get = self._settings.value
        self._dark = get("dark", self._dark, bool)
        self._primary = theme.normalize_hex(
            get("theme_primary", getattr(self, "_primary", theme.DEFAULT_PRIMARY), str)
        )
        self.log_dock.setVisible(get("log_visible", not self.log_dock.isHidden(), bool))
        self.act_grabber.setChecked(
            get("link_grabber", self.act_grabber.isChecked(), bool)
        )
        self.grab_add_at_top = get("grab_add_at_top", self.grab_add_at_top, bool)
        self.grab_auto_confirm = get("grab_auto_confirm", self.grab_auto_confirm, bool)
        self.grab_autostart = get("grab_autostart", self.grab_autostart, bool)
        self._sync_notify_timer()

    def _sync_notify_timer(self):
        timer = getattr(self, "_notify_timer", None)
        if timer is None:
            return
        if telegram_notify.enabled(self._settings) and telegram_notify.bot_token(self._settings):
            if not timer.isActive():
                timer.start()
        else:
            timer.stop()

    def _poll_telegram_notify(self):
        if getattr(self, "_notify_busy", False):
            return
        if not telegram_notify.enabled(self._settings):
            return
        token = telegram_notify.bot_token(self._settings)
        if not token:
            return
        self._notify_busy = True
        offset = telegram_notify.update_offset(self._settings)
        accounts = telegram_notify.load_accounts(self._settings)

        def work():
            try:
                result = telegram_notify.poll_starts(token, offset, accounts, reply=True)
            except (RuntimeError, OSError) as exc:
                result = exc
            self.notify_poll_done.emit(result)

        threading.Thread(target=work, daemon=True, name="telegram-notify-poll").start()

    def _on_notify_poll_done(self, result):
        self._notify_busy = False
        if isinstance(result, Exception):
            return
        accounts, offset, pending = result
        telegram_notify.save_state(self._settings, accounts, offset=offset)
        if pending:
            self._append_log(
                f"Telegram: {len(pending)} account(s) waiting for approval "
                "in Settings → Notifications."
            )

    def _save_settings(self):
        put = self._settings.setValue
        source = self.source_edit.text().strip()
        put("source", source)
        if source:
            put("recent_urls", remember_recent(self._recent_urls(), source))
        put("dark", self._dark)
        put("theme_primary", self._primary)
        put("log_visible", not self.log_dock.isHidden())
        put("dock_state", self.saveState())
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
        if hasattr(self, "views"):
            put("views_kinds", ",".join(sorted(self.views.checked_kinds())))
            put("views_folder_group", self.views.folder_group_enabled())
            for key, path in self.views.kind_folders().items():
                put(f"views_folder_{key}", path)
        put("geometry", self.saveGeometry())
        if hasattr(self, "work_split"):
            put("work_split", self.work_split.saveState())
        if hasattr(self, "splitter"):
            put("main_split", self.splitter.saveState())
        put("header_v8", self.table.header().saveState())
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
        if getattr(self, "_app_update_timer", None):
            self._app_update_timer.stop()
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
    quiet_qt_logs()
    argv = argv if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    setup_app_font(app)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet(theme.DEFAULT_DARK))
    guard = InstanceGuard(app)
    if not guard.acquire():
        guard.ping_existing()
        return 0
    settings = gui_settings()
    from app.core.telegram_report import (
        device_id_from_settings,
        install_crash_handlers,
        report_launch,
    )

    device_id = device_id_from_settings(settings)
    install_crash_handlers(device_id=device_id)
    if QSystemTrayIcon.isSystemTrayAvailable():
        app.setQuitOnLastWindowClosed(False)
    schedule_auto_update(settings.value("auto_update", True, bool))
    window = MainWindow(settings=settings)
    guard.activate.connect(window.tray.show_window)
    window.show()
    threading.Thread(
        target=report_launch, args=(settings, device_id), daemon=True, name="telegram-launch"
    ).start()
    if settings.value("check_app_updates", True, bool):
        threading.Thread(
            target=window._run_app_update_check,
            kwargs={"prompt_update": True, "notify_uptodate": False},
            daemon=True,
        ).start()
    try:
        return app.exec()
    finally:
        guard.release()
        if getattr(window, "tray", None):
            window.tray.hide_icon()


def main():
    return run_gui()
