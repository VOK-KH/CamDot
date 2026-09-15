"""Tests for the Windows in-app updater."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.core import app_updater


class AppUpdaterTests(unittest.TestCase):
    def test_download_file_writes_complete_file(self):
        payload = b"setup-bytes"

        class Response:
            headers = {"Content-Length": str(len(payload))}

            def __init__(self):
                self._remaining = payload

            def read(self, size=-1):
                if not self._remaining:
                    return b""
                if size is None or size < 0:
                    chunk, self._remaining = self._remaining, b""
                else:
                    chunk = self._remaining[:size]
                    self._remaining = self._remaining[size:]
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as folder:
            dest = os.path.join(folder, "CamDot-Setup.exe")
            with patch("app.core.app_updater.urllib.request.urlopen", return_value=Response()):
                app_updater.download_file("https://example.com/setup.exe", dest)
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), payload)

    @patch("app.core.app_updater.subprocess.Popen")
    @patch("app.core.app_updater.download_file")
    @patch("app.core.app_updater.download_path")
    def test_apply_update_downloads_and_runs_installer(self, download_path, download_file, popen):
        with tempfile.TemporaryDirectory() as folder:
            dest = os.path.join(folder, "CamDot-Setup.exe")
            download_path.return_value = dest
            download_file.return_value = dest
            with open(dest, "wb") as handle:
                handle.write(b"x")
            with patch.object(sys, "platform", "win32"):
                path = app_updater.apply_update(
                    {
                        "download_url": "https://example.com/setup.exe",
                        "asset_name": "CamDot-Setup.exe",
                    }
                )
            self.assertEqual(path, dest)
            download_file.assert_called_once()
            popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
