"""Layout constants shared by the window, tables, and widgets."""
from PySide6.QtCore import Qt

from app.core.model import (
    COL_CHECK,
    COL_DURATION,
    COL_ETA,
    COL_FILE,
    COL_HOST,
    COL_ID,
    COL_INDEX,
    COL_PROGRESS,
    COL_SIZE,
    COL_SPEED,
    COL_STATUS,
    COL_TITLE,
    COL_UPLOADER,
    COL_URL,
)

COLUMN_WIDTHS = {
    COL_CHECK: 28, COL_HOST: 118, COL_INDEX: 42, COL_STATUS: 110, COL_PROGRESS: 118,
    COL_TITLE: 280, COL_UPLOADER: 140, COL_ID: 120, COL_SIZE: 78, COL_DURATION: 64,
    COL_SPEED: 84, COL_ETA: 52, COL_FILE: 220, COL_URL: 200,
}
FIXED_COLUMNS = (COL_CHECK, COL_INDEX)
# The row number and the checkbox are structural, so the menu never hides them.
PINNED_COLUMNS = (COL_INDEX, COL_CHECK)
HIDDEN_BY_DEFAULT = (COL_UPLOADER, COL_FILE, COL_URL)
# Grabber is a review list, so the download meters stay off it.
GRABBER_HIDDEN = (COL_UPLOADER, COL_FILE, COL_URL, COL_PROGRESS, COL_SPEED, COL_ETA)
RECENT_URL_LIMIT = 20
# The window is frameless, so it grows its own grab strip along the edges.
FRAME_MARGIN = 5
# How far the floating Grabber monitor sits from the corner it parks in.
FLOAT_MARGIN = 12
TAB_DOWNLOAD = 0
TAB_GRABBER = 1
EDGE_CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
}
# The status strip polls counters, so it can tick often without costing much.
STATS_INTERVAL_MS = 1500
