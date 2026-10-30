"""Collect and download job orchestration and progress handling."""
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


class JobRunnerMixin:
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
        status = event.get("status")
        if on_grab or on_list:
            if status in (None, "downloading"):
                self._schedule_progress_ui()
            else:
                self._update_counter()
        if event.get("filepath") or status == "done":
            self._sync_output_tree(url)
        if on_list:
            if status in ("done", "failed", "cancelled") and self._thread is None:
                self._flush_store()
            else:
                self._schedule_store()
        self._sync_progress_disk_timer()

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
        _win_mod().alert(self, kind, title, "\n".join(lines), stay_on_top=True)
        telegram_notify.notify_download_done(self._settings, title, "\n".join(lines))

    def _start_collect(self):
        self.tabs.setCurrentIndex(TAB_GRABBER)
        channel, raw_url = self._channel(), self.source_edit.text().strip()
        if not raw_url:
            _win_mod().alert(self, "warning", "Missing URL", "Paste a post, channel, or playlist URL.")
            return
        if looks_shell_truncated(raw_url):
            self._append_log("URL looks truncated; adding the reels tab automatically.")
        try:
            url = normalize_source_url(raw_url)
        except ValueError as exc:
            _win_mod().alert(self, "error", "Invalid URL", str(exc))
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

    def _add_to_downloads_asked(self, _checked=False):
        """Add to downloads, then ask whether to start unless that choice is saved."""
        self._add_to_downloads(ask_autostart=True)

    def _confirm_autostart(self):
        """Yes starts the queue, No only adds. None leaves the Grabber list alone."""
        if self._settings.value("add_download_skip_confirm", False, bool):
            return bool(self.grab_autostart)
        box = _win_mod().QMessageBox(self)
        box.setWindowTitle(tr("Add to downloads"))
        box.setIconPixmap(icons.art("botty", "ask", 64))
        box.setText(tr("Start the download automatically?"))
        box.setInformativeText(tr("Yes starts the download. No only adds the links."))
        skip = QCheckBox(tr("Don't ask again"))
        box.setCheckBox(skip)
        yes = box.addButton(tr("Yes"), _win_mod().QMessageBox.ButtonRole.YesRole)
        no = box.addButton(tr("No"), _win_mod().QMessageBox.ButtonRole.NoRole)
        box.addButton(_win_mod().QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(yes)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes:
            start = True
        elif clicked is no:
            start = False
        else:
            return None
        if skip.isChecked():
            self._set_grab_autostart(start)
            self._settings.setValue("add_download_skip_confirm", True)
        return start

    def _add_to_downloads(self, ask_autostart=False):
        """Move Grabber rows into the Download queue, then open that tab."""
        self.tabs.setCurrentIndex(TAB_GRABBER)
        reels = self._selected_reels()
        if not reels:
            reels = [self.grab_model.reel_at(row) for row in range(self.grab_model.rowCount())
                      if self.grab_model.reel_at(row).checked]
        if not reels:
            reels = [self.grab_model.reel_at(row) for row in range(self.grab_model.rowCount())]
        if not reels:
            _win_mod().alert(
                self, "warning", "Nothing to add",
                "Extract a URL into the Grabber table first.",
            )
            return
        start_after = bool(self.grab_autostart)
        if ask_autostart:
            start_after = self._confirm_autostart()
            if start_after is None:
                return
        default_dir = ""
        if getattr(self, "save_path_edit", None) is not None:
            default_dir = self.save_path_edit.text().strip()
        selected_keys = {(reel.url, reel.variant or "") for reel in reels}
        # Selecting a series package row includes all of its episode children.
        selected_series = {
            (reel.series_url or reel.url)
            for reel in reels
            if is_series_package(reel) and (reel.series_url or reel.url)
        }
        if selected_series:
            for row in range(self.grab_model.rowCount()):
                child = self.grab_model.reel_at(row)
                if (child.series_url or "") in selected_series:
                    selected_keys.add((child.url, child.variant or ""))
        # Also include the parent series package row if any of its episodes are selected.
        needed_series = {
            reel.series_url
            for reel in reels
            if getattr(reel, "series_url", "")
        } | selected_series
        if needed_series:
            for row in range(self.grab_model.rowCount()):
                pkg_row = self.grab_model.reel_at(row)
                if is_series_package(pkg_row) and (pkg_row.series_url or pkg_row.url) in needed_series:
                    selected_keys.add((pkg_row.url, ""))

        selected_urls = {url for url, _variant in selected_keys}
        want_all = {url for url, variant in selected_keys if not variant}
        kinds_by_url = {}
        quality_by_url = {}
        templates = {}
        view_kinds = self.views.checked_kinds() if hasattr(self, "views") else set()
        for row in range(self.grab_model.rowCount()):
            reel = self.grab_model.reel_at(row)
            if reel.url not in selected_urls:
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
        movie = series_folder_for_items(
            [r for r in templates.values() if not is_series_package(r)]
        ) or series_folder_for_items(templates.values())
        movie_dir = self._movie_save_dir(movie, default_dir or self._output_root()) if movie else ""
        entries = []
        for url, reel in templates.items():
            base = reel.as_entry()
            base["status"] = "queued"
            base["percent"] = 0
            base["filepath"] = ""
            kinds = kinds_by_url.get(url) or set(view_kinds) or {"video"}
            base["media_kinds"] = kinds
            base["image_quality"] = quality_by_url.get(url, "")
            if movie_dir:
                base["save_dir"] = movie_dir
            elif not base.get("save_dir"):
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
        self.table.setUpdatesEnabled(False)
        self.grab_table.setUpdatesEnabled(False)
        try:
            added = self.model.add_entries(entries)
            # Keep a series package row in Grabber if it still has remaining episodes there.
            remaining_series = {
                self.grab_model.reel_at(r).series_url
                for r in range(self.grab_model.rowCount())
                if not is_series_package(self.grab_model.reel_at(r))
                and self.grab_model.reel_at(r).url not in templates
                and self.grab_model.reel_at(r).series_url
            }
            drop_urls = [
                url for url, reel in templates.items()
                if not (is_series_package(reel) and (reel.series_url or url) in remaining_series)
            ]
            self.grab_model.remove_urls(drop_urls)
        finally:
            self.table.setUpdatesEnabled(True)
            self.grab_table.setUpdatesEnabled(True)
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
        if added and start_after:
            self._start_download(ignore_checks=True)

    def _playlist_choice(self, url):
        """Ask whether a video-inside-a-playlist link means one video or the list."""
        pair = youtube_watch_with_list(url)
        if not pair:
            return url, None
        video_url, list_url = pair
        box = _win_mod().QMessageBox(self)
        box.setWindowTitle("Playlist link")
        box.setIcon(_win_mod().QMessageBox.Icon.Question)
        box.setText("This YouTube link points at a video inside a playlist.")
        box.setInformativeText("Collect only this video, or every video in the list?")
        video_btn = box.addButton("This video", _win_mod().QMessageBox.ButtonRole.AcceptRole)
        list_btn = box.addButton("Whole playlist", _win_mod().QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_win_mod().QMessageBox.StandardButton.Cancel)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setDefaultButton(video_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is video_btn:
            return video_url, False
        if clicked is list_btn:
            return list_url, True
        return None

    def _movie_save_dir(self, movie, base=""):
        """Absolute folder for a series title under the download root."""
        movie = (movie or "").strip()
        if not movie:
            return (base or "").strip()
        root = (base or "").strip() or self._output_root()
        if movie.lower() in os.path.normpath(root).lower().split(os.sep):
            return root
        return os.path.join(root, movie)

    def _expand_bilibili_seasons_in_downloads(self, urls):
        """Replace season page rows with every episode; return updated URL list."""
        seasons = [url for url in urls if is_bilibili_season_url(url)]
        if not seasons:
            return list(urls)
        speed = self._speed()
        kept = [url for url in urls if not is_bilibili_season_url(url)]
        for season_url in seasons:
            pkg = self.model.package_reel(season_url)
            prior_dir = (pkg.save_dir if pkg else "") or self._output_root()
            self._append_log(f"Expanding series into episodes: {season_url}")
            try:
                entries = list_bilibili_season_entries(
                    season_url,
                    log=self._append_log,
                    cookies_browser=speed.get("cookies_browser", ""),
                    cookies_file=speed.get("cookies_file", ""),
                )
            except Exception as exc:
                self._append_log(f"Could not expand series: {exc}")
                kept.append(season_url)
                continue
            if not entries:
                kept.append(season_url)
                continue
            entries = group_series_entries(entries)
            movie = series_folder_for_items(
                [item for item in entries if not is_series_package(item)]
            ) or series_folder_for_items([pkg] if pkg else [])
            movie_dir = self._movie_save_dir(movie, prior_dir)
            self.model.remove_urls([season_url])
            rows = []
            for entry in entries:
                data = self._stamp_entry(entry)
                data["status"] = "queued"
                data["percent"] = 0
                data["filepath"] = ""
                if movie_dir:
                    data["save_dir"] = movie_dir
                rows.append(data)
            self.model.add_entries(rows)
            kept.extend(
                entry["url"] for entry in entries
                if entry.get("url") and not is_series_package(entry)
            )
            self._append_log(
                f"Listed {sum(1 for item in entries if not is_series_package(item))} episode(s)"
                + (f" → {movie}" if movie else "")
                + "."
            )
        self._refresh_download_progress_from_disk()
        self._sync_header_check()
        self._update_counter()
        self._schedule_store()
        return kept

    def _start_download(self, ignore_checks=False):
        self.tabs.setCurrentIndex(TAB_DOWNLOAD)
        channel = self._channel()
        if not self.model.rowCount() and not self._load_saved_list(channel):
            _win_mod().alert(
                self, "warning", "Nothing to download",
                "Extract items on the Grabber tab, then Add to downloads.",
            )
            return
        selected = None if ignore_checks else (self.model.checked_urls() or None)
        urls = self.model.pending_urls(selected)
        if not urls:
            _win_mod().alert(
                self, "info", "Nothing left",
                "Checked items are already downloaded." if selected is not None
                else "Every item in the list is already downloaded.",
            )
            return
        urls = self._expand_bilibili_seasons_in_downloads(urls)
        if not urls:
            _win_mod().alert(
                self, "warning", "Nothing to download",
                "Could not list episodes for that series URL.",
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
        packages = []
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
            if pkg is not None:
                packages.append(pkg)
        movie = series_folder_for_items(packages)
        if movie and not self._settings.value("channel", "", str).strip():
            channel = movie
        self._remember_download_channel(channel)
        folders = {}
        for pkg in packages:
            dest = (pkg.save_dir or "").strip()
            if movie:
                dest = self._movie_save_dir(movie, dest or self._output_root())
            if per_link_folders:
                name = episode_leaf_name(
                    pkg.title, pkg.description, pkg.rid, series=movie,
                )
                dest = os.path.join(dest, name) if dest else name
            folders[pkg.url] = dest
            if pkg.url not in url_media_kinds:
                stored = set(pkg.media_kinds or ()) & view_kinds
                url_media_kinds[pkg.url] = stored or set(view_kinds)
            else:
                url_media_kinds[pkg.url] = set(url_media_kinds[pkg.url]) & view_kinds
                if not url_media_kinds[pkg.url]:
                    url_media_kinds[pkg.url] = set(view_kinds)
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
            "video_quality": get("video_quality", DEFAULT_VIDEO_QUALITY, str) or DEFAULT_VIDEO_QUALITY,
            "gpu_accel": get("gpu_accel", sysinfo.DEFAULT_GPU_ACCEL, str) or sysinfo.DEFAULT_GPU_ACCEL,
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
        self._sync_progress_disk_timer()
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
            self.save_path_edit, self.save_path_btn,
        ):
            widget.setEnabled(idle)
        for action in (self.act_collect, self.act_download, self.act_add):
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
            self._refresh_download_progress_from_disk()
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
        if not self._modal_open():
            self._drain_grab_sync()
        self._collecting = False
        if not keep_loader:
            self._hide_extract_loader()
        self.status.setText(message or "Done")
        self.counter.setToolTip(message or "Done")
        if not self._modal_open():
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
        if not self._pending_auto_confirm or self._modal_open():
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
        if not self._modal_open():
            self._drain_grab_sync()
            self._apply_pending_auto_confirm()
