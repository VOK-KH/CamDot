"""Right-hand Views strip: media type and host checks for Grabber/Download."""
import os
import weakref

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import icons, platform_icons
from app.core.i18n import tr
from app.core.model import MEDIA_KINDS

KIND_ICONS = {
    "video": "kind-video",
    "music": "kind-music",
    "image": "kind-image",
    "document": "kind-document",
}
KIND_ICON_SIZE = QSize(16, 16)


class _FaviconTask(QRunnable):
    """Download one unknown-host favicon off the UI thread."""

    def __init__(self, host, dest_dir, bridge):
        super().__init__()
        self.setAutoDelete(True)
        self.host = host
        self.dest_dir = dest_dir
        self._bridge = weakref.ref(bridge)

    def run(self):
        path = platform_icons.fetch_favicon(self.host, self.dest_dir) or ""
        bridge = self._bridge()
        if bridge is not None:
            bridge.ready.emit(self.host, path)


class _FaviconBridge(QObject):
    ready = Signal(str, str)


class ViewsPanel(QFrame):
    """Views panel: Video / Music / Image, then hosts from the list.

    There is no hide control — the strip stays beside the tables.
    """

    filter_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("viewsPanel")
        self.setMinimumWidth(168)
        self.setMaximumWidth(260)
        self._unchecked_hosts = set()
        self._kind_boxes = {}
        self._kind_folders = {key: "" for key, _label in MEDIA_KINDS}
        self._icon_color = "#e7ecf3"
        self._fetch_started = set()
        self._favicon_bridge = _FaviconBridge(self)
        self._favicon_bridge.ready.connect(self._on_favicon_fetched)

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 6, 6, 6)
        column.setSpacing(4)

        title = QLabel(tr("Views"))
        title.setObjectName("viewsTitle")
        column.addWidget(title)

        for key, label in MEDIA_KINDS:
            box = QCheckBox(tr(label))
            box.setObjectName("viewsKind")
            box.setProperty("iconName", KIND_ICONS[key])
            box.setIconSize(KIND_ICON_SIZE)
            box.setChecked(key == "video")
            box.toggled.connect(lambda _checked=False: self.filter_changed.emit())
            self._kind_boxes[key] = box
            column.addWidget(box)

        self.folder_group = QCheckBox(tr("Folder group"))
        self.folder_group.setObjectName("viewsFolderGroup")
        self.folder_group.setProperty("iconName", "folder")
        self.folder_group.setIconSize(KIND_ICON_SIZE)
        self.folder_group.setToolTip(
            "Group each link as a folder in the list and save files into a "
            "subfolder named from the caption."
        )
        self.folder_group.toggled.connect(lambda _checked=False: self.filter_changed.emit())
        column.addWidget(self.folder_group)

        divider = QFrame()
        divider.setObjectName("viewsDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        column.addWidget(divider)

        hosts_title = QLabel(tr("Host"))
        hosts_title.setObjectName("viewsTitle")
        column.addWidget(hosts_title)

        self.host_list = QListWidget()
        self.host_list.setObjectName("viewsHostList")
        self.host_list.setIconSize(QSize(16, 16))
        self.host_list.setAlternatingRowColors(True)
        self.host_list.itemChanged.connect(self._on_host_changed)
        column.addWidget(self.host_list, 1)
        self.apply_icons(self._icon_color)

    def apply_icons(self, color):
        """Recolor kind and host icons to match the window theme."""
        self._icon_color = color
        for key, box in self._kind_boxes.items():
            box.setIcon(icons.icon(KIND_ICONS[key], color, 16))
            box.setIconSize(KIND_ICON_SIZE)
        self.folder_group.setIcon(icons.icon("folder", color, 16))
        self.folder_group.setIconSize(KIND_ICON_SIZE)
        self._refresh_host_icons()

    def kind_folders(self):
        """Absolute save folders per type; empty means the main download folder."""
        return dict(self._kind_folders)

    def set_kind_folders(self, folders):
        folders = folders or {}
        for key, _label in MEDIA_KINDS:
            self._kind_folders[key] = str(folders.get(key) or "").strip()

    def folder_group_enabled(self):
        return self.folder_group.isChecked()

    def set_folder_group(self, enabled, emit=True):
        self.folder_group.blockSignals(True)
        self.folder_group.setChecked(bool(enabled))
        self.folder_group.blockSignals(False)
        if emit:
            self.filter_changed.emit()

    def checked_kinds(self):
        return {key for key, box in self._kind_boxes.items() if box.isChecked()}

    def set_checked_kinds(self, kinds, emit=True):
        """Check Video / Music / Image. Default is video only."""
        wanted = set(kinds) if kinds is not None else {"video"}
        for key, box in self._kind_boxes.items():
            box.blockSignals(True)
            box.setChecked(key in wanted)
            box.blockSignals(False)
        if emit:
            self.filter_changed.emit()

    def checked_hosts(self):
        """None means every listed host is included (no extra host filter)."""
        if self.host_list.count() == 0:
            return None
        allowed = set()
        for row in range(self.host_list.count()):
            item = self.host_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                allowed.add(item.data(Qt.ItemDataRole.UserRole))
        if len(allowed) == self.host_list.count():
            return None
        return allowed

    def set_counts(self, hosts, kinds):
        """`hosts` and `kinds` are name -> count maps from the active table."""
        for key, label in MEDIA_KINDS:
            self._kind_boxes[key].setText(f"{label} ({int(kinds.get(key, 0))})")
        self.host_list.blockSignals(True)
        self.host_list.clear()
        for host, count in sorted(hosts.items(), key=lambda item: (-item[1], item[0])):
            item = QListWidgetItem(f"{host}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, host)
            item.setIcon(self._host_icon(host))
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            checked = host not in self._unchecked_hosts
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            self.host_list.addItem(item)
        self.host_list.blockSignals(False)

    def _refresh_host_icons(self):
        self.host_list.blockSignals(True)
        for row in range(self.host_list.count()):
            item = self.host_list.item(row)
            host = item.data(Qt.ItemDataRole.UserRole)
            item.setIcon(self._host_icon(host))
        self.host_list.blockSignals(False)

    def _host_icon(self, host):
        """Site favicon from app cache; fetch in the background when missing."""
        color = self._icon_color
        if not host or host == "-":
            return platform_icons.icon_for(domain=host or "", fetch=False, color=color)
        dest = platform_icons.favicon_cache_path(host)
        if dest:
            return QIcon(dest)
        icon = platform_icons.host_color_icon(host, fetch=False, color=color)
        self._queue_favicon(host)
        return icon

    def _cached_favicon(self, host):
        return platform_icons.favicon_cache_path(host)

    def _queue_favicon(self, host):
        if host in self._fetch_started:
            return
        self._fetch_started.add(host)
        task = _FaviconTask(host, platform_icons.cache_dir(), self._favicon_bridge)
        QThreadPool.globalInstance().start(task)

    def _on_favicon_fetched(self, host, path):
        if not path or not os.path.isfile(path):
            return
        for row in range(self.host_list.count()):
            item = self.host_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) != host:
                continue
            item.setIcon(QIcon(path))
            break

    def _on_host_changed(self, item):
        host = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._unchecked_hosts.discard(host)
        else:
            self._unchecked_hosts.add(host)
        self.filter_changed.emit()
