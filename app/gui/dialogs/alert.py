"""Message boxes that wear the botty artwork instead of the Qt glyph."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from app.core import icons

# Alert kind -> the botty mascot shown in the body, and the images/dialog badge
# used as the window icon.
ALERT_ART = {
    "info": ("robot_info", "info"),
    "question": ("robot_info", "help"),
    "warning": ("robot_sos", "warning"),
    "error": ("robot_del", "error"),
}


def alert(parent, kind, title, text, buttons=QMessageBox.StandardButton.Ok, default=None,
          stay_on_top=False):
    """Show a message box wearing the botty artwork instead of the Qt glyph."""
    mascot, badge = ALERT_ART[kind]
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if default is not None:
        box.setDefaultButton(default)
    if stay_on_top:
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    box.setIconPixmap(icons.art("botty", mascot, 64))
    box.setWindowIcon(icons.art_icon("dialog", badge))
    return box.exec()
