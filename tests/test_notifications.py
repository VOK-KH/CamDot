"""Desktop notification helpers."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.gui import window as window_module
from app.gui.notifications import use_grabber_notifications


class GrabberNotifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        from app.core.i18n import apply_language
        apply_language("en")

    def test_offscreen_tests_keep_the_floating_monitor(self):
        self.assertFalse(use_grabber_notifications())

    @patch.object(window_module, "use_grabber_notifications", return_value=True)
    def test_mac_grabber_run_posts_begin_and_end_notifications(self, _flag):
        window = window_module.MainWindow()
        window._grabber_job = True
        window._grab_added = 2
        window._grab_dupes = 1
        window.grab_model.add_entries([{"url": "https://example.com/1"}])
        with patch.object(window.tray, "notify", return_value=True) as posted:
            window._show_grab_panel("Analyzing…", begin=True)
            self.assertTrue(window.grab_panel.isHidden())
            posted.assert_called_once_with("Parse Clipboard", "Analyzing…", ms=5000)
            window._end_grab_panel("Done!")
            self.assertEqual(posted.call_count, 2)
            self.assertEqual(posted.call_args_list[1].args[0], "Parse Clipboard — Done!")

    @patch.object(window_module, "use_grabber_notifications", return_value=True)
    def test_mac_show_monitor_still_uses_the_panel(self, _flag):
        window = window_module.MainWindow()
        window._show_grab_monitor()
        self.assertFalse(window.grab_panel.isHidden())
