"""Window layout, frameless chrome, pages, and toolbar."""
import json
import os
import sys
import threading
import time
from collections import deque

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QModelIndex,
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
from app.core.collect import (
    cookies_from_browser_value,
    list_bilibili_season_entries,
    write_entries_csv,
)
from app.core.cookies import prepare_cookies_file
from app.core.download import (
    ALL_MEDIA_KINDS, DEFAULT_FRAGMENTS, DEFAULT_VIDEO_QUALITY, DEFAULT_WORKERS,
    OUTPUT_TEMPLATE, VIDEO_QUALITY_CHOICES, episode_leaf_name, group_series_entries,
    is_series_package, read_urls, resolve_filename_template, series_folder_for_items,
    source_folder_name, tiktok_dateafter,
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
    is_bilibili_season_url,
    looks_shell_truncated,
    normalize_source_url,
    youtube_watch_with_list,
)


def _win_mod():
    from app.gui import window as _w
    return _w


class WindowChromeMixin:
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
            self._add_to_downloads_asked)
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
        self._sync_progress_disk_timer()
        if on_list and not getattr(self, "_initializing_ui", False):
            if not self.model.rowCount():
                QTimer.singleShot(0, self._auto_load_download_list)
            else:
                QTimer.singleShot(0, self._refresh_download_progress_from_disk)

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

    _WATCHED_EVENTS = frozenset({
        QEvent.Type.MouseMove,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.WindowDeactivate,
    })

    def eventFilter(self, watched, event):
        """Resize from the window's outer pixels; drag it by the menu strip."""
        if not self._custom_chrome or event.type() not in self._WATCHED_EVENTS:
            return False
        if self._frame_event(watched, event):
            return True
        if watched is not self.menu_bar or not self._on_menu_gap(event):
            return False
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
        return False

    def _on_menu_gap(self, event):
        """True for mouse events on the strip itself rather than on a menu title."""
        if not isinstance(event, QMouseEvent):
            return False
        return self.menu_bar.actionAt(event.position().toPoint()) is None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_extract_loader()
