"""Desktop Link Grabber monitor as a floating tool window."""
from PySide6.QtCore import QElapsedTimer, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import icons


class GrabberPanel(QFrame):
    """Readings for the background grab, as a free-floating desktop popup.

    The main window owns the numbers and pushes them in; this window can sit
    anywhere on the screen, including outside the app.
    """

    FIELDS = (
        ("Duration", "wait"),
        ("Found Link(s)", "link"),
        ("Duplicate(s)", "remove_dupes"),
        ("Link queue", "question"),
        ("Grabber list", "list"),
        ("Download queue", "download"),
        ("Status", "wait"),
    )
    STATUS_ART = {"Done!": "ok", "Aborted": "cancel"}
    TICK_MS = 500

    aborted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("grabberPanel")
        self.setWindowTitle("Parse Clipboard")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.user_placed = False
        self._drag_offset = None
        self._values = {}
        self._glyphs = {}
        self._elapsed = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(self.TICK_MS)
        self._tick.timeout.connect(self._show_duration)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_head())
        column.addWidget(self._build_body())
        self.hide()

    def _build_head(self):
        """Title line with the pin that keeps the panel open and a close button."""
        head = QWidget()
        head.setObjectName("grabberHead")
        row = QHBoxLayout(head)
        row.setContentsMargins(6, 2, 3, 2)
        row.setSpacing(4)
        title = QLabel("Parse Clipboard")
        title.setObjectName("grabberTitle")
        self.pin_btn = self._head_button("pinned", "Keep this panel open", checkable=True)
        self.pin_btn.toggled.connect(self._sync_pin)
        self.close_btn = self._head_button("close", "Hide this panel")
        self.close_btn.clicked.connect(self.hide)
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self.pin_btn)
        row.addWidget(self.close_btn)
        self._sync_pin(False)
        return head

    def _build_body(self):
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(1)

        art = QLabel()
        art.setPixmap(icons.png("clipboard", 24))
        art.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        grid.addWidget(art, 0, 0, len(self.FIELDS), 1)
        grid.setColumnMinimumWidth(0, 32)

        for row, (name, artwork) in enumerate(self.FIELDS):
            label = QLabel(f"{name}:")
            label.setObjectName("grabberName")
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            glyph = QLabel()
            glyph.setPixmap(icons.png(artwork, 14))
            value = QLabel("—")
            value.setObjectName("grabberValue")
            value.setMinimumWidth(value.fontMetrics().horizontalAdvance("Analyzing…"))
            grid.addWidget(label, row, 1)
            grid.addWidget(glyph, row, 2)
            grid.addWidget(value, row, 3)
            self._values[name] = value
            self._glyphs[name] = glyph

        self.abort_btn = QPushButton("Abort")
        self.abort_btn.setObjectName("grabberAbort")
        self.abort_btn.setIcon(icons.png_icon("cancel", 14))
        self.abort_btn.clicked.connect(self.aborted.emit)
        grid.addWidget(self.abort_btn, len(self.FIELDS), 1, 1, 3)
        return body

    def _head_button(self, artwork, tooltip, checkable=False):
        button = QToolButton()
        button.setObjectName("grabberHeadBtn")
        button.setIcon(icons.png_icon(artwork, 12))
        button.setIconSize(QSize(12, 12))
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        return button

    def _sync_pin(self, pinned):
        self.pin_btn.setIcon(icons.png_icon("pinned" if pinned else "nonpinned", 12))
        self.pin_btn.setToolTip(
            "Unpin, so the panel closes when the run ends" if pinned
            else "Keep this panel open after the run ends"
        )

    def is_pinned(self):
        return self.pin_btn.isChecked()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            local = event.position().toPoint()
            child = self.childAt(local)
            on_chrome = child in (self.pin_btn, self.close_btn, self.abort_btn)
            if not on_chrome and local.y() <= self.findChild(QWidget, "grabberHead").height():
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.user_placed = True
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def begin_run(self, readings, url=""):
        """Start the clock, arm Abort, and show the panel."""
        if not self._tick.isActive():
            self._elapsed.start()
            self._tick.start()
        self.abort_btn.setEnabled(True)
        self.set_readings(readings, url)
        if self.isHidden():
            self.show()

    def set_readings(self, readings, url=""):
        """`readings` maps a field name to the text it should show."""
        for name, text in readings.items():
            self._values[name].setText(text)
            if name == "Status":
                self._glyphs[name].setPixmap(
                    icons.png(self.STATUS_ART.get(text, "wait"), 14)
                )
        self.setToolTip(url or "")
        self._show_duration()

    def end_run(self, readings, url=""):
        """Freeze the clock on the final reading and disarm Abort."""
        self._tick.stop()
        self.abort_btn.setEnabled(False)
        self.set_readings(readings, url)

    def reading(self, name):
        return self._values[name].text()

    def _show_duration(self):
        if not self._elapsed.isValid():
            return
        seconds = int(self._elapsed.elapsed() / 1000)
        self._values["Duration"].setText(
            f"{seconds}s" if seconds < 60 else f"{seconds // 60}:{seconds % 60:02d}"
        )
