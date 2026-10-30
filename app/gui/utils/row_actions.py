"""Row selection, clipboard copy, file reveal/delete, and list I/O."""
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


class RowActionsMixin:
    def set_urls(self, urls):
        self.model.set_urls([self._stamp_entry(item) for item in urls])
        if self.model.rowCount():
            self.model.reshape_folder_layout(
                self._folder_group(), self._kind_folders(),
            )
        self._last_views_layout = self._views_layout_key()
        if self._folder_group():
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
        if model is self.grab_model:
            action = "Delete Selected Links" if self._selected_reels() else "Delete All Links"
            remaining = max(0, model.rowCount() - len(reels))
            if not self._confirm_cleanup(action, len(reels), remaining, grabber=True):
                return
        else:
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
        return dialog.text() if self._run_modal_dialog(dialog.exec) else None

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
            _win_mod().alert(
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

    def _selected_reels(self):
        model, _proxy, table = self._pack()
        rows = sorted({
            self._map_index_to_source(table, index).row()
            for index in table.selectionModel().selectedRows()
        })
        return [model.reel_at(row) for row in rows]

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

    def _start_selected(self):
        reels = self._selected_reels()
        self.tabs.setCurrentIndex(TAB_DOWNLOAD)
        if reels:
            all_rows = list(range(self.model.rowCount()))
            self.model.set_checked_rows(all_rows, False)
            selected_rows = [
                self._map_index_to_source(self.table, index).row()
                for index in self.table.selectionModel().selectedRows()
            ]
            self.model.set_checked_rows(selected_rows, True)
            self._sync_header_check()
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

    def _reveal(self, reel):
        folder = self._folder_for_reel(reel)
        files = store.list_output_files(folder, reel.rid, reel.filepath)
        if files:
            _win_mod().QDesktopServices.openUrl(QUrl.fromLocalFile(files[0]))
            return
        self._open_folder_path(folder)

    def _open_directory(self, reel):
        """Open the row's save folder, or the finished file's parent."""
        folder = self._folder_for_reel(reel)
        files = store.list_output_files(folder, reel.rid, reel.filepath)
        if files:
            parent = os.path.dirname(os.path.abspath(files[0]))
            if os.path.isdir(parent):
                _win_mod().QDesktopServices.openUrl(QUrl.fromLocalFile(parent))
                return
        self._open_folder_path(folder)

    def _open_folder_path(self, folder):
        os.makedirs(folder, exist_ok=True)
        _win_mod().QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _files_for_reels(self, reels):
        model, _proxy, _table = self._pack()
        expanded_reels = list(reels)
        series_keys = {
            (reel.series_url or reel.url)
            for reel in reels
            if is_series_package(reel) and (reel.series_url or reel.url)
        }
        if series_keys and model is not None:
            seen_ids = {id(r) for r in expanded_reels}
            for row in range(model.rowCount()):
                child = model.reel_at(row)
                if (child.series_url or "") in series_keys and id(child) not in seen_ids:
                    seen_ids.add(id(child))
                    expanded_reels.append(child)
        files, rids = [], []
        seen = set()
        for reel in expanded_reels:
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
        answer = _win_mod().alert(
            self, "question", title,
            f"{text}\n\n{names}{extra}",
            _win_mod().QMessageBox.StandardButton.Yes | _win_mod().QMessageBox.StandardButton.No,
            _win_mod().QMessageBox.StandardButton.No,
        )
        if answer != _win_mod().QMessageBox.StandardButton.Yes:
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

    def _copy_urls(self):
        model, _proxy, _table = self._pack()
        reels = self._selected_reels() or []
        urls = []
        seen = set()
        for reel in reels:
            if is_series_package(reel) and model is not None:
                children = model._series_episode_rows(reel.series_url or reel.url)
                if children:
                    for child in children:
                        if child.url and child.url not in seen:
                            seen.add(child.url)
                            urls.append(child.url)
                    continue
            if reel.url and reel.url not in seen:
                seen.add(reel.url)
                urls.append(reel.url)
        if urls:
            QGuiApplication.clipboard().setText("\n".join(urls))

    def _copy_captions(self):
        text = "\n".join(
            r.description or r.title
            for r in self._selected_reels() if r.description or r.title
        )
        if text:
            QGuiApplication.clipboard().setText(text)

    def _open_selected(self):
        for reel in self._selected_reels()[:5]:
            _win_mod().QDesktopServices.openUrl(QUrl(reel.url))

    def _remove_all(self):
        model, _proxy, _table = self._pack()
        reels = [model.reel_at(row) for row in range(model.rowCount())]
        if not reels:
            return
        if model is self.grab_model:
            if not self._confirm_cleanup(
                "Delete All Links", len(reels), 0, grabber=True,
            ):
                return
            removed = model.remove_urls([reel.url for reel in reels])
            if removed:
                self._append_log(f"Removed {removed} item(s) from the list.")
            self._sync_header_check()
            self._update_counter()
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
        _win_mod().QDesktopServices.openUrl(QUrl.fromLocalFile(path))

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
            _win_mod().alert(self, "warning", "Import failed", "The file is not a valid list.")
            return
        entries = [item for item in payload if isinstance(item, dict) and item.get("url")]
        if not entries:
            _win_mod().alert(self, "warning", "Import failed", "No URLs were found in the file.")
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
            _win_mod().alert(self, "info", "Nothing to retry", "There are no failed items in the list.")
            return
        self._append_log(f"Requeued {count} failed item(s).")
        self._update_counter()

    def _open_folder(self):
        path = os.path.abspath(os.path.join(self._output_root(), self._channel()))
        os.makedirs(path, exist_ok=True)
        _win_mod().QDesktopServices.openUrl(QUrl.fromLocalFile(path))
