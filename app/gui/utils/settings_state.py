"""Settings persistence, log panel/export, and window shutdown."""
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


class SettingsStateMixin:
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
        _win_mod().QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

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
        state = get("header_v9")
        if state:
            self.table.header().restoreState(state)
            self._apply_column_modes()
        for view in (getattr(self, "table", None), getattr(self, "grab_table", None)):
            if view is not None and view.horizontalScrollBar() is not None:
                view.horizontalScrollBar().setValue(0)

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
        put("header_v9", self.table.header().saveState())
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
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._set_frame_cursor(None)
        # Stop watching the clipboard first: a closing window must not start
        # another grab while it is shutting its job down.
        if getattr(self, "_clipboard_connected", False):
            self._clipboard_connected = False
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    QGuiApplication.clipboard().dataChanged.disconnect(self._on_clipboard_changed)
                except (RuntimeError, TypeError):
                    pass
        self._grab_queue.clear()
        self._grab_close_timer.stop()
        if getattr(self, "grab_panel", None):
            self.grab_panel.hide()
        self._stats_timer.stop()
        if getattr(self, "_progress_ui_timer", None):
            self._progress_ui_timer.stop()
        if getattr(self, "_progress_disk_timer", None):
            self._progress_disk_timer.stop()
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
