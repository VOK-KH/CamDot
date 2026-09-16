"""Message boxes that wear the botty artwork instead of the Qt glyph."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QMessageBox

from app.core import icons
from app.gui.widgets.loader import BOTTY_DONE, BottyClip

# Alert kind -> the botty mascot shown in the body, and the images/dialog badge
# used as the window icon.
ALERT_ART = {
    "info": ("robot_info", "info"),
    "question": ("robot_info", "help"),
    "warning": ("robot_sos", "warning"),
    "error": ("robot_del", "error"),
    "done": ("robot_info", "info"),
}
ALERT_CLIPS = {
    "done": BOTTY_DONE,
}


def build_alert(parent, kind, title, text, buttons=QMessageBox.StandardButton.Ok,
                default=None, stay_on_top=False):
    """Build a themed message box. `alert()` shows it; tests inspect it first."""
    mascot, badge = ALERT_ART[kind]
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if default is not None:
        box.setDefaultButton(default)
    if stay_on_top:
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    box.setWindowIcon(icons.art_icon("dialog", badge))
    clip_name = ALERT_CLIPS.get(kind)
    if clip_name:
        box.setIcon(QMessageBox.Icon.NoIcon)
        clip = BottyClip(box, clip=clip_name, fallback=mascot)
        layout = box.layout()
        if isinstance(layout, QGridLayout):
            layout.addWidget(clip, 0, 0, Qt.AlignmentFlag.AlignTop)
        else:
            layout.addWidget(clip)
        clip.start()
        box.finished.connect(lambda *_: clip.stop())
    else:
        box.setIconPixmap(icons.art("botty", mascot, 64))
    return box


def alert(parent, kind, title, text, buttons=QMessageBox.StandardButton.Ok, default=None,
          stay_on_top=False):
    """Show a message box wearing the botty artwork instead of the Qt glyph."""
    return build_alert(
        parent, kind, title, text, buttons=buttons, default=default,
        stay_on_top=stay_on_top,
    ).exec()
