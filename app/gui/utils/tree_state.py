"""Tree expansion/scroll preservation and disk progress sync."""
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


class TreeStateMixin:
    def _expanded_keys_store(self, table):
        if table is getattr(self, "grab_table", None):
            if not hasattr(self, "_grab_expanded_keys"):
                self._grab_expanded_keys = set()
            return self._grab_expanded_keys
        if not hasattr(self, "_download_expanded_keys"):
            self._download_expanded_keys = set()
        return self._download_expanded_keys

    def _collapse_tree(self, table):
        """Keep package folders collapsed; flat single-file rows stay as-is."""
        if table is None:
            return
        self._expanded_keys_store(table).clear()
        table.collapseAll()

    def _package_key_for_index(self, table, index):
        if table is None or not index.isValid():
            return ""
        source = self._map_index_to_source(table, index)
        if not source.isValid():
            return ""
        reel = source.model().reel_at(source.row())
        return reel.series_url or reel.url or ""

    def _set_tree_expand_frozen(self, table, frozen):
        if table is not None:
            table.setProperty("camdot_expand_frozen", bool(frozen))

    def _tree_expand_frozen(self, table):
        return bool(table is not None and table.property("camdot_expand_frozen"))

    def _capture_tree_scroll(self, table):
        if table is None:
            return
        vbar = table.verticalScrollBar()
        hbar = table.horizontalScrollBar()
        table.setProperty("camdot_scroll_v", vbar.value() if vbar else 0)
        table.setProperty("camdot_scroll_h", hbar.value() if hbar else 0)

    def _restore_tree_scroll(self, table):
        if table is None:
            return
        v = table.property("camdot_scroll_v")
        h = table.property("camdot_scroll_h")
        vbar = table.verticalScrollBar()
        hbar = table.horizontalScrollBar()
        if vbar is not None and v is not None:
            vbar.setValue(int(v))
        if hbar is not None and h is not None:
            hbar.setValue(int(h))

    def _on_tree_about_to_reset(self, table):
        self._capture_tree_scroll(table)
        self._set_tree_expand_frozen(table, True)

    def _remember_tree_expand(self, table, index, expanded):
        # Ignore expand/collapse churn while the tree model is resetting.
        if self._tree_expand_frozen(table):
            return
        key = self._package_key_for_index(table, index)
        if not key:
            return
        store = self._expanded_keys_store(table)
        if expanded:
            store.add(key)
        else:
            store.discard(key)

    def _schedule_restore_tree_expansion(self, table):
        """After a tree model reset, restore expand state and scroll position."""
        if table is None:
            return
        keys = set(self._expanded_keys_store(table))

        def restore():
            try:
                if keys:
                    self._restore_expanded_package_keys(table, keys)
                self._restore_tree_scroll(table)
            finally:
                self._set_tree_expand_frozen(table, False)

        QTimer.singleShot(0, restore)

    def _expanded_package_keys(self, table):
        """Series/package URLs currently expanded, plus remembered keys across rebuilds."""
        keys = set(self._expanded_keys_store(table))
        if table is None or table.model() is None:
            return keys
        model = table.model()

        def walk(parent):
            for row in range(model.rowCount(parent)):
                index = model.index(row, 0, parent)
                if not index.isValid():
                    continue
                if table.isExpanded(index):
                    key = self._package_key_for_index(table, index)
                    if key:
                        keys.add(key)
                if model.hasChildren(index):
                    walk(index)

        walk(QModelIndex())
        return keys

    def _restore_expanded_package_keys(self, table, keys):
        """Re-expand movie folders after a background model/tree refresh."""
        if table is None or table.model() is None or not keys:
            return
        model = table.model()
        remembered = self._expanded_keys_store(table)
        remembered.update(keys)

        def walk(parent):
            for row in range(model.rowCount(parent)):
                index = model.index(row, 0, parent)
                if not index.isValid():
                    continue
                source = self._map_index_to_source(table, index)
                if source.isValid():
                    reel = source.model().reel_at(source.row())
                    key = reel.series_url or reel.url
                    if key in keys and (is_series_package(reel) or model.hasChildren(index)):
                        table.expand(index)
                if model.hasChildren(index):
                    walk(index)

        walk(QModelIndex())

    def _with_tree_expansion(self, table, action):
        """Run `action` without losing expand state or scroll position."""
        keys = self._expanded_package_keys(table)
        self._capture_tree_scroll(table)
        try:
            return action()
        finally:
            if keys:
                self._expanded_keys_store(table).update(keys)

            def restore():
                if keys:
                    self._restore_expanded_package_keys(table, keys)
                self._restore_tree_scroll(table)

            QTimer.singleShot(0, restore)

    def _set_grab_packages_expanded(self, expanded):
        self.grab_model.set_all_expanded(expanded)
        if expanded:
            self.grab_table.expandAll()
        else:
            self._collapse_tree(self.grab_table)

    def _set_active_packages_expanded(self, expanded):
        model, _proxy, table = self._pack()
        if model is None or table is None:
            return
        model.set_all_expanded(expanded)
        if expanded:
            table.expandAll()
        else:
            self._collapse_tree(table)

    def _selected_folder_view_indexes(self, table=None):
        table = table if table is not None else self._pack()[2]
        if table is None or table.model() is None or table.selectionModel() is None:
            return []
        tree_model = table.model()
        found = []
        seen = set()
        for idx in table.selectionModel().selectedRows():
            row0 = idx.siblingAtColumn(0)
            target = row0 if tree_model.hasChildren(row0) else row0.parent()
            if target.isValid() and tree_model.hasChildren(target):
                key = (target.row(), target.internalId())
                if key not in seen:
                    seen.add(key)
                    found.append(target)
        return found

    def _set_selected_folders_expanded(self, expanded=None, table=None):
        table = table if table is not None else self._pack()[2]
        for idx in self._selected_folder_view_indexes(table):
            state = (not table.isExpanded(idx)) if expanded is None else bool(expanded)
            table.setExpanded(idx, state)

    def _sync_output_tree(self, url):
        """Show the save folder as the parent and files in that folder as children."""
        folder_group = self._folder_group()
        for model, table in ((self.model, self.table), (self.grab_model, self.grab_table)):
            reel = model.package_reel(url)
            if reel is None or is_series_package(reel):
                continue
            folder = self._folder_for_reel(reel)
            # Fast path when not grouping by folder and the single output file is already known.
            if (
                not folder_group
                and reel.filepath
                and not reel.filepath.endswith((".part", ".ytdl"))
                and os.path.isfile(reel.filepath)
            ):
                if reel.total and (reel.duration or reel.quality):
                    continue
                raw = [reel.filepath]
            else:
                raw = [
                    path for path in store.list_output_files(folder, reel.rid, reel.filepath)
                    if os.path.isfile(path)
                    and not path.endswith((".part", ".ytdl"))
                ]
            if not raw:
                continue

            def _apply():
                # Model reset already rebuilds the tree; skip proxy.invalidate
                # so background progress does not thrash scroll.
                model.attach_output_files(
                    url, folder, raw, expand=False, folder_group=folder_group,
                )

            # Never collapseAll here — background progress must keep movie folders open.
            self._with_tree_expansion(table, _apply)

    def _schedule_store(self):
        if self._restoring_list or (self._collecting and not self.model.rowCount()):
            return
        self._store_timer.start()

    def _schedule_progress_ui(self):
        """Throttle overview/counter refresh while percent ticks arrive."""
        timer = getattr(self, "_progress_ui_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()

    def _refresh_progress_ui(self):
        self._update_counter()

    def _sync_progress_disk_timer(self):
        """Poll disk for finished/.part progress when idle on the Download tab."""
        timer = getattr(self, "_progress_disk_timer", None)
        if timer is None:
            return
        on_download = (
            hasattr(self, "tabs") and self.tabs.currentIndex() == TAB_DOWNLOAD
        )
        job_busy = (
            self._thread is not None
            and not self._collecting
            and not getattr(self, "_grabber_job", False)
        )
        if on_download and self.model.rowCount() and not job_busy:
            if not timer.isActive():
                timer.start()
        else:
            timer.stop()

    def _remember_download_channel(self, channel):
        channel = (channel or "").strip()
        if channel:
            self._settings.setValue("last_download_channel", channel)

    def _auto_load_download_list(self):
        """Load the last download queue and refresh done/.part progress from disk."""
        if self.model.rowCount():
            self._refresh_download_progress_from_disk()
            return True
        candidates = []
        for name in (
            self._channel(),
            self._settings.value("last_download_channel", "", str),
        ):
            name = (name or "").strip()
            if name and name not in candidates:
                candidates.append(name)
        for name in candidates:
            if self._load_saved_list(name):
                return True
        return False

    def _refresh_download_progress_from_disk(self):
        """Re-read finished videos and .part sizes into the Download table."""
        if not self.model.rowCount() or getattr(self, "_restoring_list", False):
            return False
        if QApplication.activeModalWidget() is not None:
            return False
        entries = []
        for url in self.model.urls():
            pkg = self.model.package_reel(url)
            if pkg is None or pkg.variant or is_series_package(pkg):
                continue
            # Already complete with file size & metadata on disk -> skip re-scanning.
            if (
                pkg.status == "done"
                and pkg.filepath
                and not pkg.filepath.endswith((".part", ".ytdl"))
                and pkg.total
                and (pkg.duration or pkg.quality)
                and os.path.isfile(pkg.filepath)
            ):
                continue
            entries.append(pkg.as_entry())
        if not entries:
            return False
        root = self._output_root()
        channel = (
            self._settings.value("last_download_channel", "", str).strip()
            or self._channel()
        )
        reconciled = store.reconcile_entries(
            entries,
            root,
            store.archive_path(root, channel),
        )
        job_busy = (
            self._thread is not None
            and not self._collecting
            and not getattr(self, "_grabber_job", False)
        )
        changed = False
        series_touched = set()
        for item in reconciled:
            url = item.get("url") or ""
            pkg = self.model.package_reel(url)
            if pkg is None:
                continue
            if is_series_package(pkg):
                # Root % / status are computed from episodes; don't overwrite from disk.
                series_touched.add(pkg.series_url or pkg.url)
                continue
            if item.get("save_dir") and item["save_dir"] != pkg.save_dir:
                self.model.update_reel(url, save_dir=item["save_dir"], match_variant="")
            if job_busy and pkg.status == "downloading" and item.get("status") != "done":
                if item.get("filepath") and item["filepath"] != pkg.filepath:
                    self.model.apply_event(url, {"filepath": item["filepath"]})
                    changed = True
                continue
            event = {
                "status": item.get("status") or "queued",
                "percent": item.get("percent"),
                "id": item.get("id"),
            }
            if item.get("filepath"):
                event["filepath"] = item["filepath"]
            if item.get("total"):
                event["total"] = item["total"]
            if item.get("duration"):
                event["duration"] = item["duration"]
            if item.get("quality"):
                event["quality"] = item["quality"]
            before = (pkg.status, pkg.percent, pkg.filepath, pkg.total, pkg.duration, pkg.quality)
            if self.model.apply_event(url, event):
                after_pkg = self.model.package_reel(url)
                after = (
                    after_pkg.status,
                    after_pkg.percent,
                    after_pkg.filepath,
                    after_pkg.total,
                    after_pkg.duration,
                    after_pkg.quality,
                ) if after_pkg else before
                if after != before:
                    changed = True
                    if event["status"] == "done":
                        self._sync_output_tree(url)
                    if pkg.series_url:
                        series_touched.add(pkg.series_url)
        for series_url in series_touched:
            self.model._touch_series_package(series_url)
        if changed or series_touched:
            self._update_counter()
            if changed:
                self._schedule_store()
        self._sync_progress_disk_timer()
        return changed

    def _flush_store(self):
        self._store_timer.stop()
        if self._restoring_list or (self._collecting and not self.model.rowCount()):
            return
        channel = (
            self._settings.value("last_download_channel", "", str).strip()
            or self._channel()
        )
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
        # Search the whole download root (movie folders + flat files), not only
        # output_root/channel — series episodes often land under the title folder.
        entries = store.reconcile_entries(
            entries,
            root,
            store.archive_path(root, channel),
        )
        self._restoring_list = True
        try:
            self.set_urls(entries)
        finally:
            self._restoring_list = False
        self._remember_download_channel(channel)
        self._schedule_store()
        done = sum(1 for item in entries if item.get("status") == "done")
        pending = len(entries) - done
        self._append_log(
            f"Loaded {len(entries)} item(s)"
            + (f" — {done} done, {pending} remaining." if done else ".")
        )
        self._sync_progress_disk_timer()
        return True
