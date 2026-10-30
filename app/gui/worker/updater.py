"""GitHub app updates, runtime tool updates, and Telegram polling."""
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


class AppUpdateMixin:
    def _check_tool_updates(self):
        self._append_log("Checking download tools for updates…")
        _win_mod().threading.Thread(target=self._run_tool_update, daemon=True).start()

    def _check_app_updates(self):
        self._append_log(f"Checking GitHub for {APP_NAME} updates…")
        _win_mod().threading.Thread(
            target=self._run_app_update_check,
            kwargs={"prompt_update": True, "notify_uptodate": True},
            daemon=True,
            name="github-update-check",
        ).start()

    def _poll_github_app_update(self):
        if not self._settings.value("check_app_updates", True, bool):
            return
        _win_mod().threading.Thread(
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
        info = _win_mod().check_for_update()
        if not info:
            if notify_uptodate:
                self.app_update_uptodate.emit()
            return
        self.tools_checked.emit(format_update_message(info))
        if prompt_update and should_offer_update(info, self._settings):
            self.app_update_found.emit(info)

    @Slot()
    def _show_app_uptodate(self):
        _win_mod().alert(
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
        clicked = _win_mod().alert(
            self,
            "question",
            "Update available",
            f"{format_update_prompt(info)}{extra}",
            _win_mod().QMessageBox.StandardButton.Yes
            | _win_mod().QMessageBox.StandardButton.No
            | _win_mod().QMessageBox.StandardButton.Ignore,
            _win_mod().QMessageBox.StandardButton.Yes,
        )
        latest = info.get("latest", "")
        if clicked == _win_mod().QMessageBox.StandardButton.Yes:
            if can_install:
                self._append_log(f"Downloading {tag} from GitHub…")
                _win_mod().threading.Thread(
                    target=self._download_app_update,
                    args=(info,),
                    daemon=True,
                    name="github-update-download",
                ).start()
            else:
                url = info.get("page_url") or info.get("download_url")
                if url:
                    _win_mod().QDesktopServices.openUrl(QUrl(url))
        elif clicked == _win_mod().QMessageBox.StandardButton.Ignore:
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
        clicked = _win_mod().alert(
            self,
            "question",
            "Restart to finish update",
            f"{APP_NAME} {tag} is downloaded.\n\n"
            "Close CamDot now and install the new version? "
            "Setup will reopen the app when it finishes.",
            _win_mod().QMessageBox.StandardButton.Yes | _win_mod().QMessageBox.StandardButton.No,
            _win_mod().QMessageBox.StandardButton.Yes,
        )
        if clicked != _win_mod().QMessageBox.StandardButton.Yes:
            self._append_log(f"Installer saved to {path}")
            return
        if not launch_installer(path):
            self._append_log(f"Could not start installer: {path}")
            return
        self._append_log(f"Installing {os.path.basename(path)}…")
        self._quit_application()

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

        _win_mod().threading.Thread(target=work, daemon=True, name="telegram-notify-poll").start()

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
