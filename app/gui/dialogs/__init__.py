"""GUI dialogs: alerts, link paste, settings, and supported platforms."""
from app.gui.dialogs.alert import ALERT_ART, alert
from app.gui.dialogs.links import AddLinksDialog
from app.gui.dialogs.platforms import PlatformsDialog
from app.gui.dialogs.settings import SettingsDialog

__all__ = [
    "ALERT_ART",
    "AddLinksDialog",
    "alert",
    "PlatformsDialog",
    "SettingsDialog",
]
