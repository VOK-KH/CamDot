"""Right-hand Views strip: media type and host checks for Grabber/Download."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from app.core.model import MEDIA_KINDS


class ViewsPanel(QFrame):
    """JDownloader-style views: Video / Music / Image, then hosts from the list.

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

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 6, 6, 6)
        column.setSpacing(4)

        title = QLabel("Views")
        title.setObjectName("viewsTitle")
        column.addWidget(title)

        for key, label in MEDIA_KINDS:
            box = QCheckBox(label)
            box.setObjectName("viewsKind")
            box.setChecked(True)
            box.toggled.connect(lambda _checked=False: self.filter_changed.emit())
            self._kind_boxes[key] = box
            column.addWidget(box)

        divider = QFrame()
        divider.setObjectName("viewsDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        column.addWidget(divider)

        hosts_title = QLabel("Host")
        hosts_title.setObjectName("viewsTitle")
        column.addWidget(hosts_title)

        self.host_list = QListWidget()
        self.host_list.setObjectName("viewsHostList")
        self.host_list.setAlternatingRowColors(True)
        self.host_list.itemChanged.connect(self._on_host_changed)
        column.addWidget(self.host_list, 1)

    def checked_kinds(self):
        return {key for key, box in self._kind_boxes.items() if box.isChecked()}

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

    def _on_host_changed(self, item):
        host = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._unchecked_hosts.discard(host)
        else:
            self._unchecked_hosts.add(host)
        self.filter_changed.emit()
