"""Dialog that takes a whole paste of links instead of a single URL."""
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

PLACEHOLDER = (
    "https://www.facebook.com/reel/123456789\n"
    "https://www.instagram.com/reel/AbCdEfGh\n"
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
)


class AddLinksDialog(QDialog):
    """Collect one link per line so a batch needs a single trip to the dialog."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Links")
        self.resize(560, 280)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Paste posts, channels, or playlists — one link per line:"))
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(PLACEHOLDER)
        self.edit.setPlainText(text)
        layout.addWidget(self.edit, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self):
        return self.edit.toPlainText().strip()
