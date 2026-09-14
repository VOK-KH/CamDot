"""Tests for the download helpers (no network, no yt-dlp process)."""
import os
import tempfile
import unittest

from app.core.download import (
    OUTPUT_TEMPLATE,
    _yt_dlp_args,
    parse_info_line,
    parse_progress_line,
    post_label,
    read_urls,
    resolve_filename_template,
    reel_id,
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

    def test_plain_output_is_ignored(self):
        self.assertIsNone(parse_info_line("[download] Destination: a.mp4"))


class YtDlpArgs(unittest.TestCase):
    def test_files_are_named_from_caption_then_id(self):
        args = _yt_dlp_args("https://www.facebook.com/reel/1", "out", 8, "out/.downloaded.txt")
        self.assertIn(os.path.join("out", OUTPUT_TEMPLATE), args)
        self.assertIn("--continue", args)
        self.assertIn("--no-overwrites", args)

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


if __name__ == "__main__":
    unittest.main()
