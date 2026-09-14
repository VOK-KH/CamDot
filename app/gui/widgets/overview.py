"""The Overview strip above the bottom tools: the totals for the current tab."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class OverviewPanel(QWidget):
    """A title line plus two rows of readings, filled column by column."""

    ROWS = 2
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("overviewPanel")
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 3, 4, 4)
        column.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(5)
        glyph = QLabel()
        glyph.setProperty("iconName", "activity")
        self.title = QLabel("Overview")
        self.title.setObjectName("overviewTitle")
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("overviewClose")
        self.close_btn.setProperty("iconName", "win-close")
        self.close_btn.setToolTip("Hide the overview (Ctrl+Shift+O)")
        self.close_btn.setIconSize(QSize(11, 11))
        self.close_btn.clicked.connect(self.close_clicked)
        head.addWidget(glyph)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.close_btn)
        column.addLayout(head)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(1)
        column.addLayout(self.grid)
        self._values = {}

    def show_readings(self, title, readings):
        """Fill the strip from `readings`, a sequence of (name, text) pairs."""
        self.title.setText(title)
        names = [name for name, _text in readings]
        if names != list(self._values):
            self._rebuild(names)
        for name, text in readings:
            self._values[name].setText(text)

    def reading(self, name):
        """The value label for `name`, so callers can read what is on screen."""
        return self._values[name].text()

    def _rebuild(self, names):
        """Lay the cells out again; only a tab switch changes the names."""
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self._values = {}
        # A value that grows must not shove its neighbours sideways every tick.
        width = self.fontMetrics().horizontalAdvance("8888.8 MB/s")
        for index, name in enumerate(names):
            row, cell = index % self.ROWS, index // self.ROWS
            label = QLabel(f"{name}:")
            label.setObjectName("overviewName")
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value = QLabel("—")
            value.setObjectName("overviewValue")
            value.setMinimumWidth(width)
            self.grid.addWidget(label, row, cell * 2)
            self.grid.addWidget(value, row, cell * 2 + 1)
            self._values[name] = value
        columns = -(-len(names) // self.ROWS)
        for index in range(columns):
            self.grid.setColumnStretch(index * 2, 0)
            self.grid.setColumnStretch(index * 2 + 1, 1)
