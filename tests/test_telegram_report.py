"""Tests for Telegram reporting helpers."""
import io
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QSettings

from app import __version__
from app.core import telegram_report


class TelegramReportTests(unittest.TestCase):
    def test_device_id_created_once(self):
        settings = QSettings("CamDotTest", "telegram")
        settings.clear()
        first = telegram_report.device_id_from_settings(settings)
        second = telegram_report.device_id_from_settings(settings)
        self.assertEqual(first, second)
        self.assertTrue(len(first) >= 32)

    def test_format_message_includes_event(self):
        text = telegram_report._format_message("crash", "Boom", "details", {"version": "1.0"})
        self.assertIn("Crash", text)
        self.assertIn("💥", text)
        self.assertIn("Boom", text)
        self.assertIn("1.0", text)
        self.assertIn("📦", text)

    @patch.dict(
        "os.environ",
        {"CAMDOT_TELEGRAM_BOT_TOKEN": "token", "CAMDOT_TELEGRAM_CHAT_ID": "123"},
        clear=False,
    )
    @patch("app.core.telegram_report.urllib.request.urlopen")
    def test_send_report_posts_message(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        settings = QSettings("CamDotTest", "telegram-send")
        settings.clear()
        device_id = telegram_report.device_id_from_settings(settings)
        ok = telegram_report.send_report(
            telegram_report.EVENT_FEEDBACK,
            "Hello",
            "Body",
            device_id=device_id,
            block=True,
        )
        self.assertTrue(ok)
        urlopen.assert_called_once()
        request = urlopen.call_args[0][0]
        self.assertIn("sendMessage", request.full_url)

    @patch.dict("os.environ", {}, clear=True)
    @patch("app.core.telegram_report.telegram_secrets", None)
    def test_send_report_without_credentials(self):
        ok = telegram_report.send_report("crash", "x", block=True)
        self.assertFalse(ok)

    @patch("app.core.telegram_report.send_report")
    def test_report_launch_first_and_version(self, send_report):
        settings = QSettings("CamDotTest", "telegram-launch")
        settings.clear()
        device_id = "test-device"
        telegram_report.report_launch(settings, device_id)
        self.assertTrue(settings.value("first_activate_reported", False, bool))
        self.assertEqual(settings.value("telegram_last_launch_version", "", str), __version__)
        events = [call.args[0] for call in send_report.call_args_list]
        self.assertIn(telegram_report.EVENT_FIRST_ACTIVATE, events)
        self.assertIn(telegram_report.EVENT_VERSION_LAUNCH, events)

    @patch("app.core.telegram_report.send_report")
    def test_report_crash(self, send_report):
        telegram_report.report_crash(ValueError, ValueError("bad"), None, device_id="dev")
        send_report.assert_called_once()
        self.assertEqual(send_report.call_args.args[0], telegram_report.EVENT_CRASH)


if __name__ == "__main__":
    unittest.main()
