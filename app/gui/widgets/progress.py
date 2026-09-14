"""Progress-bar cell for the download table."""
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionProgressBar

from app.core.model import PERCENT_ROLE


class ProgressDelegate(QStyledItemDelegate):
    """Draws the progress column as a bar, cheap enough for thousands of rows."""

    def paint(self, painter, option, index):
        percent = index.data(PERCENT_ROLE)
        if percent is None:
            super().paint(painter, option, index)
            return
        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(4, 5, -4, -5)
        bar.minimum = 0
        bar.maximum = 100
        bar.progress = int(percent)
        bar.text = f"{int(percent)}%"
        bar.textVisible = True
        QApplication.style().drawControl(QStyle.ControlElement.CE_ProgressBar, bar, painter)
