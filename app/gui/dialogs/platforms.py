"""Modal listing first-class and coming-soon platforms."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.platform_icons import icon_for
from app.core.platforms import (
    ACTIVE,
    active_platforms,
    coming_soon_platforms,
)


class PlatformsDialog(QDialog):
    """Compact catalog of hosts the app treats as first-class or coming soon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Supported platforms")
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Supported platforms")
        title.setObjectName("platformsTitle")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        subtitle = QLabel("Active hosts you can paste today, plus coming soon.")
        subtitle.setObjectName("platformsSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name, host, or feature…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll, 1)

        inner = QWidget()
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 4, 0)
        self._list.setSpacing(8)
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._active_header = self._group_header("Active")
        self._list.addWidget(self._active_header)
        self._active_cards = [self._card(entry) for entry in active_platforms()]
        for card in self._active_cards:
            self._list.addWidget(card)

        self._soon_header = self._group_header("Coming soon")
        self._list.addWidget(self._soon_header)
        self._soon_cards = [self._card(entry) for entry in coming_soon_platforms()]
        for card in self._soon_cards:
            self._list.addWidget(card)

        self._list.addStretch(1)
        scroll.setWidget(inner)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._apply_muted()

    def _group_header(self, text):
        label = QLabel(text)
        label.setObjectName("platformsGroup")
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _card(self, entry):
        frame = QFrame()
        frame.setObjectName("platformCard")
        frame.setProperty("platformId", entry["id"])
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        haystack = " ".join(
            [
                entry["name"],
                entry["id"],
                " ".join(entry["hosts"]),
                " ".join(entry["features"]),
                " ".join(entry["limits"]),
                "active" if entry["status"] == ACTIVE else "coming soon",
            ]
        ).lower()
        frame.setProperty("searchText", haystack)

        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 2, 0, 6)
        row.setSpacing(8)

        color = self.palette().color(QPalette.ColorRole.WindowText).name()
        icon_label = QLabel()
        icon_label.setFixedSize(18, 18)
        icon = icon_for(platform=entry["id"], fetch=False, color=color)
        icon_label.setPixmap(icon.pixmap(16, 16))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        name = QLabel(entry["name"])
        name.setObjectName("platformName")
        name_font = name.font()
        name_font.setBold(True)
        name.setFont(name_font)
        head.addWidget(name)
        badge = QLabel("Active" if entry["status"] == ACTIVE else "Coming soon")
        badge.setObjectName("platformBadge")
        badge.setProperty("status", entry["status"])
        head.addWidget(badge)
        head.addStretch(1)
        body.addLayout(head)

        hosts = QLabel(" · ".join(entry["hosts"]))
        hosts.setObjectName("platformHosts")
        hosts.setWordWrap(True)
        body.addWidget(hosts)

        for line in entry["features"]:
            feature = QLabel(f"• {line}")
            feature.setObjectName("platformFeature")
            feature.setWordWrap(True)
            body.addWidget(feature)
        for line in entry["limits"]:
            limit = QLabel(f"• {line}")
            limit.setObjectName("platformLimit")
            limit.setWordWrap(True)
            body.addWidget(limit)

        row.addLayout(body, 1)
        return frame

    def _filter(self, text):
        needle = (text or "").strip().lower()
        self._apply_filter(self._active_header, self._active_cards, needle)
        self._apply_filter(self._soon_header, self._soon_cards, needle)

    def _apply_filter(self, header, cards, needle):
        visible = 0
        for card in cards:
            show = not needle or needle in (card.property("searchText") or "")
            card.setVisible(show)
            if show:
                visible += 1
        header.setVisible(visible > 0)

    def _apply_muted(self):
        muted = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        for hosts in self.findChildren(QLabel, "platformHosts"):
            palette = hosts.palette()
            palette.setColor(QPalette.ColorRole.WindowText, muted)
            hosts.setPalette(palette)
            hosts.setForegroundRole(QPalette.ColorRole.WindowText)
        for limit in self.findChildren(QLabel, "platformLimit"):
            palette = limit.palette()
            palette.setColor(QPalette.ColorRole.WindowText, muted)
            limit.setPalette(palette)
            limit.setForegroundRole(QPalette.ColorRole.WindowText)
        for badge in self.findChildren(QLabel, "platformBadge"):
            color = accent if badge.property("status") == ACTIVE else muted
            badge.setStyleSheet(
                f"color: {color.name()}; font-size: 11px; padding: 0px;"
            )
        subtitle = self.findChild(QLabel, "platformsSubtitle")
        if subtitle:
            palette = subtitle.palette()
            palette.setColor(QPalette.ColorRole.WindowText, muted)
            subtitle.setPalette(palette)
            subtitle.setForegroundRole(QPalette.ColorRole.WindowText)
