"""Tree tables, columns, overview, properties, and views filter."""
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


class _ReelTreeView(QTreeView):
    """Tree table that never auto-scrolls horizontally away from the Name column."""

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible):
        hbar = self.horizontalScrollBar()
        keep_h = hbar.value() if hbar is not None else 0
        super().scrollTo(index, hint)
        if hbar is not None and hbar.value() != keep_h:
            hbar.setValue(keep_h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.indexAt(event.position().toPoint())
            if idx.isValid() and idx.column() == COL_ICON:
                row0 = idx.siblingAtColumn(0)
                if self.model() is not None and self.model().hasChildren(row0):
                    self.setExpanded(row0, not self.isExpanded(row0))
                    event.accept()
                    return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.indexAt(event.position().toPoint())
            if idx.isValid():
                row0 = idx.siblingAtColumn(0)
                if self.model() is not None and self.model().hasChildren(row0):
                    self.setExpanded(row0, not self.isExpanded(row0))
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)


class TableColumnsMixin:
    def _pack(self):
        """The list the current tab is editing: download queue or Grabber."""
        grabber = (
            getattr(self, "tabs", None) is not None
            and self.tabs.currentIndex() == TAB_GRABBER
            and getattr(self, "grab_table", None) is not None
        )
        if grabber:
            return self.grab_model, self.grab_proxy, self.grab_table
        return self.model, self.proxy, getattr(self, "table", None)

    def _sync_header_check(self, *args):
        # Defer until the model has finished resetting; querying it from a
        # reset/layout slot can stall the Qt event loop.
        if getattr(self, "_header_sync_queued", False):
            return
        self._header_sync_queued = True
        QTimer.singleShot(0, self._flush_header_check)

    def _flush_header_check(self):
        self._header_sync_queued = False
        model, _proxy, table = self._pack()
        if table is None:
            return
        header = table.header()
        if isinstance(header, CheckHeaderView):
            header.set_check_state(model.check_state_for_rows(self._visible_source_rows()))

    def _tree_for(self, table):
        if table is getattr(self, "grab_table", None):
            return getattr(self, "grab_tree", None)
        if table is getattr(self, "table", None):
            return getattr(self, "download_tree", None)
        return None

    def _map_index_to_source(self, table, index):
        tree = self._tree_for(table)
        if tree is not None and index.model() is tree:
            index = tree.mapToSource(index)
        filter_proxy = self.grab_proxy if table is getattr(self, "grab_table", None) else self.proxy
        return filter_proxy.mapToSource(index)

    def _map_source_to_view(self, table, source_index):
        filter_proxy = self.grab_proxy if table is getattr(self, "grab_table", None) else self.proxy
        mid = filter_proxy.mapFromSource(source_index)
        tree = self._tree_for(table)
        if tree is not None:
            return tree.mapFromSource(mid)
        return mid

    def _make_table(self, proxy, hidden, empty_message="No items"):
        tree = ReelTreeProxy(self)
        proxy.set_tree_mode(True)
        tree.setSourceModel(proxy)
        if proxy is self.proxy:
            self.download_tree = tree
        else:
            self.grab_tree = tree

        table = _ReelTreeView()
        table.setModel(tree)
        table.setTreePosition(COL_TITLE)
        table.setItemDelegate(TextRowDelegate(table))
        table.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(table))
        table.setItemDelegateForColumn(COL_HOST, HosterDelegate(table))
        variant_delegate = VariantDelegate(table)
        variant_delegate.quality_chosen.connect(self._on_variant_quality_chosen)
        table.setItemDelegateForColumn(COL_VARIANT, variant_delegate)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setRootIsDecorated(True)
        table.setUniformRowHeights(True)
        table.setExpandsOnDoubleClick(False)
        table.setAutoScroll(False)
        table.setIconSize(QSize(16, 16))
        table.setDragEnabled(False)
        table.setAcceptDrops(False)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        table.expanded.connect(lambda index, t=table: self._remember_tree_expand(t, index, True))
        table.collapsed.connect(lambda index, t=table: self._remember_tree_expand(t, index, False))
        tree.modelAboutToBeReset.connect(lambda t=table: self._on_tree_about_to_reset(t))
        tree.modelReset.connect(lambda t=table: self._schedule_restore_tree_expansion(t))
        proxy.dataChanged.connect(self._sync_header_check)
        proxy.modelReset.connect(self._sync_header_check)
        proxy.layoutChanged.connect(self._sync_header_check)

        header = CheckHeaderView(table)
        table.setHeader(header)
        header.setModel(tree)
        header.check_clicked.connect(self._toggle_visible_checks)
        header.setStretchLastSection(False)
        header.setFirstSectionMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        table.selectionModel().selectionChanged.connect(self._fill_properties)
        table.setSortingEnabled(False)
        self._reset_columns(table, hidden)
        table.empty_hint = EmptyTableHint(table, tr(empty_message))
        return table

    def _on_variant_quality_chosen(self, index, quality):
        delegate = self.sender()
        table = delegate.parent() if delegate is not None else None
        if table not in (getattr(self, "grab_table", None), getattr(self, "table", None)):
            return
        if not index.isValid():
            return
        src = self._map_index_to_source(table, index)
        model = self.grab_model if table is self.grab_table else self.model
        reel = model.reel_at(src.row())
        model.update_reel(reel.url, match_variant="image", image_quality=quality)
        if model is self.model:
            model.update_reel(reel.url, match_variant="", image_quality=quality)
        self._fill_properties()

    def _hidden_columns(self, table):
        return GRABBER_HIDDEN if table is getattr(self, "grab_table", None) else HIDDEN_BY_DEFAULT

    def _apply_column_modes(self, table=None):
        """Widths follow the lock: pinned columns are always fixed, Title stretches."""
        targets = [table] if table is not None else [
            item for item in (getattr(self, "table", None), getattr(self, "grab_table", None))
            if item is not None
        ]
        for view in targets:
            view.setTreePosition(COL_TITLE)
            header = view.header()
            header.setSectionsMovable(not self._columns_locked)
            for column in range(len(COLUMNS)):
                if column == COL_TITLE:
                    mode = QHeaderView.ResizeMode.Stretch
                elif column in FIXED_COLUMNS or self._columns_locked:
                    mode = QHeaderView.ResizeMode.Fixed
                else:
                    mode = QHeaderView.ResizeMode.Interactive
                header.setSectionResizeMode(column, mode)
            if view.columnWidth(COL_TITLE) < 180:
                header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Interactive)
                view.setColumnWidth(COL_TITLE, COLUMN_WIDTHS.get(COL_TITLE, 260))

    def _set_columns_locked(self, locked):
        self._columns_locked = bool(locked)
        self._settings.setValue("columns_locked", self._columns_locked)
        self._apply_column_modes()

    def _reset_columns(self, table=None, hidden=None):
        view = table if table is not None else self._pack()[2]
        header = view.header()
        hidden = self._hidden_columns(view) if hidden is None else hidden
        for column in range(len(COLUMNS)):
            visual = header.visualIndex(column)
            if visual != column:
                header.moveSection(visual, column)
            view.setColumnHidden(column, column in hidden)
            if column in COLUMN_WIDTHS:
                view.setColumnWidth(column, COLUMN_WIDTHS[column])
        self._apply_column_modes(view)
        if view.horizontalScrollBar() is not None:
            view.horizontalScrollBar().setValue(0)

    def _toggle_column(self, column, visible):
        _model, _proxy, table = self._pack()
        if not visible and not any(
            c for c in range(len(COLUMNS))
            if c not in PINNED_COLUMNS and c != column and not table.isColumnHidden(c)
        ):
            return                              # never leave only the row number
        table.setColumnHidden(column, not visible)
        if visible and not table.columnWidth(column):
            table.setColumnWidth(column, COLUMN_WIDTHS.get(column, 100))

    def _build_column_menu(self):
        """The header menu: one checkable item per column, then layout actions."""
        _model, _proxy, table = self._pack()
        header = table.header()
        menu = QMenu(self)
        handlers = {}
        for column in sorted(range(len(COLUMNS)), key=header.visualIndex):
            if column in PINNED_COLUMNS:
                continue
            action = menu.addAction(tr(COLUMNS[column]))
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(column))
            handlers[action] = lambda checked, c=column: self._toggle_column(c, checked)
        menu.addSeparator()
        color = self._icon_color()
        fit = menu.addAction(icons.icon("select-all", color), tr("Fit columns to content"))
        handlers[fit] = lambda checked: table.resizeColumnsToContents()
        reset = menu.addAction(icons.icon("refresh", color), tr("Reset columns"))
        handlers[reset] = lambda checked: self._reset_columns(table)
        lock = menu.addAction(tr("Lock column layout"))
        lock.setCheckable(True)
        lock.setChecked(self._columns_locked)
        handlers[lock] = self._set_columns_locked
        scroll = menu.addAction(tr("Horizontal scrollbar"))
        scroll.setCheckable(True)
        scroll.setChecked(self._h_scrollbar)
        handlers[scroll] = self._set_h_scrollbar
        return menu, handlers

    def _show_header_menu(self, point):
        menu, handlers = self._build_column_menu()
        chosen = menu.exec(self._pack()[2].header().mapToGlobal(point))
        if chosen is not None:
            handlers[chosen](chosen.isChecked())

    def _build_log(self):
        """Dockable log: drag to split, float to a window, or close. Drag back to dock."""
        self.log_panel = LogPanel(self)
        self.log = self.log_panel.view
        self.log.setMaximumBlockCount(2000)
        self.log_panel.float_requested.connect(self._toggle_log_float)
        self.log_panel.export_requested.connect(self._export_log)
        self.log_panel.folder_requested.connect(self._open_logs_folder)
        self.log_panel.close_requested.connect(self._close_log)
        dock = QDockWidget("Log", self)
        dock.setObjectName("logDock")
        dock.setWidget(self.log_panel)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setTitleBarWidget(self.log_panel.bar)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.topLevelChanged.connect(self._on_log_float_changed)
        dock.visibilityChanged.connect(lambda _visible: self._sync_menu_state())
        self.log_dock = dock
        return dock

    def _build_overview(self):
        """Totals for the tab you are on, over the bottom tools."""
        self.overview = OverviewPanel(self)
        self.overview.close_clicked.connect(self._toggle_overview)
        return self.overview

    def _clamp_overview_size(self, *_args):
        """Keep extra splitter space in the table, not a tall empty overview."""
        if not hasattr(self, "splitter") or not hasattr(self, "overview"):
            return
        if self.overview.isHidden():
            return
        sizes = self.splitter.sizes()
        if len(sizes) < 2:
            return
        cap = self.overview.maximumHeight()
        floor = self.overview.minimumHeight()
        ov = sizes[-1]
        if floor <= ov <= cap:
            return
        extra = ov - cap if ov > cap else ov - floor
        sizes[-1] = cap if ov > cap else floor
        sizes[0] = max(0, sizes[0] + extra)
        self.splitter.blockSignals(True)
        self.splitter.setSizes(sizes)
        self.splitter.blockSignals(False)

    def _refresh_overview(self):
        """The Download tab counts bytes; the Grabber tab counts what it listed."""
        if not hasattr(self, "overview") or self.overview.isHidden():
            return
        if self.tabs.currentIndex() == TAB_GRABBER:
            self.overview.show_readings(tr("Grabber Overview"), self._grabber_readings())
        else:
            self.overview.show_readings(tr("Download Overview"), self._download_readings())

    def _download_readings(self):
        data = self.model.overview()
        counts = data["counts"]
        return (
            (tr("Links"), str(data["links"])),
            (tr("Done"), str(counts.get("done", 0))),
            (tr("Speed"), f"{sysinfo.human_bytes(data['speed'])}/s"),
            (tr("Left"), sysinfo.human_bytes(data["bytes_left"])),
            (tr("ETA"), format_eta(data["eta"]) if data["eta"] else "-"),
        )

    def _grabber_readings(self):
        data = self.grab_model.overview()
        return (
            (tr("Links"), str(data["links"])),
            (tr("Checked"), str(data["checked"])),
            (tr("Known"), str(data["sized"])),
            (tr("Unknown"), str(data["unsized"])),
        )

    def _toggle_overview(self):
        self.overview.setVisible(self.overview.isHidden())
        self._refresh_overview()
        self._clamp_overview_size()
        self._sync_stats_timer()
        self._sync_menu_state()

    def _build_properties(self):
        """JD-style File Properties above the bottom tools."""
        self.properties = PropertiesPanel(self)
        self.properties.close_clicked.connect(self._toggle_properties)
        self.properties.fields_edited.connect(self._commit_properties)
        self.properties.hide()
        return self.properties

    def _fill_properties(self, *_args):
        if not hasattr(self, "properties"):
            return
        _model, _proxy, table = self._pack()
        if table is None:
            return
        reels = self._selected_reels()
        self.properties.load_reel(reels[0] if reels else None)

    def _commit_properties(self):
        url = self.properties.download_from.text().strip()
        if not url:
            return
        model, _proxy, _table = self._pack()
        if model.update_reel(url, **self.properties.fields()):
            if model is self.model:
                self._schedule_store()

    def _toggle_properties(self, checked=None):
        visible = self.properties.isHidden() if checked is None else bool(checked)
        self.properties.setVisible(visible)
        self._settings.setValue("properties_visible", visible)
        if visible:
            self._fill_properties()
        self._sync_menu_state()

    def _set_sidebar_visible(self, visible, persist=True):
        if hasattr(self, "views"):
            self.views.setVisible(bool(visible))
        if persist:
            self._settings.setValue("sidebar_visible", bool(visible))
        self._sync_menu_state()

    def _toggle_sidebar(self):
        if not hasattr(self, "views"):
            return
        self._set_sidebar_visible(self.views.isHidden())

    def _set_h_scrollbar(self, enabled):
        self._h_scrollbar = bool(enabled)
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn if self._h_scrollbar
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        for view in (getattr(self, "table", None), getattr(self, "grab_table", None)):
            if view is not None:
                view.setHorizontalScrollBarPolicy(policy)
        self._settings.setValue("h_scrollbar", self._h_scrollbar)

    def _build_action_bar(self):
        """Bottom strip: add links on the left, save path, then the job buttons."""
        bar = QWidget()
        bar.setObjectName("actionBar")
        self.action_bar = bar
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(6)

        self.add_new_btn = self._bar_pill(
            "Add New Links", "plus", self._add_links, self._build_add_menu())
        self.add_new_btn.setToolTip("Paste posts, channels, or playlists, one per line (F5)")
        self.clip_toggle = self._tool_button(
            "link", "Watch the clipboard for links (Ctrl+G)",
            self._toggle_grabber, checkable=True)
        row.addWidget(self.add_new_btn)
        row.addWidget(self.clip_toggle)
        row.addWidget(self._tool_sep())
        row.addWidget(self._build_save_path(), 1)
        row.addWidget(self._tool_sep())

        self.status = QLabel("Idle")
        self.status.hide()
        self.counter = QLabel("0 ● 0")
        self.counter.setObjectName("jobCounter")
        row.addWidget(self.counter)

        self.continue_btn = self._bar_pill(
            "Continue login", "login", self._continue_login)
        self.cancel_btn = self._bar_pill("Cancel", "cancel", self._cancel)
        self.add_btn = self._bar_pill(
            "Add to downloads", "download", self._add_to_downloads_asked)
        self.add_btn.setToolTip("Move Grabber rows into the Download tab")
        self.download_btn = self._bar_pill(
            "Start all Downloads", "play",
            lambda _=False: self._start_download(), self._build_start_menu())
        self.download_btn.setToolTip(
            "Download remaining items. Finished files are skipped; partial files resume."
        )
        for button in (self.continue_btn, self.cancel_btn, self.add_btn, self.download_btn):
            row.addWidget(button)
        self.options_btn = self._tool_button(
            "settings", "Download and Grabber options", lambda: None)
        self.options_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.options_menu = QMenu(self)
        self.options_btn.setMenu(self.options_menu)
        self.options_menu.aboutToShow.connect(self._populate_options_menu)
        row.addWidget(self.options_btn)
        self._apply_filter()
        return bar

    def _build_save_path(self):
        """Browse the folder new downloads are saved into."""
        group = QWidget()
        group.setObjectName("savePath")
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.save_path_btn = self._tool_button(
            "folder", "Browse download folder", self._browse_save_path)
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setObjectName("savePathEdit")
        self.save_path_edit.setPlaceholderText("Save to…")
        self.save_path_edit.setToolTip("Download save path")
        self.save_path_edit.editingFinished.connect(self._commit_save_path)
        row.addWidget(self.save_path_btn)
        row.addWidget(self.save_path_edit, 1)
        return group

    def _browse_save_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Save downloads to", self._output_root(),
        )
        if not path:
            return
        self.save_path_edit.setText(os.path.normpath(path))
        self._commit_save_path()

    def _commit_save_path(self):
        path = self.save_path_edit.text().strip() or self._output_root()
        path = os.path.normpath(path)
        self._settings.setValue("output_root", path)
        if self.save_path_edit.text() != path:
            self.save_path_edit.setText(path)

    def _sync_save_path_edit(self):
        if getattr(self, "save_path_edit", None) is None:
            return
        current = self._output_root()
        if self.save_path_edit.text() != current:
            self.save_path_edit.setText(current)

    def _persist_views_kinds(self):
        panel = getattr(self, "views", None)
        if panel is None:
            return
        self._settings.setValue("views_kinds", ",".join(sorted(panel.checked_kinds())))
        self._settings.setValue("views_folder_group", panel.folder_group_enabled())
        for key, path in panel.kind_folders().items():
            self._settings.setValue(f"views_folder_{key}", path)
        self._apply_kind_folders_to_models()

    def _kind_folders(self):
        panel = getattr(self, "views", None)
        return panel.kind_folders() if panel is not None else {}

    def _folder_group(self):
        panel = getattr(self, "views", None)
        return panel.folder_group_enabled() if panel is not None else False

    def _stamp_entry(self, item):
        data = dict(item) if isinstance(item, dict) else {"url": item}
        root = self._output_root()
        if not str(data.get("save_dir") or "").strip():
            data["save_dir"] = root
        variant = data.get("variant") or ""
        dest = str(self._kind_folders().get(variant) or "").strip()
        if variant and dest:
            data["save_dir"] = dest
        return data

    def _apply_kind_folders_to_models(self):
        folders = self._kind_folders()
        root = self._output_root()
        for model in (getattr(self, "model", None), getattr(self, "grab_model", None)):
            if model is None:
                continue
            for row in range(model.rowCount()):
                reel = model.reel_at(row)
                if not reel.variant:
                    if not reel.save_dir:
                        model.update_reel(reel.url, save_dir=root, match_variant="")
                    continue
                dest = str(folders.get(reel.variant) or "").strip()
                if dest and dest != reel.save_dir:
                    model.update_reel(reel.url, save_dir=dest, match_variant=reel.variant)

    def _views_layout_key(self):
        folders = self._kind_folders()
        return (
            self._folder_group(),
            tuple(sorted((key, folders.get(key, "")) for key, _label in MEDIA_KINDS)),
        )

    def _sync_views_layout(self):
        """Rebuild package rows when Folder group or per-type save folders change."""
        key = self._views_layout_key()
        if key == getattr(self, "_last_views_layout", None):
            return False
        self._last_views_layout = key
        folder_group, _folders = key
        kind_folders = self._kind_folders()
        for tree in (getattr(self, "download_tree", None), getattr(self, "grab_tree", None)):
            if tree is not None:
                tree.set_folder_group(folder_group)
        for model in (getattr(self, "model", None), getattr(self, "grab_model", None)):
            if model is not None and model.rowCount():
                model.reshape_folder_layout(folder_group, kind_folders)
        for table in (getattr(self, "table", None), getattr(self, "grab_table", None)):
            if table is not None:
                self._collapse_tree(table)
        return True

    def _apply_views_filter(self):
        panel = getattr(self, "views", None)
        if panel is None:
            return
        kinds = panel.checked_kinds()
        hosts = panel.checked_hosts()
        for proxy in (self.proxy, self.grab_proxy):
            proxy.set_kinds(kinds)
            proxy.set_hosts(hosts)
        self._sync_views_layout()
        self._sync_header_check()

    def _refresh_views(self):
        """Rebuild Video/Music/Image and host checks from the active table."""
        panel = getattr(self, "views", None)
        if panel is None or not hasattr(self, "tabs"):
            return
        model, _proxy, _table = self._pack()
        hosts, kinds = model.host_kind_counts()
        panel.set_counts(hosts, kinds)
        self._apply_views_filter()

    def _apply_filter(self, *args):
        """Views (kind + host) filter the tables; the text proxy stays empty."""
        for proxy in (self.proxy, self.grab_proxy):
            proxy.set_field("all")
            proxy.set_text("")
        self._apply_views_filter()
        self._sync_header_check()
