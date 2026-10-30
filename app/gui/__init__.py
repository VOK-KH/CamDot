"""PySide6 desktop UI package.

Modular architecture:

    app/gui/window.py       MainWindow orchestrator and run_gui entrypoint
    app/gui/ui/             Window chrome, tables/columns, menus, and theme/locale mixins
    app/gui/worker/         Job runner, Grabber sync queue, and app/tool update mixins
    app/gui/utils/          Tree expand/scroll state, row/file actions, and settings persistence
    app/gui/constants.py    Table/tab/frame constants
    app/gui/helpers.py      Channel names and recent URLs
    app/gui/jobs.py         Background collect/download QObject worker
    app/gui/dialogs/        Modal dialogs (Settings, Supported Platforms, Add Links, Alert, Feedback)
    app/gui/widgets/        Tree proxy, delegates, header, progress bar, Overview, Grabber, tray

Backend pipeline lives in app/core/.
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
