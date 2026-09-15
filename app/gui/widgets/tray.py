"""System tray icon and context menu."""
import os

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSpinBox,
    QSystemTrayIcon,
    QWidget,
    QWidgetAction,
)

from app.core import icons
from app.core.download import DEFAULT_FRAGMENTS, DEFAULT_WORKERS

_OFFSCREEN_ICON = None


def _make_tray_icon(window):
    """Reuse one native icon offscreen so Windows tests do not exhaust the tray."""
    global _OFFSCREEN_ICON
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        if _OFFSCREEN_ICON is None:
            _OFFSCREEN_ICON = QSystemTrayIcon()
        return _OFFSCREEN_ICON
    return QSystemTrayIcon(window)


class TrayController(QObject):
    """Owns the tray icon; slots call back into MainWindow."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.icon = _make_tray_icon(window)
        self.icon.setIcon(icons.icon("app", "#1877f2", 64))
        self.menu = QMenu(window)
        self._chunks = None
        self._workers = None
        self._limit_on = None
        self._limit_rate = None
        self._activated_connected = False
        self._build_menu()
        self.menu.aboutToShow.connect(self.reload_controls)
        self.refresh_tooltip()
        self.sync_grabber()
        self.set_busy(window._thread is not None)
        if self._can_show():
            self.icon.setContextMenu(self.menu)
            self.icon.activated.connect(self._activated)
            self._activated_connected = True
            self.icon.show()

    @staticmethod
    def _can_show():
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            return False
        return QSystemTrayIcon.isSystemTrayAvailable()

    def _icon(self, name):
        return icons.icon(name, self.window._icon_color())

    def _build_menu(self):
        menu = self.menu
        menu.clear()
        self.act_show = QAction(self._icon("app"), "Show window", menu)
        self.act_show.triggered.connect(self.show_window)
        menu.addAction(self.act_show)

        self.act_start = QAction(self._icon("play"), "Start Downloads", menu)
        self.act_start.triggered.connect(self._start_downloads)
        menu.addAction(self.act_start)

        self.act_update = QAction(self._icon("refresh"), "Check for tool updates", menu)
        self.act_update.triggered.connect(self.window._check_tool_updates)
        menu.addAction(self.act_update)

        self.act_folder = QAction(self._icon("folder"), "Open download folder", menu)
        self.act_folder.triggered.connect(self.window._open_folder)
        menu.addAction(self.act_folder)

        self.act_clipboard = QAction(self._icon("link"), "Clipboard monitoring", menu)
        self.act_clipboard.setCheckable(True)
        self.act_clipboard.toggled.connect(self.window._toggle_grabber)
        menu.addAction(self.act_clipboard)

        menu.addSeparator()
        self._chunks = QSpinBox()
        self._chunks.setRange(1, 32)
        self._chunks.setToolTip("Max chunks per download")
        self._chunks.valueChanged.connect(
            lambda value: self.window._settings.setValue("fragments", value)
        )
        self._add_labeled(menu, "Max. chunks per download", self._chunks)

        self._workers = QSpinBox()
        self._workers.setRange(1, 16)
        self._workers.setToolTip("Max simultaneous downloads")
        self._workers.valueChanged.connect(
            lambda value: self.window._settings.setValue("workers", value)
        )
        self._add_labeled(menu, "Max. simultaneous downloads", self._workers)

        self._limit_on = QCheckBox("Speed limit")
        self._limit_rate = QLineEdit()
        self._limit_rate.setPlaceholderText("50K")
        self._limit_rate.setMaximumWidth(72)
        self._limit_on.toggled.connect(lambda _=False: self._persist_limit())
        self._limit_rate.editingFinished.connect(self._persist_limit)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)
        layout.addWidget(self._limit_on)
        layout.addWidget(self._limit_rate)
        action = QWidgetAction(menu)
        action.setDefaultWidget(row)
        menu.addAction(action)

        menu.addSeparator()
        self.act_settings = QAction(self._icon("settings"), "Settings", menu)
        self.act_settings.triggered.connect(self.window._open_settings)
        menu.addAction(self.act_settings)

        self.act_exit = QAction(self._icon("win-close"), "Exit", menu)
        self.act_exit.triggered.connect(self.window._quit_application)
        menu.addAction(self.act_exit)
        self.reload_controls()

    def _add_labeled(self, menu, label, widget):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)
        layout.addWidget(QLabel(label), 1)
        layout.addWidget(widget)
        action = QWidgetAction(menu)
        action.setDefaultWidget(row)
        menu.addAction(action)

    def _persist_limit(self):
        self.window._settings.setValue("speed_limit_on", self._limit_on.isChecked())
        self.window._settings.setValue("speed_limit", self._limit_rate.text().strip())
        self._limit_rate.setEnabled(self._limit_on.isChecked())

    def reload_controls(self):
        get = self.window._settings.value
        if self._chunks is not None:
            self._chunks.blockSignals(True)
            self._chunks.setValue(int(get("fragments", DEFAULT_FRAGMENTS)))
            self._chunks.blockSignals(False)
        if self._workers is not None:
            self._workers.blockSignals(True)
            self._workers.setValue(int(get("workers", DEFAULT_WORKERS)))
            self._workers.blockSignals(False)
        if self._limit_on is not None:
            self._limit_on.blockSignals(True)
            self._limit_on.setChecked(get("speed_limit_on", False, bool))
            self._limit_on.blockSignals(False)
            self._limit_rate.blockSignals(True)
            self._limit_rate.setText(get("speed_limit", "", str))
            self._limit_rate.blockSignals(False)
            self._limit_rate.setEnabled(self._limit_on.isChecked())
        self.sync_grabber()
        self.set_busy(self.window._thread is not None)

    def refresh_icon(self):
        self.icon.setIcon(icons.icon("app", "#1877f2", 64))
        for action, name in (
            (self.act_show, "app"),
            (self.act_start, "play"),
            (self.act_update, "refresh"),
            (self.act_folder, "folder"),
            (self.act_clipboard, "link"),
            (self.act_settings, "settings"),
            (self.act_exit, "win-close"),
        ):
            action.setIcon(self._icon(name))

    def refresh_tooltip(self):
        grabber = "on" if self.window.act_grabber.isChecked() else "off"
        busy = " · downloading" if self.window._thread is not None else ""
        self.icon.setToolTip(
            f"{self.window.windowTitle()} — grabber {grabber}{busy}"
        )

    def sync_grabber(self):
        checked = self.window.act_grabber.isChecked()
        self.act_clipboard.blockSignals(True)
        self.act_clipboard.setChecked(checked)
        self.act_clipboard.blockSignals(False)
        self.refresh_tooltip()

    def set_busy(self, busy):
        self.act_start.setEnabled(not busy)
        self.refresh_tooltip()

    def _start_downloads(self):
        if self.window._thread is not None:
            return
        self.window._start_download()

    def show_window(self):
        window = self.window
        if window.isMinimized() or window.isHidden():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()
        window.setWindowState(
            window.windowState() & ~Qt.WindowState.WindowMinimized
        )

    def _activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def hide_icon(self):
        self.icon.setContextMenu(None)
        if self._activated_connected:
            self.icon.activated.disconnect(self._activated)
            self._activated_connected = False
        self.icon.hide()
