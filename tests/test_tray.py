"""System tray hide-to-background behaviour (offscreen, no visible tray)."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app.gui.window import MainWindow
from app.gui.dialogs.settings import SettingsDialog


class FakeThread:
    def __init__(self):
        self.asked = False

    def isRunning(self):
        return True

    def quit(self):
        self.asked = True

    def wait(self, _timeout=0):
        return True


class FakeWorker:
    def __init__(self):
        self.stopped = False

    def request_stop(self):
        self.stopped = True


class TrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.state_folder = tempfile.TemporaryDirectory()
        settings = QSettings(
            os.path.join(self.folder.name, "test.ini"), QSettings.Format.IniFormat
        )
        settings.setValue("output_root", self.folder.name)
        settings.setValue("link_grabber", False)
        settings.setValue("close_to_tray", True)
        self._state_patch = patch(
            "app.core.runtime.state_dir", return_value=self.state_folder.name
        )
        self._state_patch.start()
        self.window = MainWindow(settings=settings)

    def tearDown(self):
        self.window._quitting = True
        self.window.close()
        self.window.deleteLater()
        QApplication.processEvents()
        self._state_patch.stop()
        self.folder.cleanup()
        self.state_folder.cleanup()

    def test_window_owns_a_tray_icon_and_menu(self):
        tray = self.window.tray
        icon = getattr(tray, "icon", tray)
        self.assertIsInstance(icon, QSystemTrayIcon)
        titles = [action.text() for action in tray.menu.actions() if action.text()]
        for name in (
            "Show window",
            "Start Downloads",
            "Clipboard monitoring",
            "Exit",
        ):
            self.assertIn(name, titles)
        self.assertIn("CamDot", icon.toolTip())

    def test_close_hides_when_tray_available(self):
        self.window._thread = FakeThread()
        self.window._worker = FakeWorker()
        with patch(
            "app.gui.widgets.tray.TrayController._can_show",
            return_value=True,
        ):
            self.window._sync_close_tooltip()
            self.assertEqual(self.window.close_btn.toolTip(), "Close to tray")
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertFalse(event.isAccepted())
            self.assertTrue(self.window.isHidden())
            self.assertFalse(self.window._worker.stopped)
            self.assertFalse(self.window._thread.asked)
            self.assertTrue(self.window._stats_timer.isActive())
            self.assertFalse(self.window._quitting)

            with patch.object(QApplication, "quit") as quit_app:
                self.window._quit_application()
            quit_app.assert_called_once()
            self.assertTrue(self.window._quitting)
            self.assertTrue(self.window._worker.stopped)
            self.assertTrue(self.window._thread.asked)
            self.assertFalse(self.window._stats_timer.isActive())
        self.window._thread = None
        self.window._worker = None

    def test_close_shuts_down_when_tray_unavailable(self):
        self.window._thread = FakeThread()
        self.window._worker = FakeWorker()
        with patch(
            "app.gui.widgets.tray.TrayController._can_show",
            return_value=False,
        ):
            self.window._sync_close_tooltip()
            self.assertEqual(self.window.close_btn.toolTip(), "Quit")
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertTrue(event.isAccepted())
            self.assertTrue(self.window._quitting)
            self.assertTrue(self.window._worker.stopped)
            self.assertTrue(self.window._thread.asked)
            self.assertFalse(self.window._stats_timer.isActive())
        self.window._thread = None
        self.window._worker = None

    def test_clipboard_tray_action_toggles_grabber(self):
        self.assertFalse(self.window.act_grabber.isChecked())
        self.window.tray.act_clipboard.setChecked(True)
        self.assertTrue(self.window.act_grabber.isChecked())
        self.window._toggle_grabber(False)
        self.assertFalse(self.window.tray.act_clipboard.isChecked())

    def test_show_window_restores_a_hidden_window(self):
        self.window.hide()
        self.window.tray.show_window()
        self.assertFalse(self.window.isHidden())

    def test_tray_trigger_and_double_click_reuse_the_same_window(self):
        self.window.hide()
        tray = self.window.tray
        tray._activated(QSystemTrayIcon.ActivationReason.Trigger)
        tray._activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        self.assertFalse(self.window.isHidden())
        self.assertIs(tray.window, self.window)

    def test_settings_checkbox_persists_close_to_tray(self):
        dialog = SettingsDialog(self.window._settings, self.window)
        self.assertTrue(dialog.close_to_tray.isChecked())
        dialog.close_to_tray.setChecked(False)
        dialog.accept()
        self.assertFalse(self.window._settings.value("close_to_tray", True, bool))
        again = SettingsDialog(self.window._settings, self.window)
        self.assertFalse(again.close_to_tray.isChecked())
        again.close_to_tray.setChecked(True)
        again.restore_defaults()
        self.assertTrue(again.close_to_tray.isChecked())


if __name__ == "__main__":
    unittest.main()
