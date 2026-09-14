"""Tests for host icons (no network)."""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.platform_icons import fetch_favicon, icon_for, platform_from_extractor


class FakeResponse:
    def __init__(self, data, url):
        self._data = data
        self._url = url

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._data[:n] if n > 0 else self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PlatformFromExtractor(unittest.TestCase):
    def test_extractor_key_and_domain(self):
        self.assertEqual(platform_from_extractor("Youtube"), "youtube")
        self.assertEqual(platform_from_extractor("vm.tiktok"), "tiktok")
        self.assertEqual(platform_from_extractor("", "x.com"), "twitter")
        self.assertEqual(platform_from_extractor("", "www.facebook.com"), "facebook")


class FaviconFetch(unittest.TestCase):
    def test_writes_cache_from_allowlisted_host(self):
        payload = b"icon-bytes"

        def opener(request, timeout=5):
            self.assertIn("icons.duckduckgo.com", request.full_url)
            return FakeResponse(payload, "https://icons.duckduckgo.com/ip3/example.com.ico")

        with tempfile.TemporaryDirectory() as folder:
            path = fetch_favicon("example.com", folder, opener=opener)
            self.assertTrue(os.path.isfile(path))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), payload)

    def test_rejects_redirect_off_allowlist(self):
        def opener(request, timeout=5):
            return FakeResponse(b"nope", "https://evil.example/steal.ico")

        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(fetch_favicon("example.com", folder, opener=opener), "")

    def test_invalid_domain_is_ignored(self):
        self.assertEqual(fetch_favicon("../etc", "/tmp"), "")


class BundledIcon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_known_platform_icon_renders(self):
        self.assertFalse(icon_for("youtube").isNull())
        self.assertFalse(icon_for("twitter").isNull())


if __name__ == "__main__":
    unittest.main()
