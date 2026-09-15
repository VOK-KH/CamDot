"""Tests for collect routing (mocked yt-dlp, no browser)."""
import json
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
from app.core.jobs import StopRequested
from app.core.runtime import collect_csv_path

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
    def setUp(self):
        self._state = tempfile.TemporaryDirectory()
        self._state_patch = patch("app.core.runtime.state_dir", return_value=self._state.name)
        self._state_patch.start()

    def tearDown(self):
        self._state_patch.stop()
        self._state.cleanup()

    def test_instagram_profile_uses_ytdlp(self):
        class FakeYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {
                    "_type": "playlist",
                    "entries": [{
                        "webpage_url": "https://www.instagram.com/reel/AbC/",
                        "id": "AbC",
                        "title": "A reel",
                        "uploader": "someone",
                        "extractor_key": "Instagram",
                    }],
                }

        with tempfile.TemporaryDirectory() as folder:
            _, entries = collect_entries(
                "x", "https://www.instagram.com/someone/",
                output_root=folder, ydl_cls=FakeYDL,
            )
        self.assertEqual(entries[0]["url"], "https://www.instagram.com/reel/AbC/")

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

    def test_facebook_reels_feed_uses_ytdlp_when_it_lists(self):
        listed = [{
            "url": "https://www.facebook.com/reel/111",
            "id": "111",
            "title": "Sunset",
            "description": "River",
            "uploader": "Ada",
            "duration": 12,
            "platform": "facebook",
            "extractor_key": "Facebook",
            "webpage_url_domain": "facebook.com",
        }]
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.core.collect._collect_ytdlp", return_value=listed) as ytdlp:
                with patch("app.core.collect.scrape_reel_urls") as scrape:
                    path, entries = collect_entries(
                        "jireel",
                        "https://www.facebook.com/jireel/reels",
                        output_root=folder,
                        log=lambda *_: None,
                    )
                    scrape.assert_not_called()
                    ytdlp.assert_called_once()
                    self.assertEqual(entries[0]["id"], "111")
                    self.assertEqual(path, collect_csv_path("jireel"))
                    self.assertTrue(os.path.isfile(path))

    def test_facebook_reels_feed_uses_selenium(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = os.path.join(folder, "jireel.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("https://www.facebook.com/reel/111\n")
            with patch("app.core.collect._collect_ytdlp", side_effect=ValueError("no items")):
                with patch("app.core.collect.scrape_reel_urls", return_value=csv_path) as scrape:
                    with patch("app.core.collect._extract_detail", return_value=None):
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

    def test_facebook_reels_feed_falls_back_when_ytdlp_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = os.path.join(folder, "jireel.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("https://www.facebook.com/reel/111\n")
            with patch("app.core.collect._collect_ytdlp", return_value=[]):
                with patch("app.core.collect.scrape_reel_urls", return_value=csv_path) as scrape:
                    with patch("app.core.collect._extract_detail", return_value=None):
                        collect_entries(
                            "jireel",
                            "https://www.facebook.com/jireel/reels",
                            output_root=folder,
                            log=lambda *_: None,
                        )
            scrape.assert_called_once()

    def test_facebook_reels_ytdlp_stop_does_not_open_chrome(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch(
                "app.core.collect._collect_ytdlp",
                side_effect=StopRequested("Cancelled."),
            ):
                with patch("app.core.collect.scrape_reel_urls") as scrape:
                    with self.assertRaises(StopRequested):
                        collect_entries(
                            "jireel",
                            "https://www.facebook.com/jireel/reels",
                            output_root=folder,
                            log=lambda *_: None,
                        )
                    scrape.assert_not_called()

    def test_facebook_reels_fill_caption_from_yt_dlp(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = os.path.join(folder, "jireel.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("https://www.facebook.com/reel/111\n")

            def fake_detail(ydl_cls, url, opts, should_stop, sleep=None):
                return {
                    "webpage_url": url,
                    "id": "111",
                    "title": "Facebook",
                    "description": "Sunset over the river",
                    "uploader": "Ada",
                    "extractor_key": "Facebook",
                }

            with patch("app.core.collect._collect_ytdlp", return_value=[]):
                with patch("app.core.collect.scrape_reel_urls", return_value=csv_path):
                    with patch("app.core.collect._extract_detail", side_effect=fake_detail):
                        _, entries = collect_entries(
                            "jireel",
                            "https://www.facebook.com/jireel/reels",
                            output_root=folder,
                            log=lambda *_: None,
                        )
        self.assertEqual(entries[0]["description"], "Sunset over the river")
        self.assertEqual(entries[0]["title"], "Facebook")

    def test_instagram_feed_ytdlp_success_skips_scrape(self):
        listed = [{
            "url": "https://www.instagram.com/reel/AbC/",
            "id": "AbC",
            "title": "A reel",
            "uploader": "2002chii_",
            "platform": "instagram",
            "extractor_key": "Instagram",
            "webpage_url_domain": "instagram.com",
        }]
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.core.collect._collect_ytdlp", return_value=listed) as ytdlp:
                with patch("app.core.collect.scrape_reel_urls") as scrape:
                    _, entries = collect_entries(
                        "ig",
                        "https://www.instagram.com/2002chii_/reels/?hl=en",
                        output_root=folder,
                        log=lambda *_: None,
                    )
                    scrape.assert_not_called()
                    ytdlp.assert_called_once()
                    self.assertEqual(
                        ytdlp.call_args.args[0],
                        "https://www.instagram.com/2002chii_/",
                    )
                    self.assertEqual(entries[0]["id"], "AbC")

    def test_instagram_feed_ytdlp_fail_calls_scrape(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = os.path.join(folder, "ig.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("https://www.instagram.com/reel/AbC/\n")
            with patch("app.core.collect._collect_ytdlp", side_effect=ValueError("Unable to extract data")):
                with patch("app.core.collect.scrape_reel_urls", return_value=csv_path) as scrape:
                    with patch("app.core.collect._extract_detail", return_value=None):
                        collect_entries(
                            "ig",
                            "https://www.instagram.com/2002chii_/",
                            output_root=folder,
                            log=lambda *_: None,
                        )
            scrape.assert_called_once()
            self.assertEqual(
                scrape.call_args.args[1],
                "https://www.instagram.com/2002chii_/",
            )

    def test_instagram_feed_ytdlp_empty_calls_scrape(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = os.path.join(folder, "ig.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("https://www.instagram.com/p/AbC/\n")
            with patch("app.core.collect._collect_ytdlp", return_value=[]):
                with patch("app.core.collect.scrape_reel_urls", return_value=csv_path) as scrape:
                    with patch("app.core.collect._extract_detail", return_value=None):
                        collect_entries(
                            "ig",
                            "https://www.instagram.com/2002chii_/reels/",
                            output_root=folder,
                            log=lambda *_: None,
                        )
            scrape.assert_called_once()
            self.assertEqual(
                scrape.call_args.args[1],
                "https://www.instagram.com/2002chii_/reels/",
            )

    def test_instagram_reposts_does_not_treat_profile_rewrite_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = os.path.join(folder, "ig.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("https://www.instagram.com/p/Repost1/\n")
            with patch(
                "app.core.collect._collect_ytdlp",
                return_value=[{
                    "url": "https://www.instagram.com/p/OwnPost/",
                    "id": "OwnPost",
                    "title": "profile mix",
                    "platform": "instagram",
                }],
            ) as ytdlp:
                with patch("app.core.collect.scrape_reel_urls", return_value=csv_path) as scrape:
                    with patch("app.core.collect._extract_detail", return_value=None):
                        _, entries = collect_entries(
                            "ig",
                            "https://www.instagram.com/2002chii_/reposts/?hl=en",
                            output_root=folder,
                            log=lambda *_: None,
                        )
            ytdlp.assert_not_called()
            scrape.assert_called_once()
            self.assertEqual(
                scrape.call_args.args[1],
                "https://www.instagram.com/2002chii_/reposts/",
            )
            self.assertEqual(entries[0]["url"], "https://www.instagram.com/p/Repost1/")

    def test_instagram_ytdlp_stop_does_not_open_chrome(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch(
                "app.core.collect._collect_ytdlp",
                side_effect=StopRequested("Cancelled."),
            ):
                with patch("app.core.collect.scrape_reel_urls") as scrape:
                    with self.assertRaises(StopRequested):
                        collect_entries(
                            "ig",
                            "https://www.instagram.com/2002chii_/",
                            output_root=folder,
                            log=lambda *_: None,
                        )
                    scrape.assert_not_called()

    def test_pinterest_board_feed_yields_image_pin_urls(self):
        board_id = "585890301462791043"
        pin_id = "664281013778109217"

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
            if "BoardResource/get/" in url:
                return FakeResp(json.dumps({
                    "resource_response": {"data": {"id": board_id, "name": "cool"}},
                }).encode())
            if "BoardFeedResource/get/" in url:
                return FakeResp(json.dumps({
                    "resource_response": {
                        "data": [
                            {
                                "type": "pin",
                                "id": pin_id,
                                "grid_title": "A cat",
                                "title": "",
                                "description": "cute",
                            },
                            {"type": "board", "id": "skip-me"},
                        ],
                        "bookmark": None,
                    },
                }).encode())
            raise AssertionError(f"unexpected url {url}")

        streamed = []

        class BoomYDL:
            def __init__(self, opts):
                raise AssertionError("yt-dlp should not run when the API works")

        with tempfile.TemporaryDirectory() as folder:
            with patch("app.core.download.urllib.request.urlopen", side_effect=fake_urlopen):
                _, entries = collect_entries(
                    "pin",
                    "https://www.pinterest.com/user/board/",
                    output_root=folder,
                    ydl_cls=BoomYDL,
                    log=lambda *_: None,
                    on_entries=streamed.extend,
                )
        self.assertEqual(entries[0]["url"], f"https://www.pinterest.com/pin/{pin_id}/")
        self.assertEqual(entries[0]["title"], "A cat")
        self.assertIsNone(entries[0]["duration"])
        self.assertEqual(streamed[0]["url"], entries[0]["url"])


if __name__ == "__main__":
    unittest.main()
