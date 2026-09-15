"""Tests for the reel table model and its filter (no window needed)."""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.core.model import (
    COL_ADDED,
    COL_CHECK,
    COL_ETA,
    COL_FILE,
    COL_HOST,
    COL_ID,
    COL_PROGRESS,
    COL_SIZE,
    COL_SPEED,
    COL_STATUS,
    COL_TITLE,
    COL_URL,
    PERCENT_ROLE,
    SORT_ROLE,
    Reel,
    ReelFilterProxy,
    ReelModel,
    format_bytes,
    format_eta,
    media_kind,
)

URLS = [
    "https://www.facebook.com/reel/111",
    "https://www.facebook.com/reel/222",
    "https://www.facebook.com/reel/333",
]


class MediaKind(unittest.TestCase):
    def test_twitter_photo_status_is_image(self):
        self.assertEqual(
            media_kind(Reel("https://x.com/name/status/2085223295776100697/photo/1")),
            "image",
        )
        self.assertEqual(
            media_kind(Reel("https://twitter.com/name/status/2085223295776100697/photo/1")),
            "image",
        )

    def test_pinterest_pin_without_duration_is_image(self):
        self.assertEqual(
            media_kind(Reel("https://www.pinterest.com/pin/664281013778109217/")),
            "image",
        )
        self.assertEqual(
            media_kind(Reel(
                "https://www.pinterest.com/pin/664281013778109217/",
                duration=12,
            )),
            "video",
        )
        self.assertEqual(
            media_kind(Reel(
                "https://www.pinterest.com/pin/1/",
                filepath=r"C:\dl\pin\video\1.mp4",
            )),
            "video",
        )


class Formatting(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_bytes(None), "-")
        self.assertEqual(format_bytes(900), "900 B")
        self.assertEqual(format_bytes(1536), "1.5 KB")

    def test_eta(self):
        self.assertEqual(format_eta(None), "-")
        self.assertEqual(format_eta(75), "1:15")


