"""Table header with a master checkbox on the check column."""
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionButton

from app.core.model import COL_CHECK


class CheckHeaderView(QHeaderView):
    """Paints a master checkbox on the check column without sorting on that click."""

    check_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._state = Qt.CheckState.Unchecked
        self.setSectionsClickable(True)
        self.setHighlightSections(False)

    def set_check_state(self, state):
        if state == self._state:
            return
        self._state = Qt.CheckState(state)
        self.viewport().update()

    def paintSection(self, painter, rect, index):
        super().paintSection(painter, rect, index)
        if index != COL_CHECK:
            return
        option = QStyleOptionButton()
        size = 14
        option.rect = QRect(
            rect.x() + (rect.width() - size) // 2,
            rect.y() + (rect.height() - size) // 2,
            size, size,
        )
        option.state = QStyle.StateFlag.State_Enabled
        if self._state == Qt.CheckState.Checked:
            option.state |= QStyle.StateFlag.State_On
        elif self._state == Qt.CheckState.PartiallyChecked:
            option.state |= QStyle.StateFlag.State_NoChange
        else:
            option.state |= QStyle.StateFlag.State_Off
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, option, painter)

    def mousePressEvent(self, event):
        # Only the left button toggles; right-click belongs to the column menu.
        if (event.button() == Qt.MouseButton.LeftButton
                and self.logicalIndexAt(event.position().toPoint()) == COL_CHECK):
            self.check_clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)
