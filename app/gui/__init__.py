"""PySide6 desktop UI package.

Layout (jobs a CTO-style agent can own independently):

    app/gui/constants.py   table/tab/frame numbers
    app/gui/helpers.py    channel names and recent URLs
    app/gui/jobs.py       background collect/download worker
    app/gui/window.py     MainWindow and run_gui
    app/gui/dialogs/      alerts and settings
    app/gui/widgets/      table header, progress bar, Overview, Grabber monitor

Download logic lives in app/core/.
"""
from app.gui.constants import COLUMN_WIDTHS
from app.gui.dialogs.alert import ALERT_ART, alert
from app.gui.helpers import derive_channel, remember_recent
from app.gui.window import MainWindow, main, run_gui

__all__ = [
    "ALERT_ART",
    "COLUMN_WIDTHS",
    "MainWindow",
    "alert",
    "derive_channel",
    "main",
    "remember_recent",
    "run_gui",
]