class Model(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.model = ReelModel()
        self.model.set_urls(URLS)

    def _display(self, row, column):
        return self.model.data(self.model.index(row, column), Qt.ItemDataRole.DisplayRole)

    def test_rows_start_queued(self):
        self.assertEqual(self.model.rowCount(), 3)
        self.assertEqual(self._display(0, COL_STATUS), "Queued")
        self.assertEqual(self._display(0, COL_ID), "111")
        self.assertEqual(self.model.counts()["queued"], 3)

    def test_download_event_fills_the_row(self):
        self.model.apply_event(URLS[0], {
            "status": "downloading", "percent": 40.0,
            "total": 2048, "speed": 1024, "eta": 30,
        })
        self.assertEqual(self._display(0, COL_STATUS), "Downloading")
        self.assertEqual(self._display(0, COL_SIZE), "2.0 KB")
        self.assertEqual(self._display(0, COL_SPEED), "1.0 KB/s")
        self.assertEqual(self._display(0, COL_ETA), "0:30")
        self.assertEqual(self.model.data(self.model.index(0, COL_PROGRESS), PERCENT_ROLE), 40.0)

    def test_caption_fills_the_title_column(self):
        self.model.apply_event(URLS[0], {
            "title": "Name on Reels",
            "description": "Morning coffee ☕",
            "uploader": "Ada",
        })
        self.assertEqual(self._display(0, COL_TITLE), "Morning coffee ☕")
        self.assertEqual(self._display(0, COL_STATUS), "Queued")
        self.assertIn("Ada", self.model.data(self.model.index(0, COL_TITLE), Qt.ItemDataRole.ToolTipRole))

    def test_add_entries_fills_an_existing_caption(self):
        added = self.model.add_entries([
            {"url": URLS[0], "title": "Name on Reels", "description": "Morning coffee"},
        ])
        self.assertEqual(added, 0)
        self.assertEqual(self._display(0, COL_TITLE), "Morning coffee")

    def test_info_does_not_wipe_download_speed(self):
        self.model.apply_event(URLS[0], {
            "status": "downloading", "percent": 40.0, "speed": 1024, "eta": 30,
        })
        self.model.apply_event(URLS[0], {"description": "Caption only"})
        self.assertEqual(self._display(0, COL_SPEED), "1.0 KB/s")
        self.assertEqual(self._display(0, COL_TITLE), "Caption only")

    def test_done_forces_full_progress_and_counts(self):
        self.model.apply_event(URLS[0], {"status": "done"})
        self.assertEqual(self.model.data(self.model.index(0, COL_PROGRESS), PERCENT_ROLE), 100.0)
        counts = self.model.counts()
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["queued"], 2)

    def test_unknown_url_is_ignored(self):
        self.assertFalse(self.model.apply_event("https://example.com/reel/9", {"status": "done"}))

    def test_clear_empties_the_model(self):
        self.model.clear()
        self.assertEqual(self.model.rowCount(), 0)

    def test_checkbox_toggles_without_changing_status(self):
        index = self.model.index(1, COL_CHECK)
        self.assertEqual(
            self.model.data(index, Qt.ItemDataRole.CheckStateRole),
            Qt.CheckState.Unchecked,
        )
        self.model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        self.assertEqual(self.model.checked_urls(), [URLS[1]])
        self.assertEqual(self._display(1, COL_STATUS), "Queued")

    def test_header_check_state_is_partial_when_mixed(self):
        self.model.set_checked_rows([0], True)
        self.assertEqual(
            self.model.check_state_for_rows([0, 1, 2]),
            Qt.CheckState.PartiallyChecked,
        )

    def test_remove_urls_keeps_the_rest_in_order(self):
        self.model.remove_urls([URLS[1]])
        self.assertEqual(self.model.urls(), [URLS[0], URLS[2]])
        self.assertEqual(self._display(1, COL_ID), "333")

    def test_overview_totals_bytes_speed_and_hosts(self):
        self.model.set_urls([
            {"url": "https://www.youtube.com/watch?v=abc", "total": 10_000_000},
            {"url": "https://www.tiktok.com/@x/video/1"},
        ])
        self.model.apply_event("https://www.youtube.com/watch?v=abc", {
            "status": "downloading", "percent": 25.0, "total": 10_000_000,
            "speed": 500_000,
        })
        data = self.model.overview()
        self.assertEqual(data["links"], 2)
        self.assertEqual(data["hosts"], 2)
        self.assertEqual((data["sized"], data["unsized"]), (1, 1))
        self.assertEqual(data["bytes_total"], 10_000_000)
        self.assertEqual(data["bytes_loaded"], 2_500_000)
        self.assertEqual(data["bytes_left"], 7_500_000)
        self.assertEqual(data["speed"], 500_000)
        self.assertEqual(data["eta"], 15.0)
        self.assertEqual(data["counts"]["downloading"], 1)

    def test_overview_has_no_eta_while_nothing_runs(self):
        self.assertIsNone(self.model.overview()["eta"])
        self.assertEqual(self.model.overview()["bytes_total"], 0)

    def test_move_rows_shifts_a_block_without_breaking_neighbors(self):
        self.assertEqual(self.model.move_rows([1, 2], 1), [1, 2])
        self.assertEqual(self.model.urls(), URLS)
        self.assertEqual(self.model.move_rows([1, 2], -1), [0, 1])
        self.assertEqual(self.model.urls(), [URLS[1], URLS[2], URLS[0]])
        self.assertEqual(self.model.move_rows([0, 1], 1), [1, 2])
        self.assertEqual(self.model.urls(), [URLS[0], URLS[1], URLS[2]])

    def test_entries_fill_title_and_platform(self):
        self.model.set_urls([{
            "url": "https://www.youtube.com/watch?v=abc",
            "id": "abc",
            "title": "Hello",
            "platform": "youtube",
            "uploader": "Ada",
        }])
        self.assertEqual(self._display(0, COL_TITLE), "Hello")
        self.assertEqual(self.model.reel_at(0).platform, "youtube")
        self.proxy = ReelFilterProxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.set_text("youtube")
        self.assertEqual(self.proxy.rowCount(), 1)

    def test_saved_status_and_progress_are_restored(self):
        self.model.set_urls([{
            "url": URLS[0],
            "status": "done",
            "percent": 100,
            "title": "Done item",
        }, {
            "url": URLS[1],
            "status": "queued",
            "percent": 40,
            "total": 2048,
        }])
        self.assertEqual(self.model.counts()["done"], 1)
        self.assertEqual(self.model.pending_urls(), [URLS[1]])
        self.assertEqual(self._display(0, COL_STATUS), "Done")
        self.assertEqual(self.model.data(self.model.index(1, COL_PROGRESS), PERCENT_ROLE), 40.0)

    def test_header_labels_use_jdownloader_names(self):
        horizontal = Qt.Orientation.Horizontal
        role = Qt.ItemDataRole.DisplayRole
        self.assertEqual(self.model.headerData(COL_TITLE, horizontal, role), "Name")
        self.assertEqual(self.model.headerData(COL_HOST, horizontal, role), "Hoster")
        self.assertEqual(self.model.headerData(COL_FILE, horizontal, role), "Save to")
        self.assertEqual(self.model.headerData(COL_URL, horizontal, role), "Download from")
        self.assertEqual(self.model.headerData(COL_ADDED, horizontal, role), "Added")

    def test_add_entries_prepends_and_rebuilds_url_map(self):
        fresh = "https://www.facebook.com/reel/000"
        added = self.model.add_entries([{"url": fresh, "title": "First"}], prepend=True)
        self.assertEqual(added, 1)
        self.assertEqual(self.model.urls()[0], fresh)
        self.assertEqual(self._display(0, COL_TITLE), "First")
        self.model.apply_event(fresh, {"status": "done"})
        self.assertEqual(self.model.counts()["done"], 1)
        self.assertEqual(self.model.status_at(0), "done")

    def test_comment_and_added_at_persist_through_entries(self):
        stamped = 1_700_000_000.0
        self.model.set_urls([{
            "url": URLS[0],
            "comment": "keep this",
            "added_at": stamped,
        }])
        self.assertEqual(self.model.reel_at(0).comment, "keep this")
        self.assertEqual(self.model.reel_at(0).added_at, stamped)
        entry = self.model.entries()[0]
        self.assertEqual(entry["comment"], "keep this")
        self.assertEqual(entry["added_at"], stamped)
        self.model.set_entries([entry])
        self.assertEqual(self.model.reel_at(0).comment, "keep this")
        self.assertEqual(self.model.reel_at(0).added_at, stamped)
        self.assertEqual(self._display(0, COL_ADDED), datetime.fromtimestamp(stamped).strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(
            self.model.data(self.model.index(0, COL_ADDED), SORT_ROLE),
            stamped,
        )

    def test_new_rows_get_added_at_now(self):
        with patch("app.core.model.time.time", return_value=1_712_000_000.0):
            reel = Reel(URLS[0])
        self.assertEqual(reel.added_at, 1_712_000_000.0)

    def test_update_reel_sets_title_comment_and_filepath(self):
        changed = []
        self.model.dataChanged.connect(lambda *_: changed.append(True))
        self.assertTrue(self.model.update_reel(
            URLS[0], title="Edited", comment="note", filepath=r"H:\out\clip.mp4",
        ))
        self.assertEqual(self.model.reel_at(0).title, "Edited")
        self.assertEqual(self.model.reel_at(0).comment, "note")
        self.assertEqual(self.model.reel_at(0).filepath, r"H:\out\clip.mp4")
        self.assertEqual(self._display(0, COL_TITLE), "Edited")
        self.assertTrue(changed)


class Filtering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.model = ReelModel()
        self.model.set_urls(URLS)
        self.proxy = ReelFilterProxy()
        self.proxy.setSourceModel(self.model)

    def test_status_filter(self):
        self.model.apply_event(URLS[1], {"status": "done"})
        self.proxy.set_status("done")
        self.assertEqual(self.proxy.rowCount(), 1)
        self.proxy.set_status(None)
        self.assertEqual(self.proxy.rowCount(), 3)

    def test_kind_and_host_filters(self):
        self.model.set_urls([
            "https://www.facebook.com/reel/111",
            "https://www.tiktok.com/@x/photo/99",
            "https://music.youtube.com/watch?v=abc",
        ])
        self.proxy.set_kinds({"image"})
        self.assertEqual(self.proxy.rowCount(), 1)
        self.proxy.set_kinds({"video", "music", "image"})
        self.proxy.set_hosts({"facebook.com"})
        self.assertEqual(self.proxy.rowCount(), 1)
        hosts, kinds = self.model.host_kind_counts()
        self.assertEqual(hosts["facebook.com"], 1)
        self.assertEqual(kinds["video"], 1)
        self.assertEqual(kinds["image"], 1)
        self.assertEqual(kinds["music"], 1)

    def test_text_filter_matches_reel_id(self):
        self.proxy.set_text("222")
        self.assertEqual(self.proxy.rowCount(), 1)

    def test_text_filter_matches_caption(self):
        self.model.apply_event(URLS[2], {"description": "sunset over the river"})
        self.proxy.set_text("sunset")
        self.assertEqual(self.proxy.rowCount(), 1)

    def test_status_change_updates_a_filtered_view(self):
        self.proxy.set_status("done")
        self.assertEqual(self.proxy.rowCount(), 0)
        self.model.apply_event(URLS[0], {"status": "done"})
        self.assertEqual(self.proxy.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
