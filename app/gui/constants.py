"""Layout constants shared by the window, tables, and widgets."""
import sys

from PySide6.QtCore import Qt

# Windows keeps the custom title strip; macOS/Linux use native window chrome.
CUSTOM_WINDOW_CHROME = sys.platform == "win32"

from app.core.model import (
    COL_ADDED,
    COL_CHECK,
    COL_DURATION,
    COL_ETA,
    COL_FILE,
    COL_HOST,
    COL_ICON,
    COL_ID,
    COL_INDEX,
    COL_PROGRESS,
    COL_SIZE,
    COL_SPEED,
    COL_STATUS,
    COL_TITLE,
    COL_UPLOADER,
    COL_URL,
    COL_VARIANT,
)

COLUMN_WIDTHS = {
    COL_CHECK: 28, COL_ICON: 28, COL_HOST: 46, COL_INDEX: 38, COL_STATUS: 96,
    COL_PROGRESS: 120, COL_TITLE: 260, COL_VARIANT: 136, COL_UPLOADER: 130, COL_ID: 96,
    COL_SIZE: 70, COL_DURATION: 58, COL_SPEED: 78, COL_ETA: 48, COL_FILE: 180,
    COL_URL: 190, COL_ADDED: 120,
}
FIXED_COLUMNS = (COL_CHECK, COL_INDEX, COL_ICON)
PINNED_COLUMNS = (COL_INDEX, COL_CHECK, COL_ICON)
HIDDEN_BY_DEFAULT = (COL_UPLOADER, COL_URL)
# Grabber is a review list, so the download meters stay off it.
GRABBER_HIDDEN = (COL_UPLOADER, COL_URL, COL_PROGRESS, COL_SPEED, COL_ETA)
# Grabber collect queue: how many packages to paint per timer tick.
GRAB_SYNC_CHUNK = 32
GRAB_SYNC_MS = 16
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
