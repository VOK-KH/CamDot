"""Tests for cURL / cookie header parsing."""
import json
import os
import tempfile
import unittest

from app.core.cookies import (
    cookie_domain_from_curl,
    cookie_domains_from_curl,
    cookies_from_curl,
    list_cookie_profile_choices,
    prepare_cookies_file,
    read_json_cookies,
    write_netscape_cookies,
    write_netscape_from_json,
)


class CookiesFromCurl(unittest.TestCase):
    def test_header_flag(self):
        curl = "curl 'https://www.kuaishou.com/short-video/1' -H 'cookie: a=1; b=2'"
        self.assertEqual(cookies_from_curl(curl), "a=1; b=2")
        self.assertEqual(cookie_domain_from_curl(curl), ".kuaishou.com")

    def test_raw_cookie_line(self):
        self.assertEqual(cookies_from_curl("did=abc; clientid=1"), "did=abc; clientid=1")

    def test_writes_netscape_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "c.txt")
            wrote = write_netscape_cookies(
                "curl 'https://www.kuaishou.com/x' -H 'cookie: did=abc'",
                path=path,
            )
            self.assertEqual(wrote, path)
            with open(path, encoding="utf-8") as f:
                body = f.read()
            self.assertIn("did\tabc", body)
            self.assertIn(".kuaishou.com", body)

    def test_douyin_curl_uses_douyin_domain(self):
        curl = "curl 'https://www.douyin.com/video/1' -H 'cookie: s_v_web_id=abc'"
        self.assertEqual(cookie_domains_from_curl(curl), [".douyin.com"])
        self.assertEqual(cookie_domain_from_curl(curl), ".douyin.com")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "c.txt")
            write_netscape_cookies(curl, path=path)
            with open(path, encoding="utf-8") as f:
                body = f.read()
            self.assertIn(".douyin.com", body)
            self.assertNotIn(".kuaishou.com", body)

    def test_raw_cookie_line_writes_douyin_and_kuaishou(self):
        self.assertEqual(
            cookie_domains_from_curl("s_v_web_id=abc; ttwid=1"),
            [".douyin.com", ".kuaishou.com"],
        )
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "c.txt")
            write_netscape_cookies("s_v_web_id=abc", path=path)
            with open(path, encoding="utf-8") as f:
                body = f.read()
            self.assertIn(".douyin.com\tTRUE\t/\tFALSE\t0\ts_v_web_id\tabc", body)
            self.assertIn(".kuaishou.com\tTRUE\t/\tFALSE\t0\ts_v_web_id\tabc", body)

    def test_json_export_writes_netscape_for_ytdlp(self):
        sample = [{
            "domain": ".tiktok.com",
            "expirationDate": 1824440837.345269,
            "hostOnly": False,
            "httpOnly": False,
            "name": "ttwid",
            "path": "/",
            "secure": True,
            "session": False,
            "value": "abc123",
        }]
        with tempfile.TemporaryDirectory() as folder:
            json_path = os.path.join(folder, "cookies_www.tiktok.com.json")
            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump(sample, handle)
            self.assertEqual(len(read_json_cookies(json_path)), 1)
            out = os.path.join(folder, "netscape.txt")
            wrote = write_netscape_from_json(read_json_cookies(json_path), out)
            self.assertEqual(wrote, out)
            with open(out, encoding="utf-8") as handle:
                body = handle.read()
            self.assertIn(".tiktok.com\tTRUE\t/\tTRUE\t1824440837\tttwid\tabc123", body)

    def test_vok_profiles_lists_accounts_and_merges_or_picks_one(self):
        payload = {
            "__type": "vok-profiles",
            "profiles": {
                "p_a": {
                    "id": "p_a",
                    "name": "tiktok",
                    "domain": "www.tiktok.com",
                    "cookies": [{"domain": ".tiktok.com", "name": "a", "value": "1"}],
                },
                "p_b": {
                    "id": "p_b",
                    "name": "yt",
                    "domain": "www.youtube.com",
                    "cookies": [{"domain": ".youtube.com", "name": "b", "value": "2"}],
                },
            },
        }
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "profiles.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            self.assertEqual(
                list_cookie_profile_choices(path),
                [
                    ("p_a", "tiktok (www.tiktok.com)", "www.tiktok.com"),
                    ("p_b", "yt (www.youtube.com)", "www.youtube.com"),
                ],
            )
            merged = read_json_cookies(path)
            self.assertEqual(len(merged), 2)
            one = read_json_cookies(path, profile_id="p_a")
            self.assertEqual(len(one), 1)
            self.assertEqual(one[0]["name"], "a")

    def test_prepare_cookies_prefers_json_file_over_curl(self):
        sample = [{
            "domain": "www.tiktok.com",
            "hostOnly": True,
            "name": "msToken",
            "path": "/",
            "secure": False,
            "session": True,
            "value": "from-json",
        }]
        with tempfile.TemporaryDirectory() as folder:
            json_path = os.path.join(folder, "export.json")
            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump(sample, handle)
            with patch_state_dir(folder):
                path = prepare_cookies_file(
                    curl_text="curl -H 'cookie: stale=1'",
                    json_path=json_path,
                )
            self.assertTrue(path)
            with open(path, encoding="utf-8") as handle:
                body = handle.read()
            self.assertIn("msToken\tfrom-json", body)
            self.assertNotIn("stale", body)


def patch_state_dir(folder):
    from unittest.mock import patch
    return patch("app.core.cookies.state_dir", return_value=folder)


if __name__ == "__main__":
    unittest.main()
