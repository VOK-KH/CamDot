"""Modal listing first-class and coming-soon platforms with collapsible detail rows."""
import re
import threading
import webbrowser
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import icons
from app.core.platform_icons import icon_for
from app.core.platforms import (
    ACTIVE,
    active_platforms,
    coming_soon_platforms,
)

_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.IGNORECASE)


def _primary_url(entry):
    for host in entry.get("hosts") or ():
        clean = str(host or "").strip().lower()
        if _DOMAIN_RE.match(clean):
            return f"https://{clean}"
    return ""


class _CollapsibleCard(QFrame):
    """Platform card: icon/link button opens the site; clicking the card toggles details."""

    def __init__(self, entry, icon_pixmap, color="#e7ecf3", muted_hex="#8c98a8", parent=None):
        super().__init__(parent)
        self.setObjectName("platformCard")
        self.setProperty("platformId", entry["id"])
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._url = _primary_url(entry)

        haystack = " ".join(
            [
                entry["name"],
                entry["id"],
                " ".join(entry["hosts"]),
                " ".join(entry.get("features") or ()),
                " ".join(entry.get("limits") or ()),
                "active" if entry["status"] == ACTIVE else "coming soon",
            ]
        ).lower()
        self.setProperty("searchText", haystack)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 4)
        row.setSpacing(8)

        self.icon_btn = QToolButton(self)
        self.icon_btn.setObjectName("platformIconButton")
        self.icon_btn.setAutoRaise(True)
        self.icon_btn.setFixedSize(20, 20)
        self.icon_btn.setIcon(QIcon(icon_pixmap))
        self.icon_btn.setIconSize(QSize(16, 16))
        self.icon_btn.setStyleSheet("QToolButton { border: none; background: transparent; padding: 0px; }")
        if self._url:
            self.icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.icon_btn.setToolTip(f"Open {self._url}")
            self.icon_btn.clicked.connect(self.open_platform_url)
        else:
            self.icon_btn.setEnabled(False)
        row.addWidget(self.icon_btn, 0, Qt.AlignmentFlag.AlignTop)

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
        if self._url:
            open_btn = QToolButton(self)
            open_btn.setObjectName("platformOpenLink")
            open_btn.setAutoRaise(True)
            open_btn.setFixedSize(18, 18)
            open_btn.setIcon(icons.icon("external", color, 13))
            open_btn.setIconSize(QSize(13, 13))
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.setToolTip(f"Open {self._url}")
            open_btn.setStyleSheet("QToolButton { border: none; background: transparent; padding: 0px; }")
            open_btn.clicked.connect(self.open_platform_url)
            head.addWidget(open_btn)
        head.addStretch(1)
        body.addLayout(head)

        hosts = QLabel(" · ".join(entry["hosts"]))
        hosts.setObjectName("platformHosts")
        hosts.setWordWrap(True)
        body.addWidget(hosts)

        self._entry = entry
        self._details_built = False
        self.details = QWidget(self)
        self.details.setObjectName("platformDetails")
        self._details_layout = QVBoxLayout(self.details)
        self._details_layout.setContentsMargins(0, 2, 0, 2)
        self._details_layout.setSpacing(2)
        self.details.setVisible(False)
        body.addWidget(self.details)

        row.addLayout(body, 1)

    def _ensure_details_built(self):
        if self._details_built:
            return
        self._details_built = True
        muted = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
        for line in self._entry.get("features") or ():
            feature = QLabel(f"• {line}")
            feature.setObjectName("platformFeature")
            feature.setWordWrap(True)
            self._details_layout.addWidget(feature)
        for line in self._entry.get("limits") or ():
            limit = QLabel(f"• {line}")
            limit.setObjectName("platformLimit")
            limit.setWordWrap(True)
            palette = limit.palette()
            palette.setColor(QPalette.ColorRole.WindowText, muted)
            limit.setPalette(palette)
            limit.setForegroundRole(QPalette.ColorRole.WindowText)
            self._details_layout.addWidget(limit)

    def open_platform_url(self):
        if self._url:
            threading.Thread(
                target=webbrowser.open, args=(self._url,), daemon=True,
            ).start()

    def is_expanded(self):
        return not self.details.isHidden()

    def set_expanded(self, expanded):
        expanded = bool(expanded)
        if expanded:
            self._ensure_details_built()
        self.details.setVisible(expanded)

    def toggle_expanded(self):
        self.set_expanded(self.details.isHidden())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_expanded()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PlatformsDialog(QDialog):
    """Compact catalog of hosts and supported domains, with collapsible details."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Supported platforms")
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)
        title = QLabel("Supported platforms")
        title.setObjectName("platformsTitle")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        top_bar.addWidget(title)
        top_bar.addStretch(1)

        self.expand_all_btn = QPushButton("Expand all")
        self.expand_all_btn.setObjectName("platformsExpandAll")
        self.expand_all_btn.setFlat(True)
        self.expand_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_all_btn.clicked.connect(self._toggle_all_cards)
        top_bar.addWidget(self.expand_all_btn)
        layout.addLayout(top_bar)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name, domain, or feature…")
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
        self._list.setSpacing(6)
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
        color = self.palette().color(QPalette.ColorRole.WindowText).name()
        muted_hex = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText).name()
        icon = icon_for(platform=entry["id"], fetch=False, color=color)
        return _CollapsibleCard(entry, icon.pixmap(16, 16), color=color, muted_hex=muted_hex, parent=self)

    def _all_cards(self):
        return self._active_cards + self._soon_cards

    def _toggle_all_cards(self):
        cards = [card for card in self._all_cards() if not card.isHidden()]
        expand = not all(card.is_expanded() for card in cards) if cards else True
        for card in self._all_cards():
            card.set_expanded(expand)
        self.expand_all_btn.setText("Collapse all" if expand else "Expand all")

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
