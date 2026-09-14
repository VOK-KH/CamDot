"""Tests for automatic runtime setup (no network or package changes)."""
import os
import tempfile
import unittest
from unittest.mock import patch

from app.core.runtime import (
    APP_FOLDER_NAME,
    UPDATE_PACKAGES,
    default_output_root,
    resolve_ffmpeg,
    resolve_output_root,
    runtime_versions,
    update_runtime,
)


class FakeResult:
    returncode = 0


class RuntimeTools(unittest.TestCase):
    def test_bundled_ffmpeg_exists(self):
        path = resolve_ffmpeg()
        self.assertTrue(os.path.isfile(path), path)

    def test_versions_are_available(self):
        versions = runtime_versions()
        self.assertTrue(versions["yt_dlp"])
        self.assertTrue(os.path.isfile(versions["ffmpeg"]))

    def test_configured_ffmpeg_wins(self):
        self.assertEqual(resolve_ffmpeg("C:/Tools/ffmpeg.exe"), "C:/Tools/ffmpeg.exe")

    def test_update_uses_fixed_packages_and_current_python(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return FakeResult()

        with tempfile.TemporaryDirectory() as folder:
            state = os.path.join(folder, "state.json")
            with patch("app.core.runtime.shutil.which", return_value="C:/uv.exe"):
                self.assertTrue(update_runtime(force=True, state_path=state, runner=runner))
        command = calls[0][0]
        self.assertEqual(command[0], "C:/uv.exe")
        self.assertIn("--python", command)
        for package in UPDATE_PACKAGES:
            self.assertIn(package, command)

    def test_update_is_skipped_without_uv(self):
        with patch("app.core.runtime.shutil.which", return_value=None):
            self.assertFalse(update_runtime(force=True))

    def test_windows_default_folder_is_downloads_app_name(self):
        with patch("app.core.runtime.sys.platform", "win32"):
            with patch("app.core.runtime.os.path.expanduser", return_value=r"C:\Users\DEV"):
                self.assertEqual(
                    default_output_root(),
                    os.path.join(r"C:\Users\DEV", "Downloads", APP_FOLDER_NAME),
                )

    def test_mac_default_folder_is_documents_app_name(self):
        with patch("app.core.runtime.sys.platform", "darwin"):
            with patch("app.core.runtime.os.path.expanduser", return_value="/Users/dev"):
                self.assertEqual(
                    default_output_root(),
                    os.path.join("/Users/dev", "Documents", APP_FOLDER_NAME),
                )

    def test_legacy_relative_output_upgrades_to_platform_default(self):
        self.assertEqual(resolve_output_root("output"), default_output_root())
        self.assertEqual(resolve_output_root(""), default_output_root())
        self.assertEqual(resolve_output_root(r"D:\Videos"), r"D:\Videos")


if __name__ == "__main__":
    unittest.main()
