"""Empty-state artwork shown when a table has no rows."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.core import icons


class EmptyTableHint(QWidget):
    """Centered illustration over a table viewport while that table has no rows."""

    def __init__(self, table, message="No items"):
        super().__init__(table.viewport())
        self._table = table
        self.setObjectName("emptyTable")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        art = QLabel()
        art.setObjectName("emptyTableArt")
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setPixmap(icons.art("empty", "list", 150))
        caption = QLabel(message)
        caption.setObjectName("emptyTableHint")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(art)
        layout.addWidget(caption)

        table.viewport().installEventFilter(self)
        model = table.model()
        if model is not None:
            model.modelReset.connect(self.sync)
            model.layoutChanged.connect(self.sync)
            model.rowsInserted.connect(self.sync)
            model.rowsRemoved.connect(self.sync)
        self.sync()

    def eventFilter(self, watched, event):
        if watched is self._table.viewport() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._table.viewport().rect())
        return False

    def sync(self, *_args):
        model = self._table.model()
        empty = model is None or model.rowCount() == 0
        self.setVisible(empty)
        if empty:
            self.setGeometry(self._table.viewport().rect())
            self.raise_()
