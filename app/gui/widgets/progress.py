"""Progress-bar cell for the download table."""
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from app.core import theme
from app.core.model import (
    COL_STATUS,
    PERCENT_ROLE,
    STATUS_COLORS,
    STATUS_COLORS_DARK,
    STATUS_LABELS,
)

_LABEL_TO_STATUS = {label: key for key, label in STATUS_LABELS.items()}
_GROOVE_DARK = QColor("#243044")
_GROOVE_LIGHT = QColor("#d5dbe3")
_TEXT_LIGHT = QColor("#f4f7fb")
_TEXT_DARK = QColor("#1c1e21")
_RADIUS = 3


class ProgressDelegate(QStyledItemDelegate):
    """Draws the progress column as a bar, cheap enough for thousands of rows."""

    def paint(self, painter, option, index):
        percent = index.data(PERCENT_ROLE)
        if percent is None:
            super().paint(painter, option, index)
            return

        painter.save()
        try:
            self._paint_background(painter, option)
            dark = self._is_dark(option.palette)
            bar = option.rect.adjusted(4, 5, -4, -5)
            if bar.width() < 1 or bar.height() < 1:
                return

            status = self._status_at(index)
            pct = max(0.0, float(percent))
            fill = self._fill_color(status, pct, dark)

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            path = QPainterPath()
            path.addRoundedRect(QRectF(bar), _RADIUS, _RADIUS)
            painter.fillPath(path, _GROOVE_DARK if dark else _GROOVE_LIGHT)

            if fill is not None and pct > 0:
                fill_w = max(0, int(bar.width() * min(pct, 100.0) / 100.0))
                if fill_w > 0:
                    painter.save()
                    painter.setClipPath(path)
                    painter.fillRect(
                        QRect(bar.x(), bar.y(), fill_w, bar.height()), fill,
                    )
                    painter.restore()

            covers_center = (bar.width() * min(pct, 100.0) / 100.0) >= (bar.width() / 2)
            text_color = _TEXT_LIGHT if (dark or covers_center) else _TEXT_DARK
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(text_color)
            painter.drawText(
                option.rect,
                int(Qt.AlignmentFlag.AlignCenter),
                f"{int(pct)}%",
            )
        finally:
            painter.restore()

    @staticmethod
    def _paint_background(painter, option):
        if option.features & QStyleOptionViewItem.ViewItemFeature.Alternate:
            color = option.palette.color(QPalette.ColorRole.AlternateBase)
        else:
            color = option.palette.color(QPalette.ColorRole.Base)
        painter.fillRect(option.rect, color)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, theme.accent_wash())

    @staticmethod
    def _is_dark(palette):
        return palette.color(QPalette.ColorRole.Base).lightness() < 128

    @staticmethod
    def _status_at(index):
        label = index.sibling(index.row(), COL_STATUS).data(Qt.ItemDataRole.DisplayRole)
        return _LABEL_TO_STATUS.get(label, "queued")

    @staticmethod
    def _fill_color(status, percent, dark):
        colors = STATUS_COLORS_DARK if dark else STATUS_COLORS
        if status == "failed":
            return QColor(colors["failed"])
        if status == "cancelled":
            return QColor(colors["cancelled"])
        if status == "done" or percent >= 100:
            return QColor(colors["done"])
        if status == "downloading" or (status == "queued" and percent > 0):
            return QColor(theme.primary_color())
        return None
