"""Dark/light theme, accent colors, locale translation, and pills."""
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


class ThemeLocaleMixin:
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

    def _open_settings(self):
        dialog = SettingsDialog(self._settings, self)
        if self._run_modal_dialog(dialog.exec):
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
