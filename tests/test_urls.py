"""Tests for URL handling (stdlib unittest, no extra dependencies).

Run: uv run python -m unittest discover -s tests -v
"""
import unittest

from app.core.urls import (
    FACEBOOK_REELS_FEED,
    FEED,
    SINGLE,
    UNSUPPORTED_FEED,
    classify_source,
    collection_strategy,
    detect_platform,
    extract_supported_urls,
    looks_shell_truncated,
    normalize_channel_url,
    normalize_source_url,
    tiktok_sec_uid,
    tiktok_username,
    youtube_watch_with_list,
)


class ClipboardUrls(unittest.TestCase):
    def test_extracts_supported_urls_and_removes_duplicates(self):
        text = (
            "watch https://www.tiktok.com/@demo/video/123, then "
            "https://youtu.be/abc123. Duplicate: https://youtu.be/abc123 "
            "and ignore https://example.com/nope"
        )
        self.assertEqual(
            extract_supported_urls(text),
            [
                "https://www.tiktok.com/@demo/video/123",
                "https://youtu.be/abc123",
            ],
        )


class YoutubeWatchWithList(unittest.TestCase):
    def test_mix_keeps_the_seed_video_because_it_is_unviewable_alone(self):
        video, playlist = youtube_watch_with_list(
            "https://www.youtube.com/watch?v=OaPcBJnGU5M&list=RDOaPcBJnGU5M&start_radio=1"
        )
        self.assertEqual(video, "https://www.youtube.com/watch?v=OaPcBJnGU5M")
        self.assertEqual(
            playlist,
            "https://www.youtube.com/watch?v=OaPcBJnGU5M&list=RDOaPcBJnGU5M",
        )

    def test_ordinary_playlist_gets_its_own_page(self):
        video, playlist = youtube_watch_with_list(
            "https://www.youtube.com/watch?v=abc123&list=PL0123456789"
        )
        self.assertEqual(video, "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(playlist, "https://www.youtube.com/playlist?list=PL0123456789")

    def test_short_link_with_a_list_is_recognised(self):
        video, playlist = youtube_watch_with_list("https://youtu.be/abc123?list=PLxyz")
        self.assertEqual(video, "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(playlist, "https://www.youtube.com/playlist?list=PLxyz")

    def test_plain_links_have_nothing_to_ask_about(self):
        self.assertEqual(youtube_watch_with_list("https://www.youtube.com/watch?v=abc123"), ())
        self.assertEqual(
            youtube_watch_with_list("https://www.youtube.com/playlist?list=PLxyz"), ()
        )
        self.assertEqual(youtube_watch_with_list("https://www.tiktok.com/@a/video/1"), ())


class TiktokCreatorFeeds(unittest.TestCase):
    SEC_UID = "MS4wLjABAAAAbur-JVGxoTBCrLVUoAFqWcFn7hiIevluwN0k_LaB4U8q3tQizemnqCpb6thhVdXQ"

    def test_creator_id_input_is_a_tiktok_feed(self):
        source = f"tiktokuser:{self.SEC_UID}"
        self.assertEqual(detect_platform(source), "tiktok")
        self.assertEqual(classify_source(source), FEED)
        self.assertEqual(normalize_source_url(source), source)
        self.assertEqual(collection_strategy(source), "ytdlp")

    def test_creator_id_without_a_value_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_source_url("tiktokuser:")

    def test_username_and_sec_uid_are_read_from_urls(self):
        self.assertEqual(
            tiktok_username("https://www.tiktok.com/@viralfinds__hub"), "viralfinds__hub"
        )
        self.assertEqual(
            tiktok_username("https://www.tiktok.com/@viralfinds__hub/video/7683297279184358687"),
            "viralfinds__hub",
        )
        self.assertEqual(tiktok_username(f"tiktokuser:{self.SEC_UID}"), "")
        self.assertEqual(
            tiktok_sec_uid(f"https://www.tiktok.com/@{self.SEC_UID}/video/1"), self.SEC_UID
        )


class NormalizeChannelUrl(unittest.TestCase):
    def test_profile_url_gets_reels_tab(self):
        # This is what CMD/bash hand us after the shell eats "&sk=reels_tab".
        self.assertEqual(
            normalize_channel_url("https://www.facebook.com/profile.php?id=61554746552594"),
            "https://www.facebook.com/profile.php?id=61554746552594&sk=reels_tab",
        )

    def test_profile_url_with_reels_tab_is_unchanged(self):
        url = "https://www.facebook.com/profile.php?id=61554746552594&sk=reels_tab"
        self.assertEqual(normalize_channel_url(url), url)

    def test_explicit_other_tab_is_respected(self):
        url = "https://www.facebook.com/profile.php?id=61554746552594&sk=photos"
        self.assertEqual(normalize_channel_url(url), url)

    def test_people_style_profile_gets_reels_tab(self):
        self.assertEqual(
            normalize_channel_url("https://www.facebook.com/people/Some-Page/61554746552594/"),
            "https://www.facebook.com/people/Some-Page/61554746552594/?sk=reels_tab",
        )

    def test_vanity_name_gets_reels_path(self):
        self.assertEqual(
            normalize_channel_url("https://www.facebook.com/jireel"),
            "https://www.facebook.com/jireel/reels",
        )

    def test_reels_path_is_unchanged(self):
        url = "https://www.facebook.com/jireel/reels"
        self.assertEqual(normalize_channel_url(url), url)

    def test_surrounding_quotes_are_stripped(self):
        # People paste the URL still wrapped in the quotes they typed in the shell.
        self.assertEqual(
            normalize_channel_url('"https://www.facebook.com/jireel/reels"'),
            "https://www.facebook.com/jireel/reels",
        )

    def test_inline_cmd_escaping_is_cleaned(self):
        # cmd.exe users are told to write ...id=1"&"sk=reels_tab ; if the quotes
        # survive into argv (copy/paste, quoted whole string) we must clean them.
        self.assertEqual(
            normalize_channel_url('https://www.facebook.com/profile.php?id=615"&"sk=reels_tab'),
            "https://www.facebook.com/profile.php?id=615&sk=reels_tab",
        )

    def test_missing_scheme_is_added(self):
        self.assertEqual(
            normalize_channel_url("facebook.com/jireel/reels"),
            "https://facebook.com/jireel/reels",
        )

    def test_whitespace_is_trimmed(self):
        self.assertEqual(
            normalize_channel_url("  https://www.facebook.com/jireel/reels \n"),
            "https://www.facebook.com/jireel/reels",
        )

    def test_non_facebook_url_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_channel_url("https://www.youtube.com/@someone")

    def test_empty_url_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_channel_url("   ")


class LooksShellTruncated(unittest.TestCase):
    def test_profile_id_only_looks_truncated(self):
        self.assertTrue(
            looks_shell_truncated("https://www.facebook.com/profile.php?id=61554746552594")
        )

    def test_full_url_does_not_look_truncated(self):
        self.assertFalse(
            looks_shell_truncated(
                "https://www.facebook.com/profile.php?id=61554746552594&sk=reels_tab"
            )
        )

    def test_vanity_url_does_not_look_truncated(self):
        self.assertFalse(looks_shell_truncated("https://www.facebook.com/jireel/reels"))


class DetectPlatform(unittest.TestCase):
    def test_known_hosts(self):
        cases = {
            "https://www.facebook.com/reel/1": "facebook",
            "https://fb.com/jireel": "facebook",
            "https://www.instagram.com/p/AbC/": "instagram",
            "https://www.tiktok.com/@user/video/1": "tiktok",
            "https://vm.tiktok.com/ZMabc/": "tiktok",
            "https://www.youtube.com/watch?v=dQw4w9wgGcQ": "youtube",
            "https://youtu.be/dQw4w9wgGcQ": "youtube",
            "https://x.com/name/status/1": "twitter",
            "https://twitter.com/name/status/1": "twitter",
        }
        for url, platform in cases.items():
            with self.subTest(url=url):
                self.assertEqual(detect_platform(url), platform)

    def test_unknown_host(self):
        self.assertEqual(detect_platform("https://example.com/v/1"), "unknown")


class ClassifySource(unittest.TestCase):
    def test_facebook_single_and_feed(self):
        self.assertEqual(classify_source("https://www.facebook.com/reel/123"), SINGLE)
        self.assertEqual(classify_source("https://www.facebook.com/watch/?v=99"), SINGLE)
        self.assertEqual(
            classify_source("https://www.facebook.com/jireel/reels"), FACEBOOK_REELS_FEED
        )
        self.assertEqual(
            classify_source("https://www.facebook.com/profile.php?id=1&sk=reels_tab"),
            FACEBOOK_REELS_FEED,
        )

    def test_instagram(self):
        self.assertEqual(classify_source("https://www.instagram.com/p/AbC/"), SINGLE)
        self.assertEqual(classify_source("https://www.instagram.com/reel/AbC/"), SINGLE)
        self.assertEqual(classify_source("https://www.instagram.com/someone/"), UNSUPPORTED_FEED)

    def test_tiktok(self):
        self.assertEqual(classify_source("https://www.tiktok.com/@user/video/1"), SINGLE)
        self.assertEqual(classify_source("https://www.tiktok.com/@user"), FEED)
        self.assertEqual(classify_source("https://www.tiktok.com/tag/dance"), UNSUPPORTED_FEED)

    def test_youtube(self):
        self.assertEqual(classify_source("https://www.youtube.com/watch?v=dQw4w9wgGcQ"), SINGLE)
        self.assertEqual(classify_source("https://www.youtube.com/shorts/dQw4w9wgGcQ"), SINGLE)
        self.assertEqual(classify_source("https://www.youtube.com/@handle"), FEED)
        self.assertEqual(
            classify_source("https://www.youtube.com/playlist?list=PLabc"), FEED
        )

    def test_twitter(self):
        self.assertEqual(classify_source("https://x.com/name/status/123"), SINGLE)
        self.assertEqual(classify_source("https://x.com/name"), UNSUPPORTED_FEED)


class NormalizeSourceUrl(unittest.TestCase):
    def test_facebook_vanity_still_gets_reels_tab(self):
        self.assertEqual(
            normalize_source_url("https://www.facebook.com/jireel"),
            "https://www.facebook.com/jireel/reels",
        )

    def test_youtube_channel_gains_videos_tab(self):
        self.assertEqual(
            normalize_source_url("https://www.youtube.com/@handle"),
            "https://www.youtube.com/@handle/videos",
        )

    def test_youtube_watch_is_unchanged(self):
        url = "https://www.youtube.com/watch?v=dQw4w9wgGcQ"
        self.assertEqual(normalize_source_url(url), url)

    def test_instagram_profile_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            normalize_source_url("https://www.instagram.com/someone/")
        self.assertIn("profile", str(caught.exception).lower())

    def test_x_timeline_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_source_url("https://x.com/name")

    def test_unknown_site_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_source_url("https://vimeo.com/123")

    def test_collection_strategy(self):
        self.assertEqual(
            collection_strategy("https://www.facebook.com/jireel/reels"), "selenium"
        )
        self.assertEqual(
            collection_strategy("https://www.youtube.com/watch?v=dQw4w9wgGcQ"), "ytdlp"
        )
        self.assertEqual(collection_strategy("https://www.instagram.com/someone/"), "unsupported")


if __name__ == "__main__":
    unittest.main()
