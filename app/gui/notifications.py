"""Native desktop notifications (macOS Notification Center via the tray icon)."""
import os
import sys

from PySide6.QtWidgets import QSystemTrayIcon


def use_grabber_notifications():
    """macOS uses Notification Center; tests/offscreen keep the floating monitor."""
    if sys.platform != "darwin":
        return False
    return os.environ.get("QT_QPA_PLATFORM", "").lower() != "offscreen"


def notify(window, title, message, ms=5000):
    """Post a system notification when the tray icon is available."""
    tray = getattr(window, "tray", None)
    if tray is None:
        return False
    return tray.notify(title, message, ms=ms)
