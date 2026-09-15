"""Compact File / Link properties strip, JDownloader-style."""
from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class PropertiesPanel(QWidget):
    """Name, save path, URL, and comment for the selected row."""

    MIN_HEIGHT = 88
    MAX_HEIGHT = 132
    close_clicked = Signal()
    fields_edited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("propertiesPanel")
        self.setMinimumHeight(self.MIN_HEIGHT)
        self.setMaximumHeight(self.MAX_HEIGHT)
        self._loading = False

        column = QVBoxLayout(self)
        column.setContentsMargins(6, 2, 4, 4)
        column.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(5)
        glyph = QLabel()
        glyph.setProperty("iconName", "settings")
        self.title = QLabel("File Properties")
        self.title.setObjectName("propertiesTitle")
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("overviewClose")
        self.close_btn.setProperty("iconName", "win-close")
        self.close_btn.setToolTip("Hide Package or Link Properties")
        self.close_btn.setIconSize(QSize(11, 11))
        self.close_btn.clicked.connect(self.close_clicked)
        head.addWidget(glyph)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.close_btn)
        column.addLayout(head)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 4, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(2)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name")
        self.save_to = QLineEdit()
        self.save_to.setPlaceholderText("Save to…")
        self.download_from = QLineEdit()
        self.download_from.setReadOnly(True)
        self.download_from.setPlaceholderText("Download from")
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Comment")
        form.addRow("Name", self.name)
        form.addRow("Save to", self.save_to)
        form.addRow("Download from", self.download_from)
        form.addRow("Comment", self.comment)
        column.addLayout(form)

        for field in (self.name, self.save_to, self.comment):
            field.editingFinished.connect(self._on_edit)

    def _on_edit(self):
        if not self._loading:
            self.fields_edited.emit()

    def load_reel(self, reel):
        """Fill the form from a reel, or clear it when nothing is selected."""
        self._loading = True
        if reel is None:
            self.name.clear()
            self.save_to.clear()
            self.download_from.clear()
            self.comment.clear()
            self.setEnabled(False)
        else:
            self.setEnabled(True)
            self.name.setText(reel.title or "")
            self.save_to.setText(reel.filepath or "")
            self.download_from.setText(reel.url or "")
            self.comment.setText(reel.comment or "")
        self._loading = False

    def fields(self):
        return {
            "title": self.name.text(),
            "filepath": self.save_to.text(),
            "comment": self.comment.text(),
        }
