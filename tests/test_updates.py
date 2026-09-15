"""Tests for GitHub release update checks."""
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from app.core import updates


class UpdateChecks(unittest.TestCase):
    def test_parse_and_compare_versions(self):
        self.assertTrue(updates.is_newer("0.3.0", "0.2.0"))
        self.assertFalse(updates.is_newer("0.2.0", "0.2.0"))
        self.assertFalse(updates.is_newer("0.1.9", "0.2.0"))

    def test_asset_for_platform(self):
        release = {
            "assets": [
                {"name": "CamDot-v0.3.0-Windows-x86_64.exe", "browser_download_url": "https://x/portable"},
                {"name": "CamDot-v0.3.0-Windows-x86_64-Setup.exe", "browser_download_url": "https://x/setup"},
                {"name": "CamDot-v0.3.0-Linux-x86_64.tar.gz", "browser_download_url": "https://x/linux"},
            ]
        }
        with patch.object(updates, "platform_label", return_value="Windows"):
            with patch.object(updates, "arch_label", return_value="x86_64"):
                name, url = updates.asset_for_platform(release)
        self.assertEqual(name, "CamDot-v0.3.0-Windows-x86_64-Setup.exe")
        self.assertEqual(url, "https://x/setup")

    def test_check_for_update_returns_none_when_current(self):
        payload = json.dumps({"tag_name": "v0.2.0", "assets": []}).encode()
        with patch.object(updates, "_request_json", return_value=json.loads(payload)):
            with patch.object(updates, "__version__", "0.2.0"):
                self.assertIsNone(updates.check_for_update())

    def test_check_for_update_finds_newer_release(self):
        payload = {
            "tag_name": "v0.3.0",
            "html_url": "https://github.com/VOK-KH/CamDot/releases/tag/v0.3.0",
            "body": "Bug fixes",
            "assets": [
                {
                    "name": "CamDot-v0.3.0-Windows-x86_64.exe",
                    "browser_download_url": "https://example.com/win.exe",
                }
            ],
        }
        with patch.object(updates, "_request_json", return_value=payload):
            with patch.object(updates, "__version__", "0.2.0"):
                with patch.object(updates, "platform_label", return_value="Windows"):
                    with patch.object(updates, "arch_label", return_value="x86_64"):
                        info = updates.check_for_update()
        self.assertEqual(info["latest"], "0.3.0")
        self.assertEqual(info["tag"], "v0.3.0")
        self.assertEqual(info["download_url"], "https://example.com/win.exe")
        self.assertEqual(len(info["assets"]), 1)

    def test_asset_label_and_listed_assets(self):
        self.assertEqual(
            updates.asset_label("CamDot-v0.3.0-Windows-x86_64-Setup.exe"),
            "Windows x86_64 Setup",
        )
        self.assertEqual(
            updates.asset_label("CamDot-v0.3.0-Windows-x86_64.exe"),
            "Windows x86_64 portable",
        )
        release = {
            "tag_name": "v0.4.0",
            "html_url": "https://github.com/VOK-KH/CamDot/releases/tag/v0.4.0",
            "body": "- Fix tray\n- Skip unknown hosts",
            "assets": [
                {
                    "name": "CamDot-v0.4.0-Windows-x86_64-Setup.exe",
                    "browser_download_url": "https://example.com/setup.exe",
                },
                {
                    "name": "CamDot-v0.4.0-Linux-x86_64.tar.gz",
                    "browser_download_url": "https://example.com/linux.tgz",
                },
            ],
        }
        with patch.object(updates, "platform_label", return_value="Windows"):
            with patch.object(updates, "arch_label", return_value="x86_64"):
                info = updates.parse_release(release, current="0.3.0")
        self.assertEqual(info["tag"], "v0.4.0")
        self.assertEqual(info["notes"], "- Fix tray\n- Skip unknown hosts")
        labels = [row["label"] for row in info["assets"]]
        self.assertEqual(labels, ["Windows x86_64 Setup", "Linux x86_64 tarball"])

    def test_format_update_prompt(self):
        text = updates.format_update_prompt(
            {
                "current": "0.2.1",
                "latest": "0.2.2",
                "asset_name": "CamDot-v0.2.2-Windows-x86_64-Setup.exe",
                "notes": "Bug fixes",
            }
        )
        self.assertIn("0.2.1", text)
        self.assertIn("0.2.2", text)
        self.assertIn("Setup.exe", text)
        self.assertIn("Bug fixes", text)

    def test_should_offer_update_respects_skip_and_snooze(self):
        info = {"latest": "0.3.0"}
        settings = MagicMock()
        settings.value.side_effect = lambda key, default="", *_: {
            "skipped_update_version": "0.3.0",
            "update_remind_after": 0,
        }.get(key, default)
        self.assertFalse(updates.should_offer_update(info, settings))

        settings.value.side_effect = lambda key, default="", *_: {
            "skipped_update_version": "",
            "update_remind_after": time.time() + 3600,
        }.get(key, default)
        self.assertFalse(updates.should_offer_update(info, settings))

        settings.value.side_effect = lambda key, default="", *_: {
            "skipped_update_version": "",
            "update_remind_after": 0,
        }.get(key, default)
        self.assertTrue(updates.should_offer_update(info, settings))


if __name__ == "__main__":
    unittest.main()
