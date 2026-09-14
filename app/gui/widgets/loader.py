"""Centered overlay while Extract / Link Grabber syncs links into Grabber."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.core import icons


class ExtractLoader(QFrame):
    """Dim the Grabber table and show a botty wait card while links stream in."""

    aborted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("extractLoader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame()
        card.setObjectName("extractLoaderCard")
        card.setMinimumWidth(280)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 16, 18, 14)
        inner.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.mascot = QLabel()
        self.mascot.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title = QLabel("Extracting links")
        self.title.setObjectName("extractLoaderTitle")
        self.title.setWordWrap(True)
        self.detail = QLabel("Looking for links…")
        self.detail.setObjectName("extractLoaderDetail")
        self.detail.setWordWrap(True)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title)
        text.addWidget(self.detail)
        head.addWidget(self.mascot)
        head.addLayout(text, 1)
        inner.addLayout(head)

        self.count = QLabel("0 listed")
        self.count.setObjectName("extractLoaderCount")
        inner.addWidget(self.count)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        inner.addWidget(self.bar)

        self.abort_btn = QPushButton("Cancel")
        self.abort_btn.setObjectName("extractLoaderAbort")
        self.abort_btn.setIcon(icons.icon("cancel", "#eef2f7", 14))
        self.abort_btn.clicked.connect(self.aborted.emit)
        inner.addWidget(self.abort_btn, alignment=Qt.AlignmentFlag.AlignRight)

        row.addWidget(card)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        self.hide()
        self._paint_mascot()

    def _paint_mascot(self):
        pixmap = icons.art("botty", "robot_info", 56)
        if pixmap.isNull():
            pixmap = icons.png("wait", 32)
        self.mascot.setPixmap(pixmap)

    def show_busy(self, title, detail="", count=""):
        self.title.setText(title)
        self.detail.setText(detail or "Looking for links…")
        self.detail.setToolTip(detail)
        if count:
            self.count.setText(count)
        self.abort_btn.setEnabled(True)
        if self.isHidden():
            self.show()
        self.raise_()

    def set_count(self, listed):
        self.count.setText(f"{listed} listed")
