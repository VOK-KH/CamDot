"""Tests for collect routing (mocked yt-dlp, no browser)."""
import os
import tempfile
import unittest
from unittest.mock import patch

from app.core.collect import (
    cached_tiktok_sec_uid,
    collect_entries,
    cookies_from_browser_value,
    entry_from_info,
    remember_tiktok_user,
    tiktok_username_for_sec_uid,
)

SEC_UID = "MS4wLjABAAAAbur-JVGxoTBCrLVUoAFqWcFn7hiIevluwN0k_LaB4U8q3tQizemnqCpb6thhVdXQ"


class CookiesFromBrowser(unittest.TestCase):
    def test_empty_when_unset(self):
        self.assertEqual(cookies_from_browser_value(""), "")
        self.assertEqual(cookies_from_browser_value("none"), "")

    def test_browser_and_profile(self):
        self.assertEqual(cookies_from_browser_value("chrome"), "chrome")
        self.assertEqual(cookies_from_browser_value("chrome", "Default"), "chrome:Default")


class EntryFromInfo(unittest.TestCase):
    def test_prefers_webpage_url_and_caption(self):
        entry = entry_from_info({
            "webpage_url": "https://www.youtube.com/watch?v=abc",
            "id": "abc",
            "title": "Watch me",
            "description": "A caption",
            "uploader": "Ada",
            "duration": 12,
            "extractor_key": "Youtube",
            "webpage_url_domain": "youtube.com",
        })
        self.assertEqual(entry["url"], "https://www.youtube.com/watch?v=abc")
        self.assertEqual(entry["platform"], "youtube")
        self.assertEqual(entry["title"], "Watch me")
        self.assertEqual(entry["description"], "A caption")


