"""Table delegates inspired by the JDownloader-style package tree."""
from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionButton,
)

from app.core.model import IMAGE_QUALITIES, VARIANT_OPTIONS_ROLE


class TextRowDelegate(QStyledItemDelegate):
    """Default cell painter. Rows stay tall enough for Khmer vowel signs."""

    MIN_HEIGHT = 28

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        if hint.height() < self.MIN_HEIGHT:
            hint.setHeight(self.MIN_HEIGHT)
        return hint


class VariantDelegate(QStyledItemDelegate):
    """Variant cell with a drop-down for image quality on Grabber rows."""

    ARROW_WIDTH = 18
    quality_chosen = Signal(object, str)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not index.data(VARIANT_OPTIONS_ROLE):
            return
        arrow_rect = self._arrow_rect(option.rect)
        opt = QStyleOptionButton()
        opt.rect = arrow_rect
        opt.state = QStyle.StateFlag.State_Enabled
        opt.text = "\u25BE"
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_PushButtonLabel, opt, painter, option.widget)

    def _arrow_rect(self, rect):
        return QRect(rect.right() - self.ARROW_WIDTH, rect.top(), self.ARROW_WIDTH, rect.height())

    def editorEvent(self, event, model, option, index):
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False
        if not index.data(VARIANT_OPTIONS_ROLE):
            return False
        if not self._arrow_rect(option.rect).contains(event.pos()):
            return False
        labels = index.data(VARIANT_OPTIONS_ROLE) or []
        keys = [key for key, label in IMAGE_QUALITIES if label in labels]
        menu = QMenu()
        for key, label in IMAGE_QUALITIES:
            if label in labels:
                menu.addAction(label).setData(key)
        chosen = menu.exec(event.globalPos())
        if not chosen:
            return True
        quality = chosen.data()
        if not quality and chosen.text() in labels:
            quality = keys[labels.index(chosen.text())]
        self.quality_chosen.emit(index, quality or "best")
        return True

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.data(VARIANT_OPTIONS_ROLE):
            return QSize(size.width() + self.ARROW_WIDTH, size.height())
        return size


class HosterDelegate(QStyledItemDelegate):
    """Hoster column: platform icon only, domain kept in the tooltip."""

    ICON_SIZE = 16

    def paint(self, painter, option, index):
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon and not icon.isNull():
            target = QRect(
                option.rect.left() + (option.rect.width() - self.ICON_SIZE) // 2,
                option.rect.top() + (option.rect.height() - self.ICON_SIZE) // 2,
                self.ICON_SIZE,
                self.ICON_SIZE,
            )
            icon.paint(painter, target)
            return
        super().paint(painter, option, index)

    def sizeHint(self, option, index):
        return QSize(max(36, super().sizeHint(option, index).width()), option.rect.height())
