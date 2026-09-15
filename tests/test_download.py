"""Tests for the download helpers (no network, no yt-dlp process)."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app.core.download import (
    ALL_MEDIA_KINDS,
    FORMAT_SELECTOR,
    OUTPUT_TEMPLATE,
    PINTEREST_FORMAT_SELECTOR,
    TWITTER_EXTRACTOR_ARGS,
    TWITTER_FORMAT_SELECTOR,
    _pinterest_media_fallback,
    _twitter_media_fallback,
    _yt_dlp_args,
    download_urls,
    organize_media_into_kinds,
    parse_info_line,
    parse_progress_line,
    pinterest_pin_id,
    post_label,
    read_urls,
    relocate_artifacts,
    resolve_filename_template,
    reel_id,
    source_folder_name,
    twitter_status_id,
)


class ReadUrls(unittest.TestCase):
    def test_reads_rows_in_order_without_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "channel.csv")
            with open(path, "w", newline="") as f:
                f.write("https://www.facebook.com/reel/111\n")
                f.write("https://www.facebook.com/reel/222\n")
                f.write("https://www.facebook.com/reel/111\n")
                f.write("\n")
            self.assertEqual(
                read_urls(path),
                [
                    "https://www.facebook.com/reel/111",
                    "https://www.facebook.com/reel/222",
                ],
            )


class ReelId(unittest.TestCase):
    def test_last_path_segment_is_used(self):
        self.assertEqual(reel_id("https://www.facebook.com/reel/123456/"), "123456")

    def test_youtube_watch_id_comes_from_query(self):
        self.assertEqual(reel_id("https://www.youtube.com/watch?v=dQw4w9wgGcQ"), "dQw4w9wgGcQ")

    def test_douyin_modal_id_is_used(self):
        self.assertEqual(
            reel_id("https://www.douyin.com/jingxuan?modal_id=7683008214744581018"),
            "7683008214744581018",
        )


class ParseProgressLine(unittest.TestCase):
    def test_plain_output_is_not_progress(self):
        self.assertIsNone(parse_progress_line("[download] Destination: output/a.mp4"))

    def test_percent_is_computed_from_bytes(self):
        event = parse_progress_line("@@P|512000|1024000|250000|4")
        self.assertEqual(event["status"], "downloading")
        self.assertAlmostEqual(event["percent"], 50.0)
        self.assertEqual(event["speed"], 250000)
        self.assertEqual(event["eta"], 4)

    def test_unknown_total_leaves_percent_empty(self):
        event = parse_progress_line("@@P|512000|NA|NA|NA")
        self.assertIsNone(event["percent"])
        self.assertIsNone(event["speed"])


class PostLabel(unittest.TestCase):
    def test_caption_wins_over_title(self):
        self.assertEqual(
            post_label("Name on Reels", "Hello from the post\nline two", "9"),
            "Hello from the post line two",
        )

    def test_empty_caption_uses_title(self):
        self.assertEqual(post_label("Sunset reel", "", "9"), "Sunset reel")

    def test_falls_back_to_id(self):
        self.assertEqual(post_label("", "NA", "123"), "123")


class ParseInfoLine(unittest.TestCase):
    def test_json_payload_is_flattened(self):
        line = '@@I{"id": "1", "title": "Name on Reels", "description": "Hi\\nthere", "uploader": "Ada", "duration": 12.5}'
        event = parse_info_line(line)
        self.assertEqual(event["title"], "Name on Reels")
        self.assertEqual(event["description"], "Hi there")
        self.assertEqual(event["uploader"], "Ada")
        self.assertEqual(event["duration"], 12.5)

    def test_extractor_fields_are_kept(self):
        event = parse_info_line(
            '@@I{"id": "1", "extractor_key": "Youtube", "webpage_url_domain": "youtube.com"}'
        )
        self.assertEqual(event["extractor_key"], "Youtube")
        self.assertEqual(event["platform"], "youtube")

    def test_bilibili_extractor_maps_to_platform(self):
        event = parse_info_line(
            '@@I{"id": "4794551511289856", "extractor_key": "BiliIntl", '
            '"webpage_url_domain": "bilibili.tv"}'
        )
        self.assertEqual(event["platform"], "bilibili")

    def test_douyin_extractor_maps_to_platform(self):
        event = parse_info_line(
            '@@I{"id": "7683008214744581018", "extractor_key": "Douyin", '
            '"webpage_url_domain": "douyin.com"}'
        )
        self.assertEqual(event["platform"], "douyin")

    def test_plain_output_is_ignored(self):
        self.assertIsNone(parse_info_line("[download] Destination: a.mp4"))


class YtDlpArgs(unittest.TestCase):
    def test_files_are_named_from_caption_then_id(self):
        args = _yt_dlp_args("https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt")
        self.assertIn(os.path.join("out", OUTPUT_TEMPLATE), args)
        self.assertIn("--continue", args)
        self.assertIn("--no-overwrites", args)
        self.assertEqual(args[args.index("-f") + 1], FORMAT_SELECTOR)

    def test_custom_filename_template_is_used(self):
        args = _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
            filename_template="%(id)s.%(ext)s",
        )
        self.assertIn(os.path.join("out", "%(id)s.%(ext)s"), args)
        self.assertEqual(resolve_filename_template(""), OUTPUT_TEMPLATE)
        self.assertEqual(resolve_filename_template("  "), OUTPUT_TEMPLATE)

    def test_cookies_from_browser_are_passed(self):
        args = _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
            cookies_browser="chrome:Default",
        )
        self.assertIn("--cookies-from-browser", args)
        self.assertIn("chrome:Default", args)

    def test_douyin_impersonates_chrome(self):
        args = _yt_dlp_args(
            "https://www.douyin.com/video/7683008214744581018",
            "out", 8, "out/.downloaded.txt",
        )
        self.assertIn("--impersonate", args)
        self.assertIn("chrome", args)

    def test_tiktok_dateafter_is_passed(self):
        args = _yt_dlp_args(
            "https://www.tiktok.com/@user/video/1",
            "out", 8, "out/.downloaded.txt",
            dateafter="20240101",
        )
        self.assertIn("--dateafter", args)
        self.assertIn("20240101", args)

    def test_limit_rate_is_passed_when_set(self):
        args = _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
            limit_rate="50K",
        )
        self.assertIn("--limit-rate", args)
        self.assertEqual(args[args.index("--limit-rate") + 1], "50K")

    def test_limit_rate_is_omitted_when_empty(self):
        args = _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
            limit_rate="",
        )
        self.assertNotIn("--limit-rate", args)
        self.assertNotIn("--limit-rate", _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
        ))

    def test_twitter_uses_syndication_and_fallback_format(self):
        args = _yt_dlp_args(
            "https://x.com/name/status/2085223295776100697",
            "out", 8, "out/.downloaded.txt",
        )
        self.assertEqual(args[args.index("-f") + 1], TWITTER_FORMAT_SELECTOR)
        self.assertIn("--extractor-args", args)
        self.assertEqual(args[args.index("--extractor-args") + 1], TWITTER_EXTRACTOR_ARGS)
        self.assertTrue(TWITTER_FORMAT_SELECTOR.startswith(FORMAT_SELECTOR))

    def test_pinterest_uses_image_capable_format(self):
        args = _yt_dlp_args(
            "https://www.pinterest.com/pin/123/",
            "out", 8, "out/.downloaded.txt",
        )
        self.assertEqual(args[args.index("-f") + 1], PINTEREST_FORMAT_SELECTOR)
        self.assertEqual(PINTEREST_FORMAT_SELECTOR, TWITTER_FORMAT_SELECTOR)

    def test_bilibili_keeps_merged_format(self):
        args = _yt_dlp_args(
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "out", 8, "out/.downloaded.txt",
        )
        self.assertEqual(args[args.index("-f") + 1], FORMAT_SELECTOR)
        self.assertNotIn("--extractor-args", args)

    def test_douyin_auto_cookies_from_browser_chrome(self):
        args = _yt_dlp_args(
            "https://www.douyin.com/video/7681950375104610226",
            "out", 8, "out/.downloaded.txt",
        )
        self.assertIn("--cookies-from-browser", args)
        self.assertEqual(args[args.index("--cookies-from-browser") + 1], "chrome")
        self.assertIn("--impersonate", args)

    def test_douyin_skips_auto_chrome_when_cookies_file_set(self):
        args = _yt_dlp_args(
            "https://www.douyin.com/video/7681950375104610226",
            "out", 8, "out/.downloaded.txt",
            cookies_file="extra-cookies.txt",
        )
        self.assertNotIn("--cookies-from-browser", args)
        self.assertIn("--cookies", args)
        self.assertIn("--impersonate", args)


class TwitterFallback(unittest.TestCase):
    def test_status_id_from_photo_url(self):
        self.assertEqual(
            twitter_status_id("https://x.com/name/status/2085223295776100697/photo/1"),
            "2085223295776100697",
        )

    def test_fallback_writes_jpg_from_mocked_json(self):
        tweet_id = "2085223295776100697"
        photo_url = "https://pbs.twimg.com/media/example.jpg"
        payload = json.dumps({
            "tweet": {"media": {"photos": [{"url": photo_url, "type": "photo"}]}},
        }).encode()
        jpeg = b"\xff\xd8\xff\xe0fakejpeg"

        class FakeResp:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=20):
            url = request.full_url if hasattr(request, "full_url") else request
            if "fxtwitter.com" in url:
                return FakeResp(payload)
            if url == photo_url:
                return FakeResp(jpeg)
            raise AssertionError(f"unexpected url {url}")

        with tempfile.TemporaryDirectory() as folder:
            with patch("app.core.download.urllib.request.urlopen", side_effect=fake_urlopen):
                ok = _twitter_media_fallback(
                    f"https://x.com/name/status/{tweet_id}",
                    folder,
                    archive_path=os.path.join(folder, ".downloaded.txt"),
                )
            self.assertTrue(ok)
            dest = os.path.join(folder, f"{tweet_id}.jpg")
            self.assertTrue(os.path.isfile(dest))
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), jpeg)


class PinterestFallback(unittest.TestCase):
    def test_pin_id_from_slug_url(self):
        self.assertEqual(
            pinterest_pin_id("https://www.pinterest.com/pin/cool-pin--123456789/"),
            "123456789",
        )

    def test_fallback_writes_jpg_from_mocked_pin_json(self):
        pin_id = "664281013778109217"
        image_url = "https://i.pinimg.com/originals/aa/bb/cc/example.jpg"
        payload = json.dumps({
            "resource_response": {
                "data": {
                    "id": pin_id,
                    "images": {"orig": {"url": image_url, "width": 800, "height": 600}},
                },
            },
        }).encode()
        jpeg = b"\xff\xd8\xff\xe0fakejpeg"

        class FakeResp:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=20):
            url = request.full_url if hasattr(request, "full_url") else request
            if "PinResource/get/" in url:
                handler = request.headers.get("X-pinterest-pws-handler") or request.get_header(
                    "X-Pinterest-PWS-Handler"
                )
                self.assertTrue(handler)
                return FakeResp(payload)
            if url == image_url:
                return FakeResp(jpeg)
            raise AssertionError(f"unexpected url {url}")

        with tempfile.TemporaryDirectory() as folder:
            with patch("app.core.download.urllib.request.urlopen", side_effect=fake_urlopen):
                ok = _pinterest_media_fallback(
                    f"https://www.pinterest.com/pin/{pin_id}/",
                    folder,
                    archive_path=os.path.join(folder, ".downloaded.txt"),
                )
            self.assertTrue(ok)
            dest = os.path.join(folder, f"{pin_id}.jpg")
            self.assertTrue(os.path.isfile(dest))
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), jpeg)


class SourceFolderName(unittest.TestCase):
    def test_caption_wins_over_title(self):
        self.assertEqual(
            source_folder_name("Page title", "Hello from the post", "9"),
            "Hello from the post",
        )

    def test_title_used_when_caption_missing(self):
        self.assertEqual(source_folder_name("Sunset reel", "", "9"), "Sunset reel")

    def test_illegal_windows_chars_are_stripped(self):
        self.assertEqual(
            source_folder_name("", r'a\b/c:d*e?f"g<h>i|j', "1"),
            "a b c d e f g h i j",
        )

    def test_empty_falls_back_to_hex_and_rid(self):
        name = source_folder_name("", "NA", "abc123")
        self.assertRegex(name, r"^[0-9a-f]{8}-abc123$")

    def test_empty_without_rid_is_hex_only(self):
        name = source_folder_name("", "", "")
        self.assertRegex(name, r"^[0-9a-f]{8}$")


class MediaKindArgs(unittest.TestCase):
    def test_all_kinds_extract_keep_and_thumbnail(self):
        args = _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
            media_kinds=ALL_MEDIA_KINDS,
        )
        self.assertIn("--extract-audio", args)
        self.assertIn("--keep-video", args)
        self.assertEqual(args[args.index("--audio-format") + 1], "m4a")
        self.assertIn("--write-thumbnail", args)
        self.assertEqual(args[args.index("--convert-thumbnails") + 1], "jpg")
        self.assertNotIn("--skip-download", args)

    def test_music_without_video_omits_keep_video(self):
        args = _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
            media_kinds={"music"},
        )
        self.assertIn("--extract-audio", args)
        self.assertNotIn("--keep-video", args)
        self.assertNotIn("--write-thumbnail", args)

    def test_video_only_omits_audio_and_thumb(self):
        args = _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
            media_kinds={"video"},
        )
        self.assertNotIn("--extract-audio", args)
        self.assertNotIn("--keep-video", args)
        self.assertNotIn("--write-thumbnail", args)
        self.assertNotIn("--skip-download", args)

    def test_image_only_skips_media_download(self):
        args = _yt_dlp_args(
            "https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt",
            media_kinds={"image"},
        )
        self.assertIn("--write-thumbnail", args)
        self.assertIn("--skip-download", args)
        self.assertNotIn("--extract-audio", args)


class OrganizeMedia(unittest.TestCase):
    def test_moves_finished_files_into_kind_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("clip.mp4", "song.m4a", "cover.jpg", "clip.mp4.part"):
                with open(os.path.join(folder, name), "wb") as f:
                    f.write(b"x")
            organize_media_into_kinds(folder, {"video", "music", "image"})
            self.assertTrue(os.path.isfile(os.path.join(folder, "video", "clip.mp4")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "audio", "song.m4a")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "image", "cover.jpg")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "clip.mp4.part")))


class RelocateArtifacts(unittest.TestCase):
    def test_finds_media_in_kind_subfolders(self):
        with tempfile.TemporaryDirectory() as folder:
            layout = {
                "video/clip.mp4": b"x",
                "audio/song.m4a": b"x",
                "image/cover.jpg": b"x",
                "clip.mp4.part": b"x",
                "meta.ytdl": b"x",
            }
            for rel, data in layout.items():
                path = os.path.join(folder, rel)
                os.makedirs(os.path.dirname(path) or folder, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
            found = relocate_artifacts(folder, {"video", "music", "image"})
            names = {os.path.basename(path) for path in found}
            self.assertEqual(names, {"clip.mp4", "song.m4a", "cover.jpg"})
            self.assertTrue(os.path.isfile(os.path.join(folder, "video", "clip.mp4")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "audio", "song.m4a")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "image", "cover.jpg")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "clip.mp4.part")))


class DownloadKwargs(unittest.TestCase):
    def test_download_urls_forwards_kinds_and_source_folder(self):
        captured = {}

        def fake_one(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return 0

        url = "https://www.facebook.com/reel/99"
        with tempfile.TemporaryDirectory() as downloads, tempfile.TemporaryDirectory() as state:
            with patch("app.core.runtime.state_dir", return_value=state):
                with patch("app.core.download._download_one", side_effect=fake_one):
                    failures = download_urls(
                        "jireel", [url], output_root=downloads, log=lambda *_: None,
                        media_kinds={"image"},
                        source_folders={url: "My Caption"},
                    )
        self.assertEqual(failures, 0)
        self.assertEqual(captured["args"][-2], frozenset({"image"}))
        self.assertEqual(captured["args"][-1], "My Caption")


    def test_download_urls_skips_source_folder_when_grouping_disabled(self):
        captured = {}

        def fake_one(*args, **kwargs):
            captured["source_folder"] = args[-1]
            return 0

        url = "https://www.facebook.com/reel/99"
        with tempfile.TemporaryDirectory() as downloads, tempfile.TemporaryDirectory() as state:
            with patch("app.core.runtime.state_dir", return_value=state):
                with patch("app.core.download._download_one", side_effect=fake_one):
                    failures = download_urls(
                        "jireel",
                        [url],
                        output_root=downloads,
                        log=lambda *_: None,
                        group_by_source=False,
                    )
        self.assertEqual(failures, 0)
        self.assertEqual(captured["source_folder"], "")


class DownloadLayout(unittest.TestCase):
    def test_empty_download_keeps_media_dir_under_output_root(self):
        with tempfile.TemporaryDirectory() as downloads, tempfile.TemporaryDirectory() as state:
            with patch("app.core.runtime.state_dir", return_value=state):
                failures = download_urls(
                    "jireel", [], output_root=downloads, log=lambda *_: None,
                )
            self.assertEqual(failures, 0)
            self.assertTrue(os.path.isdir(os.path.join(downloads, "jireel")))
            self.assertFalse(os.path.isfile(os.path.join(downloads, "jireel", ".downloaded.txt")))
            self.assertTrue(os.path.isdir(os.path.join(state, "channels", "jireel")))
            self.assertFalse(os.path.isfile(os.path.join(downloads, "jireel.csv")))


if __name__ == "__main__":
    unittest.main()