class CollectEntries(unittest.TestCase):
    def test_instagram_profile_raises_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                collect_entries("x", "https://www.instagram.com/someone/", output_root=folder)

    def test_x_timeline_raises_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                collect_entries("x", "https://x.com/name", output_root=folder)

    def test_single_post_uses_extract_info(self):
        class FakeYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {
                    "_type": "video",
                    "webpage_url": url,
                    "id": "abc",
                    "title": "A video",
                    "description": "",
                    "uploader": "Ada",
                    "duration": 9,
                    "extractor_key": "Youtube",
                }

        with tempfile.TemporaryDirectory() as folder:
            path, entries = collect_entries(
                "yt",
                "https://www.youtube.com/watch?v=abc",
                output_root=folder,
                ydl_cls=FakeYDL,
                log=lambda *_: None,
            )
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "abc")
            self.assertEqual(entries[0]["uploader"], "Ada")

    def test_on_entries_streams_a_single_post(self):
        class FakeYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {
                    "_type": "video",
                    "webpage_url": url,
                    "id": "abc",
                    "title": "A video",
                    "uploader": "Ada",
                    "extractor_key": "Youtube",
                }

        streamed = []
        with tempfile.TemporaryDirectory() as folder:
            _, entries = collect_entries(
                "yt",
                "https://www.youtube.com/watch?v=abc",
                output_root=folder,
                ydl_cls=FakeYDL,
                log=lambda *_: None,
                on_entries=streamed.extend,
            )
        self.assertEqual(len(entries), 1)
        self.assertEqual(streamed, entries)

    def test_feed_flattens_then_enriches(self):
        calls = []

        class FakeYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                calls.append((url, self.opts.get("extract_flat")))
                if self.opts.get("extract_flat"):
                    return {
                        "_type": "playlist",
                        "entries": [
                            {"id": "aaa", "ie_key": "Youtube", "title": "one"},
                            {"id": "bbb", "ie_key": "Youtube", "title": "two"},
                        ],
                    }
                vid = url.rsplit("=", 1)[-1]
                return {
                    "webpage_url": url,
                    "id": vid,
                    "title": vid.upper(),
                    "uploader": "Ada",
                    "extractor_key": "Youtube",
                }

        with tempfile.TemporaryDirectory() as folder:
            _, entries = collect_entries(
                "yt",
                "https://www.youtube.com/@handle/videos",
                output_root=folder,
                ydl_cls=FakeYDL,
                log=lambda *_: None,
            )
        self.assertEqual([e["id"] for e in entries], ["aaa", "bbb"])
        self.assertTrue(any(flat for _, flat in calls if flat))

    def test_throttled_feed_item_is_retried_before_giving_up(self):
        attempts = {"count": 0}

        class FlakyYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                if self.opts.get("extract_flat"):
                    return {
                        "_type": "playlist",
                        "entries": [{
                            "id": "7673240659817401630",
                            "ie_key": "TikTok",
                            "url": "https://www.tiktok.com/@who/video/7673240659817401630",
                        }],
                    }
                attempts["count"] += 1
                if attempts["count"] < 2:
                    raise RuntimeError("Unable to extract universal data for rehydration")
                return {
                    "webpage_url": url,
                    "id": "7673240659817401630",
                    "title": "Late but fine",
                    "uploader": "viralfinds__hub",
                    "extractor_key": "TikTok",
                }

        with tempfile.TemporaryDirectory() as folder:
            _, entries = collect_entries(
                "tt",
                "https://www.tiktok.com/@who",
                output_root=folder,
                ydl_cls=FlakyYDL,
                log=lambda *_: None,
                sleep=lambda _: None,
            )
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(entries[0]["title"], "Late but fine")
        self.assertEqual(entries[0]["uploader"], "viralfinds__hub")

    def test_feed_item_survives_when_every_retry_is_throttled(self):
        class BlockedYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                if self.opts.get("extract_flat"):
                    return {
                        "_type": "playlist",
                        "entries": [{
                            "id": "7676225066660662558",
                            "ie_key": "TikTok",
                            "url": "https://www.tiktok.com/@who/video/7676225066660662558",
                        }],
                    }
                return None

        with tempfile.TemporaryDirectory() as folder:
            _, entries = collect_entries(
                "tt",
                "https://www.tiktok.com/@who",
                output_root=folder,
                ydl_cls=BlockedYDL,
                log=lambda *_: None,
                sleep=lambda _: None,
            )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "7676225066660662558")

    def test_flat_feed_entries_with_titles_skip_extra_requests(self):
        detail_calls = []

        class FlatYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                if self.opts.get("extract_flat"):
                    return {
                        "_type": "playlist",
                        "entries": [{
                            "id": "7683870987586260254",
                            "ie_key": "TikTok",
                            "title": "part4 #fyp",
                            "uploader": "viralfinds__hub",
                            "channel_id": SEC_UID,
                            "url": "https://www.tiktok.com/@viralfinds__hub/video/7683870987586260254",
                        }],
                    }
                detail_calls.append(url)
                return {"webpage_url": url, "id": "x", "title": "slow path"}

        with tempfile.TemporaryDirectory() as folder:
            cache = os.path.join(folder, "tt.json")
            _, entries = collect_entries(
                "tt",
                "https://www.tiktok.com/@viralfinds__hub",
                output_root=folder,
                ydl_cls=FlatYDL,
                log=lambda *_: None,
                cache_path=cache,
            )
            self.assertEqual(cached_tiktok_sec_uid("viralfinds__hub", cache), SEC_UID)
        self.assertEqual(detail_calls, [])
        self.assertEqual(entries[0]["title"], "part4 #fyp")

    def test_known_creator_makes_a_blocked_profile_use_the_creator_id(self):
        seen = []

        class UserFeedYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                seen.append(url)
                return {
                    "_type": "playlist",
                    "entries": [{
                        "id": "1",
                        "ie_key": "TikTok",
                        "title": "one",
                        "uploader": "viralfinds__hub",
                        "url": "https://www.tiktok.com/@viralfinds__hub/video/1",
                    }],
                }

        with tempfile.TemporaryDirectory() as folder:
            cache = os.path.join(folder, "tt.json")
            remember_tiktok_user("viralfinds__hub", SEC_UID, cache)
            collect_entries(
                "tt",
                "https://www.tiktok.com/@viralfinds__hub",
                output_root=folder,
                ydl_cls=UserFeedYDL,
                log=lambda *_: None,
                cache_path=cache,
            )
            self.assertEqual(tiktok_username_for_sec_uid(SEC_UID, cache), "viralfinds__hub")
        self.assertEqual(seen, [f"tiktokuser:{SEC_UID}"])

    def test_blocked_profile_explains_how_to_recover(self):
        class BlockedYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return None

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError) as caught:
                collect_entries(
                    "tt",
                    "https://www.tiktok.com/@viralfinds__hub",
                    output_root=folder,
                    ydl_cls=BlockedYDL,
                    log=lambda *_: None,
                    cache_path=os.path.join(folder, "tt.json"),
                )
        self.assertIn("@viralfinds__hub", str(caught.exception))
        self.assertIn("tiktokuser:", str(caught.exception))

    def test_single_post_never_expands_a_playlist(self):
        seen = {}

        class WatchYDL:
            def __init__(self, opts):
                self.opts = opts
                seen.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {"webpage_url": url, "id": "abc", "title": "One", "uploader": "Ada"}

        with tempfile.TemporaryDirectory() as folder:
            _, entries = collect_entries(
                "yt",
                "https://www.youtube.com/watch?v=abc&list=RDabc",
                output_root=folder,
                ydl_cls=WatchYDL,
                log=lambda *_: None,
                feed=False,
            )
        self.assertTrue(seen["noplaylist"])
        self.assertEqual(len(entries), 1)

    def test_feed_choice_lists_a_mix_through_its_seed_video(self):
        class MixYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {
                    "_type": "playlist",
                    "entries": [
                        {"id": "one", "ie_key": "Youtube", "title": "One", "uploader": "Ada"},
                        {"id": "two", "ie_key": "Youtube", "title": "Two", "uploader": "Ada"},
                    ],
                }

        with tempfile.TemporaryDirectory() as folder:
            _, entries = collect_entries(
                "yt",
                "https://www.youtube.com/watch?v=abc&list=RDabc",
                output_root=folder,
                ydl_cls=MixYDL,
                log=lambda *_: None,
                feed=True,
            )
        self.assertEqual([e["id"] for e in entries], ["one", "two"])

    def test_facebook_reels_feed_uses_selenium(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = os.path.join(folder, "jireel.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("https://www.facebook.com/reel/111\n")
            with patch("app.core.collect.scrape_reel_urls", return_value=csv_path) as scrape:
                path, entries = collect_entries(
                    "jireel",
                    "https://www.facebook.com/jireel/reels",
                    output_root=folder,
                    log=lambda *_: None,
                )
            scrape.assert_called_once()
            self.assertEqual(path, csv_path)
            self.assertEqual(entries[0]["platform"], "facebook")
            self.assertEqual(entries[0]["id"], "111")


if __name__ == "__main__":
    unittest.main()
