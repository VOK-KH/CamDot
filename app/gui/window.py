"""Main window orchestrator composing UI, worker, and utility mixins."""
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

from app.gui.ui import (
    TableColumnsMixin,
    ThemeLocaleMixin,
    WindowChromeMixin,
    WindowMenusMixin,
)
from app.gui.utils import (
    RowActionsMixin,
    SettingsStateMixin,
    TreeStateMixin,
)
from app.gui.worker import (
    AppUpdateMixin,
    GrabberSyncMixin,
    JobRunnerMixin,
)


class MainWindow(
    WindowChromeMixin,
    TableColumnsMixin,
    WindowMenusMixin,
    ThemeLocaleMixin,
    TreeStateMixin,
    RowActionsMixin,
    SettingsStateMixin,
    GrabberSyncMixin,
    JobRunnerMixin,
    AppUpdateMixin,
    QMainWindow,
):
    tools_checked = Signal(str)
    gpu_detected = Signal(str, str)
    speedtest_ready = Signal(object)
    app_update_found = Signal(object)
    app_update_uptodate = Signal()
    notify_poll_done = Signal(object)
    app_update_downloaded = Signal(str, object)
    open_url = Signal(str)

    def __init__(self, dark=theme.DEFAULT_DARK, settings=None):
        super().__init__()
        self._initializing_ui = True
        self.tools_checked.connect(self._append_log)
        self.open_url.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.gpu_detected.connect(self._on_gpu_detected)
        self.speedtest_ready.connect(self._on_speedtest_ready)
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
        self._grab_sync_dirty = False
        # Before tables exist — modelReset during build can call expand restore.
        self._download_expanded_keys = set()
        self._grab_expanded_keys = set()

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
        self._progress_ui_timer = QTimer(self)
        self._progress_ui_timer.setSingleShot(True)
        self._progress_ui_timer.setInterval(250)
        self._progress_ui_timer.timeout.connect(self._refresh_progress_ui)
        self._progress_disk_timer = QTimer(self)
        self._progress_disk_timer.setInterval(2000)
        self._progress_disk_timer.timeout.connect(self._refresh_download_progress_from_disk)
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
        self._initializing_ui = False
        self._auto_load_download_list()
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
        self._clipboard_connected = True
        self.tray = TrayController(self)
        self._sync_close_tooltip()
        # The panels reach the window edge, so the resize band has to see the
        # presses they would otherwise swallow.
        if self._custom_chrome:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)

    # Declare QObject slots directly on MainWindow (QMainWindow subclass) so
    # PySide6 registers them on MainWindow's QMetaObject with main-thread
    # affinity (QueuedConnection from worker QThreads, never DirectConnection).
    @Slot(str)
    def _append_log(self, text):
        return SettingsStateMixin._append_log(self, text)

    @Slot(list)
    def _enqueue_grab_urls(self, urls):
        return GrabberSyncMixin._enqueue_grab_urls(self, urls)

    @Slot(list)
    def set_urls(self, urls):
        return RowActionsMixin.set_urls(self, urls)

    @Slot(str, dict)
    def _on_progress(self, url, event):
        return JobRunnerMixin._on_progress(self, url, event)

    @Slot()
    def _on_waiting_login(self):
        return JobRunnerMixin._on_waiting_login(self)

    @Slot(str)
    def _on_finished(self, message):
        return JobRunnerMixin._on_finished(self, message)

    @Slot()
    def _on_thread_finished(self):
        return JobRunnerMixin._on_thread_finished(self)

    @Slot(str, str)
    def _on_gpu_detected(self, label, tooltip):
        return WindowMenusMixin._on_gpu_detected(self, label, tooltip)

    @Slot(object)
    def _on_speedtest_ready(self, result):
        return WindowMenusMixin._on_speedtest_ready(self, result)

    @Slot(object)
    def _prompt_app_update(self, info):
        return AppUpdateMixin._prompt_app_update(self, info)

    @Slot()
    def _show_app_uptodate(self):
        return AppUpdateMixin._show_app_uptodate(self)

    @Slot(str, object)
    def _prompt_restart_for_update(self, installer_path, info):
        return AppUpdateMixin._prompt_restart_for_update(self, installer_path, info)

    @Slot(object)
    def _on_notify_poll_done(self, result):
        return AppUpdateMixin._on_notify_poll_done(self, result)

    @Slot()
    def _on_clipboard_changed(self):
        return GrabberSyncMixin._on_clipboard_changed(self)


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
