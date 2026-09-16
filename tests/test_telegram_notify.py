"""Tests for user Telegram download notifications."""
import json
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings

from app.core import telegram_notify


def _settings(name):
    settings = QSettings("CamDotTest", name)
    settings.clear()
    return settings


START_UPDATE = {
    "update_id": 44,
    "message": {
        "text": "/start",
        "chat": {
            "id": 9001,
            "first_name": "Ada",
            "username": "ada",
        },
        "from": {"id": 9001, "first_name": "Ada", "username": "ada"},
    },
}


class TelegramNotifyTests(unittest.TestCase):
    def test_start_chats_reads_bot_start(self):
        chats = telegram_notify.start_chats([START_UPDATE, {"update_id": 45}])
        self.assertEqual(chats, [{
            "chat_id": "9001",
            "username": "ada",
            "name": "Ada",
        }])

    def test_upsert_keeps_approved_and_revives_rejected(self):
        accounts, row, is_new = telegram_notify.upsert_start([], {
            "chat_id": "1", "username": "a", "name": "A",
        })
        self.assertTrue(is_new)
        self.assertEqual(row["status"], telegram_notify.STATUS_PENDING)
        accounts[0]["status"] = telegram_notify.STATUS_APPROVED
        accounts, row, is_new = telegram_notify.upsert_start(accounts, {
            "chat_id": "1", "username": "a", "name": "A",
        })
        self.assertFalse(is_new)
        self.assertEqual(row["status"], telegram_notify.STATUS_APPROVED)
        accounts[0]["status"] = telegram_notify.STATUS_REJECTED
        accounts, row, is_new = telegram_notify.upsert_start(accounts, {
            "chat_id": "1", "username": "a", "name": "A",
        })
        self.assertTrue(is_new)
        self.assertEqual(row["status"], telegram_notify.STATUS_PENDING)

    def test_approve_and_reject(self):
        accounts = [{"chat_id": "1", "username": "a", "name": "A", "status": "pending"}]
        accounts, row = telegram_notify.set_status(
            accounts, "1", telegram_notify.STATUS_APPROVED)
        self.assertEqual(row["status"], "approved")
        self.assertEqual(telegram_notify.approved_chat_ids(accounts), ["1"])
        accounts, row = telegram_notify.set_status(
            accounts, "1", telegram_notify.STATUS_REJECTED)
        self.assertEqual(telegram_notify.approved_chat_ids(accounts), [])

    @patch("app.core.telegram_notify.fetch_updates")
    @patch("app.core.telegram_notify._reply")
    def test_poll_starts_adds_pending_account(self, reply, fetch):
        fetch.return_value = ([START_UPDATE], 45)
        accounts, offset, pending = telegram_notify.poll_starts("123:token", 0, [])
        self.assertEqual(offset, 45)
        self.assertEqual(len(pending), 1)
        self.assertEqual(accounts[0]["chat_id"], "9001")
        self.assertEqual(accounts[0]["status"], "pending")
        reply.assert_called()

    def test_notify_download_done_only_approved(self):
        settings = _settings("telegram-notify-send")
        settings.setValue(telegram_notify.SETTING_ENABLED, True)
        settings.setValue(telegram_notify.SETTING_TOKEN, "123:abc")
        telegram_notify.save_state(settings, [
            {"chat_id": "1", "username": "ok", "name": "Ok", "status": "approved"},
            {"chat_id": "2", "username": "no", "name": "No", "status": "pending"},
        ])
        with patch("app.core.telegram_notify._post_message") as post:
            ok = telegram_notify.notify_download_done(
                settings, "Downloads finished", "2 of 2 item(s) downloaded.",
                block=True,
            )
        self.assertTrue(ok)
        post.assert_called_once()
        self.assertEqual(post.call_args.args[1], "1")
        self.assertIn("Downloads finished", post.call_args.args[2])

    def test_notify_skips_when_disabled(self):
        settings = _settings("telegram-notify-off")
        settings.setValue(telegram_notify.SETTING_TOKEN, "123:abc")
        telegram_notify.save_state(settings, [
            {"chat_id": "1", "username": "ok", "name": "Ok", "status": "approved"},
        ])
        with patch("app.core.telegram_notify._post_message") as post:
            ok = telegram_notify.notify_download_done(settings, "Done", "ok", block=True)
        self.assertFalse(ok)
        post.assert_not_called()

    def test_accounts_round_trip_settings(self):
        settings = _settings("telegram-notify-store")
        telegram_notify.save_state(
            settings,
            [{"chat_id": "9", "username": "x", "name": "X", "status": "approved"}],
            offset=12,
            token="1:token",
            enabled_flag=True,
        )
        self.assertTrue(telegram_notify.enabled(settings))
        self.assertEqual(telegram_notify.bot_token(settings), "1:token")
        self.assertEqual(telegram_notify.update_offset(settings), 12)
        loaded = telegram_notify.load_accounts(settings)
        self.assertEqual(loaded[0]["chat_id"], "9")
        self.assertEqual(json.loads(settings.value(telegram_notify.SETTING_ACCOUNTS)), loaded)
