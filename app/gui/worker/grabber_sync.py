"""Grabber sync queue, clipboard watcher, and floating monitor."""
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


class GrabberSyncMixin:
    def _modal_open(self):
        return bool(
            getattr(self, "_in_modal_dialog", False)
            or QApplication.activeModalWidget() is not None
        )

    def _run_modal_dialog(self, action):
        """Pause background Grabber UI/timers and hide the stays-on-top tool panel while a modal dialog runs."""
        prev = getattr(self, "_in_modal_dialog", False)
        self._in_modal_dialog = True
        if getattr(self, "_grab_sync_timer", None) is not None:
            self._grab_sync_timer.stop()
        if getattr(self, "_stats_timer", None) is not None:
            self._stats_timer.stop()
        if getattr(self, "_progress_disk_timer", None) is not None:
            self._progress_disk_timer.stop()
        panel = getattr(self, "grab_panel", None)
        panel_was_visible = bool(panel is not None and not panel.isHidden())
        if panel is not None and panel_was_visible:
            panel._tick.stop()
            panel._slide.stop()
            panel.hide()
        loader = getattr(self, "extract_loader", None)
        if loader is not None and not loader.isHidden():
            loader.bar.stop()
        try:
            return action()
        finally:
            self._in_modal_dialog = prev
            if not prev:
                self._sync_stats_timer()
                self._sync_progress_disk_timer()
                if loader is not None and self._collecting and not loader.isHidden():
                    loader.bar.start()
                if panel is not None and panel_was_visible and (
                    self._collecting or self._grabber_job or panel.is_pinned()
                ):
                    panel.show()
                if self._grab_sync or getattr(self, "_grab_sync_dirty", False):
                    QTimer.singleShot(0, self._flush_grab_chunk)
                elif getattr(self, "_pending_auto_confirm", False) and self._thread is None:
                    QTimer.singleShot(0, self._apply_pending_auto_confirm)
                if self._grab_queue and self._thread is None and self._grabbing_allowed():
                    QTimer.singleShot(0, self._start_next_grab)

    @Slot(list)
    def _enqueue_grab_urls(self, urls):
        """Queue collect results and paint them in chunks so the table stays responsive."""
        if not urls:
            return
        self._grab_sync.extend(urls)
        self._grab_sync_dirty = True
        if self._modal_open() or self._grab_sync_timer.isActive():
            return
        self._flush_grab_chunk()
        if self._grab_sync:
            self._grab_sync_timer.start()

    def _flush_grab_chunk(self):
        if self._modal_open():
            self._grab_sync_timer.stop()
            return
        if not self._grab_sync:
            self._grab_sync_timer.stop()
            if self._grab_sync_dirty:
                self._grab_sync_dirty = False
                self._finish_grab_sync()
            return
        chunk = []
        while self._grab_sync and len(chunk) < GRAB_SYNC_CHUNK:
            chunk.append(self._grab_sync.popleft())
        self._insert_grab_urls(chunk, light=True)
        if self._grab_sync:
            if not self._grab_sync_timer.isActive() and not self._modal_open():
                self._grab_sync_timer.start()
            return
        self._grab_sync_timer.stop()
        self._grab_sync_dirty = False
        self._finish_grab_sync()
        if self._thread is None:
            self._apply_pending_auto_confirm()

    def _drain_grab_sync(self):
        """Paint every queued package now in one coalesced batch."""
        self._grab_sync_timer.stop()
        if self._grab_sync:
            batch = list(self._grab_sync)
            self._grab_sync.clear()
            self._insert_grab_urls(batch, light=True)
            self._grab_sync_dirty = True
        if self._grab_sync_dirty:
            self._grab_sync_dirty = False
            self._finish_grab_sync()

    def _finish_grab_sync(self):
        self.grab_table.sortByColumn(COL_INDEX, Qt.SortOrder.AscendingOrder)
        self.grab_proxy.invalidate()
        self._collapse_tree(self.grab_table)
        if self.grab_table.horizontalScrollBar() is not None:
            self.grab_table.horizontalScrollBar().setValue(0)
        self._sync_header_check()
        self._update_counter()

    def _insert_grab_urls(self, urls, light=False):
        known = self.grab_model.url_set()
        requested = []
        requested_seen = set()
        for item in urls:
            url = item.get("url") if isinstance(item, dict) else item
            if url and url not in requested_seen:
                requested_seen.add(url)
                requested.append(url)
        dupes = sum(1 for url in requested if url in known)
        expanded = []
        folders = self._kind_folders()
        kinds = None
        if hasattr(self, "views") and self.views is not None:
            kinds = self.views.checked_kinds() or {"video"}
        grouped = group_series_entries(urls, existing_urls=known)
        movie = series_folder_for_items(
            [item for item in grouped if isinstance(item, dict) and not is_series_package(item)]
        )
        movie_dir = self._movie_save_dir(movie, self._output_root()) if movie else ""
        folder_group = self._folder_group()
        for item in grouped:
            stamped = self._stamp_entry(item)
            series_key = stamped.get("series_url") or ""
            if not movie_dir and series_key:
                pkg = self.grab_model.package_reel(series_key)
                if pkg and pkg.save_dir:
                    movie_dir = pkg.save_dir
            if movie_dir and (
                is_series_package(stamped) or series_key
            ):
                stamped["save_dir"] = movie_dir
            expanded.extend(extract_package_rows(
                stamped,
                kinds=kinds,
                kind_folders=folders,
                folder_group=folder_group,
            ))
        table = self.grab_table
        table.setUpdatesEnabled(False)
        try:
            added_rows = self.grab_model.add_entries(expanded, prepend=self.grab_add_at_top)
        finally:
            table.setUpdatesEnabled(True)
        added = len(self.grab_model.url_set() - known)
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
        if self._modal_open():
            return
        panel = self.grab_panel
        readings = self._grab_readings(status)
        if _win_mod().use_grabber_notifications() and not self._grab_panel_visible():
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
        if self._modal_open():
            if getattr(self, "grab_panel", None) is not None:
                self.grab_panel._tick.stop()
            return
        if _win_mod().use_grabber_notifications() and not self._grab_panel_visible():
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
        if self._modal_open():
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
        if QApplication.activeModalWidget() is not None:
            QTimer.singleShot(400, self._start_next_grab)
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
