"""Menu bar, gear options menu, status bar, and context menus."""
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


class WindowMenusMixin:
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
        quality_box = QComboBox()
        for key, label in VIDEO_QUALITY_CHOICES:
            quality_box.addItem(label, key)
        saved_q = get("video_quality", DEFAULT_VIDEO_QUALITY, str) or DEFAULT_VIDEO_QUALITY
        quality_box.setCurrentIndex(max(quality_box.findData(saved_q), 0))
        quality_box.setToolTip("Default video download quality")
        quality_box.currentIndexChanged.connect(
            lambda _idx=-1: self._settings.setValue(
                "video_quality", quality_box.currentData() or DEFAULT_VIDEO_QUALITY
            )
        )
        self._add_menu_labeled_widget(menu, "Video quality", quality_box)

        gpu_box = QComboBox()
        for key, label in sysinfo.GPU_ACCEL_MODES:
            gpu_box.addItem(label, key)
        saved_gpu = get("gpu_accel", sysinfo.DEFAULT_GPU_ACCEL, str) or sysinfo.DEFAULT_GPU_ACCEL
        gpu_box.setCurrentIndex(max(gpu_box.findData(saved_gpu), 0))
        gpu_box.setToolTip(sysinfo.hardware_profile_summary())
        gpu_box.currentIndexChanged.connect(
            lambda _idx=-1: self._settings.setValue(
                "gpu_accel", gpu_box.currentData() or sysinfo.DEFAULT_GPU_ACCEL
            )
        )
        self._add_menu_labeled_widget(menu, "GPU acceleration", gpu_box)

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

        rec_w, rec_f = sysinfo.recommended_concurrency()
        auto_hw = menu.addAction(tr(f"Auto-tune for hardware ({rec_w}×{rec_f})"))
        auto_hw.setToolTip(sysinfo.hardware_profile_summary())

        def _apply_hw():
            workers.setValue(rec_w)
            chunks.setValue(rec_f)
            self._settings.setValue("workers", rec_w)
            self._settings.setValue("fragments", rec_f)

        auto_hw.triggered.connect(lambda _=False: _apply_hw())

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

    def _confirm_cleanup(self, action, count, remaining, grabber=False):
        if self._settings.value("cleanup_skip_confirm", False, bool):
            return True
        box = _win_mod().QMessageBox(self)
        box.setWindowTitle("Are you sure?")
        box.setText(
            f"Do you really want to perform this clean up action:\n{action}?"
        )
        box.setInformativeText(
            f"Delete {count} link(s) — {remaining} link(s) remaining."
        )
        art_name = "remove" if grabber else "robot_del"
        box.setIconPixmap(icons.art("botty", art_name, 64))
        skip = QCheckBox("Don't show this again")
        box.setCheckBox(skip)
        cont = box.addButton("Continue", _win_mod().QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", _win_mod().QMessageBox.ButtonRole.RejectRole)
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
        if not self._confirm_cleanup(
            action, len(reels), remaining, grabber=model is self.grab_model,
        ):
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
            _win_mod().alert(
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
        _win_mod().threading.Thread(target=self._detect_gpu, daemon=True).start()
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
        if self._modal_open():
            return
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
            file_menu, "Add to down&loads", self._add_to_downloads_asked, "Ctrl+Shift+D",
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

    def _context_action(self, menu, text, slot, icon=""):
        color = self._icon_color()
        label = tr(text)
        action = menu.addAction(icons.icon(icon, color), label) if icon else menu.addAction(label)
        if icon:
            action.setProperty("iconName", icon)
        action.triggered.connect(slot)
        return action

    def _context_menu_for(self, table):
        """Build the table context menu without showing it (for tests and exec)."""
        grabber = table is self.grab_table
        model = self.grab_model if grabber else self.model
        selected = bool(table.selectionModel() and table.selectionModel().selectedRows())
        menu = QMenu(self)
        if selected:
            if grabber:
                self._context_action(
                    menu, "Add to downloads", self._add_to_downloads_asked, "download")
                menu.addMenu(self._variant_menu())
            else:
                self._context_action(
                    menu, "Start selected", self._start_selected, "play")
            folder_indexes = self._selected_folder_view_indexes(table)
            if folder_indexes:
                menu.addSeparator()
                any_collapsed = any(not table.isExpanded(idx) for idx in folder_indexes)
                any_expanded = any(table.isExpanded(idx) for idx in folder_indexes)
                if any_collapsed:
                    self._context_action(
                        menu, "Expand folder",
                        lambda _=False, t=table: self._set_selected_folders_expanded(True, t),
                        "folder",
                    )
                if any_expanded:
                    self._context_action(
                        menu, "Collapse folder",
                        lambda _=False, t=table: self._set_selected_folders_expanded(False, t),
                        "folder",
                    )
                self._context_action(
                    menu, "Expand all packages",
                    lambda _=False: self._set_active_packages_expanded(True),
                )
                self._context_action(
                    menu, "Collapse all packages",
                    lambda _=False: self._set_active_packages_expanded(False),
                )
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
            elif folder_indexes:
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

    def _show_supported_sites(self):
        self._run_modal_dialog(lambda: PlatformsDialog(self).exec())

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
        if self._run_modal_dialog(dialog.exec):
            self._append_log("Feedback sent. Thank you.")

    def _show_about(self):
        versions = runtime_versions()
        _win_mod().QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"{APP_NAME} {__version__}\n\n"
            f"Engine: {versions['yt_dlp'] or 'missing'}\n"
            f"FFmpeg: {versions['ffmpeg'] or 'missing'}\n"
            f"Downloads: {self._output_root()}",
        )
