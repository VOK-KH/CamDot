"""Catalog of first-class and coming-soon platforms (no widgets)."""
import unittest

from app.core.platforms import (
    PLATFORM_CATALOG,
    active_platforms,
    coming_soon_platforms,
    platform_by_id,
)

ACTIVE_IDS = (
    "facebook",
    "instagram",
    "tiktok",
    "youtube",
    "twitter",
    "bilibili",
    "douyin",
    "kuaishou",
    "pinterest",
    "generic",
)
COMING_SOON_IDS = (
    "threads",
    "reddit",
    "snapchat",
    "xiaohongshu",
    "weibo",
    "twitch",
)


class PlatformCatalog(unittest.TestCase):
    def test_active_ids_include_first_class_hosts(self):
        ids = [entry["id"] for entry in active_platforms()]
        self.assertEqual(ids, list(ACTIVE_IDS))

    def test_coming_soon_includes_threads(self):
        ids = [entry["id"] for entry in coming_soon_platforms()]
        self.assertIn("threads", ids)
        self.assertEqual(ids, list(COMING_SOON_IDS))

    def test_coming_soon_ids_are_not_active(self):
        active = {entry["id"] for entry in active_platforms()}
        for platform_id in COMING_SOON_IDS:
            self.assertNotIn(platform_id, active)

    def test_facebook_features_mention_reels_and_chrome(self):
        features = " ".join(platform_by_id("facebook")["features"])
        self.assertIn("reels", features)
        self.assertIn("Chrome", features)

    def test_douyin_limits_mention_feeds(self):
        limits = " ".join(platform_by_id("douyin")["limits"])
        self.assertIn("feeds", limits.lower())

    def test_platform_by_id_and_catalog_keys(self):
        self.assertIsNone(platform_by_id("missing"))
        for entry in PLATFORM_CATALOG:
            self.assertEqual(set(entry), {
                "id", "name", "hosts", "status", "icon", "features", "limits",
            })
            self.assertIs(platform_by_id(entry["id"]), entry)
