"""Tests for automatic runtime setup (no network or package changes)."""
import os
import tempfile
import unittest
from unittest.mock import patch

from app.core.runtime import (
    APP_FOLDER_NAME,
    UPDATE_PACKAGES,
    channel_state_dir,
    chrome_profile_dir,
    collect_csv_path,
    default_output_root,
    gui_settings_path,
    resolve_ffmpeg,
    resolve_output_root,
    runtime_versions,
    sweep_download_folder,
    update_runtime,
    util_cache_dir,
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

    def test_util_paths_live_under_state_dir(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.core.runtime.state_dir", return_value=folder):
                self.assertEqual(chrome_profile_dir(), os.path.join(folder, "chrome-profile"))
                self.assertEqual(
                    collect_csv_path("jireel"),
                    os.path.join(folder, "collect", "jireel.csv"),
                )
                self.assertEqual(
                    channel_state_dir("jireel"),
                    os.path.join(folder, "channels", "jireel"),
                )
                self.assertEqual(util_cache_dir(), os.path.join(folder, "cache"))
                self.assertEqual(gui_settings_path(), os.path.join(folder, "gui.ini"))

    def test_sweep_moves_csv_and_chrome_profile(self):
        with tempfile.TemporaryDirectory() as downloads, tempfile.TemporaryDirectory() as state:
            chrome = os.path.join(downloads, ".chrome-profile")
            os.makedirs(os.path.join(chrome, "Default"))
            with open(os.path.join(chrome, "Default", "Prefs"), "w", encoding="utf-8") as f:
                f.write("{}")
            with open(os.path.join(downloads, "jireel.csv"), "w", encoding="utf-8") as f:
                f.write("https://example.com/1\n")
            with open(os.path.join(downloads, "yt-dlp.csv"), "w", encoding="utf-8") as f:
                f.write("")
            cache = os.path.join(downloads, ".cache", "favicons")
            os.makedirs(cache)
            with open(os.path.join(cache, "x.ico"), "wb") as f:
                f.write(b"x")
            channel = os.path.join(downloads, "jireel")
            os.makedirs(channel)
            with open(os.path.join(channel, "list.json"), "w", encoding="utf-8") as f:
                f.write("[]")
            with open(os.path.join(channel, ".downloaded.txt"), "w", encoding="utf-8") as f:
                f.write("youtube abc\n")
            video = os.path.join(channel, "clip [abc].mp4")
            part = os.path.join(channel, "clip [def].mp4.part")
            for path in (video, part):
                with open(path, "wb") as f:
                    f.write(b"x")
            with patch("app.core.runtime.state_dir", return_value=state):
                sweep_download_folder(downloads)
            self.assertFalse(os.path.exists(os.path.join(downloads, ".chrome-profile")))
            self.assertTrue(os.path.isfile(os.path.join(state, "chrome-profile", "Default", "Prefs")))
            self.assertFalse(os.path.isfile(os.path.join(downloads, "jireel.csv")))
            self.assertTrue(os.path.isfile(os.path.join(state, "collect", "jireel.csv")))
            self.assertTrue(os.path.isfile(os.path.join(state, "collect", "yt-dlp.csv")))
            self.assertFalse(os.path.exists(os.path.join(downloads, ".cache")))
            self.assertTrue(os.path.isfile(os.path.join(state, "cache", "favicons", "x.ico")))
            self.assertFalse(os.path.isfile(os.path.join(channel, "list.json")))
            self.assertFalse(os.path.isfile(os.path.join(channel, ".downloaded.txt")))
            self.assertTrue(os.path.isfile(os.path.join(state, "channels", "jireel", "list.json")))
            self.assertTrue(os.path.isfile(os.path.join(state, "channels", "jireel", ".downloaded.txt")))
            self.assertTrue(os.path.isfile(video))
            self.assertTrue(os.path.isfile(part))


if __name__ == "__main__":
    unittest.main()
