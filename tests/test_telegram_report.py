"""Tests for Telegram reporting helpers."""
import io
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QSettings

from app import __version__
from app.core import telegram_report
from app.core.runtime import gui_settings


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

    @patch.dict("os.environ", {"CAMDOT_TELEGRAM_REPORTS": "0"}, clear=False)
    def test_reporting_disabled_by_env(self):
        self.assertFalse(telegram_report.reporting_enabled())

    def test_github_release_notice_includes_tag_links_and_notes(self):
        text = telegram_report.format_github_release_notice(
            {
                "tag": "v0.4.0",
                "latest": "0.4.0",
                "page_url": "https://github.com/VOK-KH/CamDot/releases/tag/v0.4.0",
                "notes": "Fix tray clicks\nSkip unsupported hosts",
                "assets": [
                    {
                        "name": "CamDot-v0.4.0-Windows-x86_64-Setup.exe",
                        "url": "https://example.com/setup.exe",
                        "label": "Windows x86_64 Setup",
                    }
                ],
            }
        )
        self.assertIn("v0.4.0", text)
        self.assertIn("Windows x86_64 Setup", text)
        self.assertIn("https://example.com/setup.exe", text)
        self.assertIn("Fix tray clicks", text)
        self.assertIn("Patch notes", text)

    @patch("app.core.telegram_report._post_message")
    @patch.dict(
        "os.environ",
        {
            "CAMDOT_TELEGRAM_BOT_TOKEN": "token",
            "CAMDOT_TELEGRAM_CHAT_ID": "123",
            "CAMDOT_TELEGRAM_RELEASE_NOTICE": "1",
        },
        clear=False,
    )
    def test_notify_github_release_posts_html(self, post):
        ok = telegram_report.notify_github_release(
            {
                "tag": "v0.4.0",
                "notes": "Hello",
                "assets": [],
                "page_url": "https://github.com/VOK-KH/CamDot/releases/tag/v0.4.0",
            },
            block=True,
        )
        self.assertTrue(ok)
        post.assert_called_once()
        self.assertIn("v0.4.0", post.call_args.args[2])

    @patch("app.core.telegram_report.send_html")
    def test_notify_github_release_requires_action_flag(self, send_html):
        with patch.dict("os.environ", {"CAMDOT_TELEGRAM_RELEASE_NOTICE": ""}, clear=False):
            ok = telegram_report.notify_github_release({"tag": "v0.4.0"}, block=True)
        self.assertFalse(ok)
        send_html.assert_not_called()

    def test_reporting_respects_settings(self):
        folder = tempfile.TemporaryDirectory()
        try:
            with patch("app.core.runtime.state_dir", return_value=folder.name):
                settings = gui_settings()
                settings.setValue("telegram_reports", False)
                settings.sync()
                with patch.dict("os.environ", {}, clear=True):
                    self.assertFalse(telegram_report.reporting_enabled())
        finally:
            folder.cleanup()


if __name__ == "__main__":
    unittest.main()
