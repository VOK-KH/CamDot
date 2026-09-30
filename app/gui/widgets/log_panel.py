"""Log panel: text view plus a custom window header."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QToolButton, QVBoxLayout, QWidget

from app.core import icons
from app.core.i18n import tr


class LogPanel(QWidget):
    """Log text. `bar` is the dock title and, when floated, the frameless window header."""

    float_requested = Signal()
    export_requested = Signal()
    folder_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logPanel")
        self.setMinimumHeight(72)

        self.bar = QWidget()
        self.bar.setObjectName("logBar")
        self.bar.setFixedHeight(32)
        head = QHBoxLayout(self.bar)
        head.setContentsMargins(8, 0, 0, 0)
        head.setSpacing(4)
        mark = QLabel()
        mark.setPixmap(icons.icon("app", size=16).pixmap(16, 16))
        self.title = QLabel(tr("Log"))
        self.title.setObjectName("logTitle")
        head.addWidget(mark)
        head.addWidget(self.title)
        head.addStretch(1)
        self.export_btn = self._button("csv", "Export log…", self.export_requested.emit)
        self.folder_btn = self._button("folder", "Open logs folder", self.folder_requested.emit)
        self.float_btn = self._button("external", "Open in a new window", self.float_requested.emit)
        self.close_btn = self._button(
            "win-close", "Close log", self.close_requested.emit, "logClose",
        )
        for button in (self.export_btn, self.folder_btn, self.float_btn, self.close_btn):
            head.addWidget(button)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(4000)
        mono = QFont("Consolas")
        if "Consolas" not in QFontDatabase.families():
            mono.setFamily(self.font().family())
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        self.view.setFont(mono)
        column.addWidget(self.view, 1)

    def refresh_text(self):
        self.title.setText(tr("Log"))
        self.export_btn.setToolTip(tr("Export log…"))
        self.folder_btn.setToolTip(tr("Open logs folder"))
        self.close_btn.setToolTip(tr("Close log"))
        self.set_floating(self.float_btn.property("iconName") == "win-restore")

    def set_floating(self, floating):
        """Switch the pop-out button between 'new window' and 'dock back'."""
        if floating:
            self.float_btn.setProperty("iconName", "win-restore")
            self.float_btn.setToolTip(tr("Dock in the main window"))
        else:
            self.float_btn.setProperty("iconName", "external")
            self.float_btn.setToolTip(tr("Open in a new window"))

    def _button(self, icon_name, tip, slot, object_name="logHeadBtn"):
        button = QToolButton()
        button.setObjectName(object_name)
        button.setProperty("iconName", icon_name)
        button.setToolTip(tr(tip))
        button.setIconSize(QSize(14, 14))
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button
