"""Tests for cURL / cookie header parsing."""
import os
import tempfile
import unittest

from app.core.cookies import (
    cookie_domain_from_curl,
    cookie_domains_from_curl,
    cookies_from_curl,
    write_netscape_cookies,
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


if __name__ == "__main__":
    unittest.main()
