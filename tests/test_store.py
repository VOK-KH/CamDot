"""Tests for the persisted table list (no GUI, no yt-dlp)."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app.core import store


class Store(unittest.TestCase):
    def test_save_round_trip_freezes_in_flight_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "list.json")
            store.save_list(path, [
                {"url": "https://example.com/a", "status": "done", "percent": 100},
                {"url": "https://example.com/b", "status": "downloading", "percent": 33},
            ])
            loaded = store.load_list(path)
            self.assertEqual(loaded[0]["status"], "done")
            self.assertEqual(loaded[1]["status"], "queued")
            self.assertEqual(loaded[1]["percent"], 33)

    def test_reconcile_marks_archive_and_files_done(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, store.ARCHIVE_NAME), "w", encoding="utf-8") as f:
                f.write("youtube abc\n")
            with open(os.path.join(folder, "clip [xyz].mp4"), "wb") as f:
                f.write(b"x")
            entries = store.reconcile_entries(
                [
                    {"url": "https://youtu.be/abc", "id": "abc", "status": "queued"},
                    {"url": "https://youtu.be/xyz", "id": "xyz", "status": "queued"},
                    {"url": "https://youtu.be/def", "id": "def", "status": "downloading", "percent": 10},
                ],
                folder,
            )
            by_id = {item["id"]: item for item in entries}
            self.assertEqual(by_id["abc"]["status"], "done")
            self.assertEqual(by_id["xyz"]["status"], "done")
            self.assertTrue(by_id["xyz"]["filepath"].endswith("clip [xyz].mp4"))
            self.assertEqual(by_id["def"]["status"], "queued")
            self.assertEqual(by_id["def"]["percent"], 10)

    def test_part_file_keeps_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            part = os.path.join(folder, "clip [def].mp4.part")
            with open(part, "wb") as f:
                f.write(b"x" * 50)
            entries = store.reconcile_entries(
                [{"url": "https://youtu.be/def", "id": "def", "total": 100, "percent": 10}],
                folder,
            )
            self.assertEqual(entries[0]["status"], "queued")
            self.assertEqual(entries[0]["percent"], 50.0)
            self.assertEqual(entries[0]["filepath"], part)

    def test_find_output_file_searches_kind_subfolders(self):
        with tempfile.TemporaryDirectory() as folder:
            nested = os.path.join(folder, "video", "clip [abc].mp4")
            os.makedirs(os.path.dirname(nested), exist_ok=True)
            with open(nested, "wb") as f:
                f.write(b"x")
            found = store.find_output_file(folder, "abc", partial=False)
            self.assertEqual(found, os.path.abspath(nested))

    def test_list_output_files_includes_part_and_named_path(self):
        with tempfile.TemporaryDirectory() as folder:
            finished = os.path.join(folder, "clip [abc].mp4")
            part = os.path.join(folder, "clip [abc].mp4.part")
            other = os.path.join(folder, "other [zzz].mp4")
            for path in (finished, part, other):
                with open(path, "wb") as f:
                    f.write(b"x")
            found = store.list_output_files(folder, "abc", finished)
            self.assertEqual(set(found), {os.path.abspath(finished), os.path.abspath(part)})

    def test_list_and_archive_paths_use_channel_state_dir(self):
        with tempfile.TemporaryDirectory() as state:
            with patch("app.core.runtime.state_dir", return_value=state):
                self.assertEqual(
                    store.list_path("downloads", "jireel"),
                    os.path.join(state, "channels", "jireel", store.LIST_NAME),
                )
                self.assertEqual(
                    store.archive_path("downloads", "jireel"),
                    os.path.join(state, "channels", "jireel", store.ARCHIVE_NAME),
                )

    def test_forget_archive_ids_drops_matching_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, store.ARCHIVE_NAME)
            with open(path, "w", encoding="utf-8") as f:
                f.write("youtube abc\nyoutube def\n")
            store.forget_archive_ids(path, ["abc"])
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "youtube def\n")
