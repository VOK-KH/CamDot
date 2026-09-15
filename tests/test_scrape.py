"""Tests for the reel-collecting helpers (no browser)."""
import unittest

from app.core.scrape import (
    _clean_caption,
    harvest_new_reel_urls,
    harvest_reel_cards,
    instagram_media_url,
    ordered_reel_urls,
)


class OrderedReelUrls(unittest.TestCase):
    def test_page_order_is_kept(self):
        # Download order must follow the page, not the alphabet.
        hrefs = [
            "https://www.facebook.com/reel/300",
            "https://www.facebook.com/reel/100",
            "https://www.facebook.com/reel/200",
        ]
        self.assertEqual(ordered_reel_urls(hrefs), hrefs)

    def test_duplicates_keep_their_first_position(self):
        hrefs = [
            "https://www.facebook.com/reel/300",
            "https://www.facebook.com/reel/100",
            "https://www.facebook.com/reel/300",
        ]
        self.assertEqual(
            ordered_reel_urls(hrefs),
            ["https://www.facebook.com/reel/300", "https://www.facebook.com/reel/100"],
        )

    def test_tracking_suffix_is_trimmed(self):
        self.assertEqual(
            ordered_reel_urls(["https://www.facebook.com/reel/9/?s=abc"]),
            ["https://www.facebook.com/reel/9"],
        )

    def test_non_reel_links_are_skipped(self):
        hrefs = [None, "https://www.facebook.com/jireel", "https://www.facebook.com/reel/1"]
        self.assertEqual(ordered_reel_urls(hrefs), ["https://www.facebook.com/reel/1"])

    def test_harvest_reports_only_new_reel_urls(self):
        seen = {}
        first = harvest_new_reel_urls(
            [
                "https://www.facebook.com/reel/1",
                "https://www.facebook.com/reel/2",
            ],
            seen,
        )
        again = harvest_new_reel_urls(
            [
                "https://www.facebook.com/reel/2",
                "https://www.facebook.com/reel/3",
            ],
            seen,
        )
        self.assertEqual(first, [
            "https://www.facebook.com/reel/1",
            "https://www.facebook.com/reel/2",
        ])
        self.assertEqual(again, ["https://www.facebook.com/reel/3"])
        self.assertEqual(list(seen), [
            "https://www.facebook.com/reel/1",
            "https://www.facebook.com/reel/2",
            "https://www.facebook.com/reel/3",
        ])

    def test_harvest_keeps_aria_label_captions(self):
        seen = {}
        cards = harvest_reel_cards(
            [
                ("https://www.facebook.com/reel/1/?s=x", "Reel by Ada: Lake at dusk"),
                ("https://www.facebook.com/reel/1", "Lake at dusk"),
            ],
            seen,
        )
        self.assertEqual(cards[0]["url"], "https://www.facebook.com/reel/1")
        self.assertEqual(cards[0]["description"], "Lake at dusk")
        self.assertEqual(_clean_caption("Play reel"), "")
        self.assertEqual(_clean_caption("Reel by Ada: Lake at dusk"), "Lake at dusk")

    def test_harvest_unique_instagram_post_urls(self):
        hrefs = [
            "https://www.instagram.com/2002chii_/",
            "https://www.instagram.com/2002chii_/reels/",
            "https://www.instagram.com/2002chii_/reposts/",
            "https://www.instagram.com/p/AbC/?hl=en",
            "https://www.instagram.com/reel/DeF/",
            "https://www.instagram.com/2002chii_/tv/GhI/",
            "https://www.instagram.com/p/AbC/",
            "https://www.facebook.com/reel/111",
        ]
        self.assertEqual(
            ordered_reel_urls(hrefs),
            [
                "https://www.instagram.com/p/AbC/",
                "https://www.instagram.com/reel/DeF/",
                "https://www.instagram.com/tv/GhI/",
                "https://www.facebook.com/reel/111",
            ],
        )
        self.assertEqual(instagram_media_url("https://www.instagram.com/2002chii_/reels/"), "")
        seen = {}
        first = harvest_new_reel_urls(hrefs, seen)
        again = harvest_new_reel_urls(hrefs, seen)
        self.assertEqual(first, [
            "https://www.instagram.com/p/AbC/",
            "https://www.instagram.com/reel/DeF/",
            "https://www.instagram.com/tv/GhI/",
            "https://www.facebook.com/reel/111",
        ])
        self.assertEqual(again, [])


if __name__ == "__main__":
    unittest.main()
