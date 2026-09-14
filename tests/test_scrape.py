"""Tests for the reel-collecting helpers (no browser)."""
import unittest

from app.core.scrape import harvest_new_reel_urls, ordered_reel_urls


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


if __name__ == "__main__":
    unittest.main()
