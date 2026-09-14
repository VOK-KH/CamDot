"""Smoke tests for the PySide6 window (offscreen, no Chrome, no downloads)."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QPushButton,
    QToolButton,
)

from app.core import icons, theme
from app.core.model import (
    COL_CHECK,
    COL_DURATION,
    COL_FILE,
    COL_HOST,
    COL_ID,
    COL_INDEX,
    COL_PROGRESS,
    COL_STATUS,
    COL_TITLE,
    COL_UPLOADER,
    COL_URL,
    COLUMNS,
)
from app.gui import (
    ALERT_ART,
    COLUMN_WIDTHS,
    MainWindow,
    derive_channel,
    remember_recent,
)
from app.gui import window as window_module
from app.gui.dialogs.links import AddLinksDialog
from app.gui.widgets import GrabberPanel
from app.core.runtime import APP_FOLDER_NAME, default_output_root
from app.gui.dialogs.settings import SettingsDialog

URLS = [
    "https://www.facebook.com/reel/111",
    "https://www.facebook.com/reel/222",
]


class Icons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_referenced_icon_file_exists(self):
        names = [
            "refresh", "select-all", "clear", "link", "collect", "download", "login", "cancel",
            "folder", "settings", "log", "moon", "sun", "copy", "external", "app",
            "play", "stop", "move-up", "move-down", "globe", "plus",
            "status-queued", "status-downloading", "status-done", "status-failed",
            "status-cancelled",
            "platform-facebook", "platform-instagram", "platform-youtube",
            "platform-tiktok", "platform-x", "platform-generic",
        ]
        for name in names:
            path = os.path.join(icons.icon_dir(), f"{name}.svg")
            self.assertTrue(os.path.isfile(path), path)

    def test_icons_render_to_a_pixmap(self):
        self.assertFalse(icons.icon("download", "#ffffff").isNull())

    def test_grabber_monitor_artwork_loads(self):
        names = [artwork for _name, artwork in GrabberPanel.FIELDS]
        names += ["clipboard", "pinned", "nonpinned", "close", "cancel", "ok"]
        for artwork in names:
            self.assertFalse(icons.png(artwork, 14).isNull(), artwork)

    def test_alert_artwork_loads_at_the_requested_height(self):
        for mascot, badge in ALERT_ART.values():
            self.assertEqual(icons.art("botty", mascot, 64).height(), 64)
            self.assertFalse(icons.art("dialog", badge).isNull(), badge)


class SourceNaming(unittest.TestCase):
    def test_vanity_url_becomes_channel(self):
        self.assertEqual(
            derive_channel("https://www.facebook.com/jireel/reels"),
            "jireel",
        )

    def test_profile_id_becomes_channel(self):
        self.assertEqual(
            derive_channel("https://facebook.com/profile.php?id=6155"),
            "6155",
        )

    def test_preferred_name_wins_and_is_sanitized(self):
        self.assertEqual(derive_channel("ignored", "My Channel"), "My-Channel")

    def test_youtube_handle_becomes_channel(self):
        self.assertEqual(derive_channel("https://www.youtube.com/@SomeHandle/videos"), "SomeHandle")


class RecentUrls(unittest.TestCase):
    def test_newest_url_moves_to_the_front(self):
        self.assertEqual(
            remember_recent(["https://a.example/1", "https://b.example/2"], "https://b.example/2"),
            ["https://b.example/2", "https://a.example/1"],
        )

    def test_empty_url_is_ignored(self):
        self.assertEqual(remember_recent(["https://a.example/1"], "  "), ["https://a.example/1"])


class GuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Never touch the real user settings while testing.
        self.folder = tempfile.TemporaryDirectory()
        settings = QSettings(
            os.path.join(self.folder.name, "test.ini"), QSettings.Format.IniFormat
        )
        settings.setValue("output_root", self.folder.name)
        settings.setValue("link_grabber", False)
        self.window = MainWindow(settings=settings)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QApplication.processEvents()
        self.folder.cleanup()

    def test_table_has_all_columns(self):
        self.assertEqual(self.window.table.model().columnCount(), len(COLUMNS))
        self.assertEqual(COLUMNS[:2], ("#", ""))

    def test_index_comes_before_the_checkbox_and_columns_can_move(self):
        header = self.window.table.horizontalHeader()
        self.assertTrue(header.sectionsMovable())
        self.assertTrue(header.isFirstSectionMovable())
        self.assertEqual(header.visualIndex(COL_INDEX), 0)
        self.assertEqual(header.visualIndex(COL_CHECK), 1)
        header.moveSection(header.visualIndex(COL_HOST), 0)
        self.assertEqual(header.visualIndex(COL_HOST), 0)
        self.assertEqual(header.visualIndex(COL_INDEX), 1)

    def test_extra_data_columns_start_hidden_and_can_be_shown(self):
        for column in (COL_UPLOADER, COL_FILE, COL_URL):
            self.assertTrue(self.window.table.isColumnHidden(column), COLUMNS[column])
        for column in (COL_HOST, COL_STATUS, COL_TITLE, COL_DURATION):
            self.assertFalse(self.window.table.isColumnHidden(column), COLUMNS[column])
        self.window._toggle_column(COL_UPLOADER, True)
        self.assertFalse(self.window.table.isColumnHidden(COL_UPLOADER))
        self.window._toggle_column(COL_UPLOADER, False)
        self.assertTrue(self.window.table.isColumnHidden(COL_UPLOADER))

    def test_header_menu_lists_columns_and_applies_the_choice(self):
        menu, handlers = self.window._build_column_menu()
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        self.assertNotIn("#", labels)                      # pinned, never hideable
        for name in ("Host", "Status", "Title", "Uploader", "File", "URL"):
            self.assertIn(name, labels)
        self.assertIn("Reset columns", labels)
        self.assertIn("Lock column layout", labels)

        uploader = [a for a in menu.actions() if a.text() == "Uploader"][0]
        self.assertFalse(uploader.isChecked())
        uploader.setChecked(True)
        handlers[uploader](True)
        self.assertFalse(self.window.table.isColumnHidden(COL_UPLOADER))

    def test_reset_columns_restores_order_and_visibility(self):
        header = self.window.table.horizontalHeader()
        self.window._toggle_column(COL_URL, True)
        header.moveSection(header.visualIndex(COL_TITLE), 0)
        self.window.table.setColumnWidth(COL_ID, 400)
        self.window._reset_columns()
        self.assertEqual(header.visualIndex(COL_INDEX), 0)
        self.assertTrue(self.window.table.isColumnHidden(COL_URL))
        self.assertEqual(self.window.table.columnWidth(COL_ID), COLUMN_WIDTHS[COL_ID])

    def test_locking_columns_stops_moving_and_resizing(self):
        header = self.window.table.horizontalHeader()
        self.window._set_columns_locked(True)
        self.assertFalse(header.sectionsMovable())
        self.assertEqual(
            header.sectionResizeMode(COL_ID), QHeaderView.ResizeMode.Fixed
        )
        self.window._set_columns_locked(False)
        self.assertTrue(header.sectionsMovable())
        self.assertEqual(
            header.sectionResizeMode(COL_ID), QHeaderView.ResizeMode.Interactive
        )

    def test_duration_and_file_columns_show_row_data(self):
        self.window.set_urls([{"url": URLS[0], "duration": 75}])
        self.window._on_progress(URLS[0], {"status": "done", "filepath": "C:/out/clip [111].mp4"})
        self.assertEqual(self.window.model.index(0, COL_DURATION).data(), "1:15")
        self.assertEqual(self.window.model.index(0, COL_FILE).data(), "clip [111].mp4")

    def test_host_column_shows_the_domain_beside_the_logo(self):
        self.window.set_urls(["https://www.tiktok.com/@viralfinds_hub/video/7669545"])
        index = self.window.model.index(0, COL_HOST)
        self.assertEqual(index.data(), "tiktok.com")
        self.assertFalse(index.data(Qt.ItemDataRole.DecorationRole).isNull())

    def test_every_button_got_an_icon(self):
        buttons = self.window.findChildren(QToolButton) + self.window.findChildren(QPushButton)
        named = [b for b in buttons if b.property("iconName")]
        self.assertTrue(named)
        for button in named:
            self.assertFalse(button.icon().isNull(), button.property("iconName"))

    def test_urls_fill_the_table_as_queued(self):
        self.window.set_urls(URLS)
        self.assertEqual(self.window.table.model().rowCount(), 2)
        self.assertEqual(self.window.counter.text(), "2 ● 0")

    def test_link_grabber_merges_and_deduplicates_rows(self):
        self.window.add_grab_urls([URLS[0]])
        self.assertEqual(self.window.add_urls([URLS[0], URLS[1]]), 1)
        self.assertEqual(self.window.grab_model.urls(), URLS)
        self.assertEqual(self.window.model.rowCount(), 0)

    def test_grabber_monitor_reads_the_background_sync(self):
        window = self.window
        window.set_urls(URLS)                       # 2 in the download queue
        window._grabber_job = True
        window._grab_current = URLS[0]
        window._grab_queue = [URLS[1]]
        window._grab_added, window._grab_dupes = 3, 1
        window._show_grab_panel("Analyzing…", begin=True)
        panel = window.grab_panel
        self.assertFalse(panel.isHidden())
        self.assertEqual(panel.reading("Found Link(s)"), "3")
        self.assertEqual(panel.reading("Duplicate(s)"), "1")
        self.assertEqual(panel.reading("Link queue"), "1")
        self.assertEqual(panel.reading("Grabber list"), "0")
        self.assertEqual(panel.reading("Download queue"), "2")
        self.assertEqual(panel.reading("Status"), "Analyzing…")
        self.assertTrue(panel.abort_btn.isEnabled())
        self.assertEqual(panel.toolTip(), URLS[0])

    def test_grabber_monitor_is_a_desktop_tool_window(self):
        window = self.window
        panel = window.grab_panel
        self.assertTrue(panel.isWindow())
        self.assertTrue(bool(panel.windowFlags() & Qt.WindowType.Tool))
        window.show()
        window.resize(1000, 640)
        window._show_grab_panel("Analyzing…", begin=True)
        QApplication.processEvents()
        self.assertFalse(panel.isHidden())
        stuck = QPoint(48, 64)
        panel.move(stuck)
        panel.user_placed = True
        window.resize(1200, 700)
        QApplication.processEvents()
        self.assertEqual(panel.pos(), stuck)

    def test_grabber_monitor_freezes_when_the_run_ends(self):
        window = self.window
        window._show_grab_panel("Analyzing…", begin=True)
        window._end_grab_panel("Done!")
        panel = window.grab_panel
        self.assertEqual(panel.reading("Status"), "Done!")
        self.assertFalse(panel.abort_btn.isEnabled())
        self.assertTrue(panel.reading("Duration").endswith("s"))

    def test_aborting_the_monitor_clears_the_queue(self):
        self.window.act_grabber.setChecked(False)
        self.window._queue_grab_urls(URLS)
        self.window._show_grab_panel("Analyzing…", begin=True)
        self.window.grab_panel.abort_btn.click()
        self.assertEqual(self.window._grab_queue, [])
        self.assertEqual(self.window.grab_panel.reading("Status"), "Aborted")

    def test_tools_menu_reopens_the_monitor_when_idle(self):
        panel = self.window.grab_panel
        self.assertTrue(panel.isHidden())
        self.window._show_grab_monitor()
        self.assertFalse(panel.isHidden())
        self.assertEqual(panel.reading("Status"), "Idle")

    def test_pinned_monitor_stays_open_after_the_run(self):
        panel = self.window.grab_panel
        self.window._show_grab_panel("Analyzing…", begin=True)
        panel.pin_btn.setChecked(True)
        self.window._hide_grab_panel()
        self.assertFalse(panel.isHidden())
        panel.pin_btn.setChecked(False)
        self.window._hide_grab_panel()
        self.assertTrue(panel.isHidden())

    def test_duplicate_links_are_counted_while_a_run_syncs(self):
        window = self.window
        window._grabber_job = True
        window._show_grab_panel("Analyzing…", begin=True)
        window.add_grab_urls(URLS)
        window.add_grab_urls([URLS[0]])
        self.assertEqual((window._grab_added, window._grab_dupes), (2, 1))
        self.assertEqual(window.grab_panel.reading("Grabber list"), "2")
        self.assertEqual(window.grab_panel.reading("Duplicate(s)"), "1")

    def test_toolbar_exposes_the_job_actions(self):
        bar = self.window.start_btn.parent()
        self.assertEqual(bar.objectName(), "toolBar")
        names = [
            b.property("iconName")
            for b in bar.findChildren(QToolButton)
        ]
        self.assertEqual(
            names,
            [
                "play", "stop", "move-up", "move-down", "link",
                "collect", "download", "clear", "settings", "globe",
            ],
        )
        self.assertTrue(self.window.clip_btn.isCheckable())

    def test_toolbar_clipboard_tracks_the_grabber_toggle(self):
        self.window.act_grabber.setChecked(True)
        self.window._sync_grabber_ui()
        self.assertTrue(self.window.clip_btn.isChecked())
        self.window.act_grabber.setChecked(False)
        self.window._sync_grabber_ui()
        self.assertFalse(self.window.clip_btn.isChecked())

    def test_toolbar_move_reorders_selected_download_rows(self):
        self.window.set_urls(URLS)
        self.window.table.selectRow(1)
        self.window.up_btn.click()
        self.assertEqual(self.window.model.urls(), [URLS[1], URLS[0]])

    def test_action_bar_adds_links_then_filters_then_starts(self):
        bar = self.window.action_bar
        labels = [
            b.text() for b in bar.findChildren(QToolButton)
            if b.parent() is bar and b.text()
        ]
        self.assertEqual(
            labels,
            ["Add New Links", "Continue login", "Cancel",
             "Add to downloads", "Start all Downloads"],
        )
        self.assertTrue(self.window.clip_toggle.isCheckable())
        self.assertEqual(self.window.collect_btn.text(), "Extract")

    def test_add_new_links_button_carries_the_other_ways_in(self):
        menu = self.window.add_new_btn.menu()
        self.assertIsNotNone(menu)
        self.assertEqual(
            [a.text() for a in menu.actions()],
            ["Paste links…", "Add links from the clipboard", "Open download folder"],
        )
        for action in menu.actions():
            self.assertFalse(action.icon().isNull(), action.text())

    def test_start_button_menu_can_ignore_the_checks(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append(worker)
        self.window.set_urls(URLS)
        self.window.model.set_checked_rows([0], True)
        actions = self.window.download_btn.menu().actions()
        self.assertEqual(
            [a.text() for a in actions],
            ["Start all downloads", "Start checked only", "Cancel job"],
        )
        actions[1].trigger()
        self.assertEqual(started[0].urls, [URLS[0]])
        actions[0].trigger()
        self.assertEqual(started[1].urls, URLS)

    def test_add_from_clipboard_lists_supported_links(self):
        QApplication.clipboard().setText(f"look at {URLS[0]} and {URLS[1]}")
        self.window._add_from_clipboard()
        self.assertEqual(self.window.grab_model.urls(), URLS)
        self.assertEqual(self.window.tabs.currentIndex(), 1)

    def test_filter_box_narrows_both_tables(self):
        self.window.set_urls(URLS)
        self.window.add_grab_urls(URLS)
        self.window.filter_edit.setText("222")
        self.assertEqual(self.window.table.model().rowCount(), 1)
        self.assertEqual(self.window.grab_table.model().rowCount(), 1)
        self.window.filter_edit.clear()
        self.assertEqual(self.window.table.model().rowCount(), 2)

    def test_filter_field_picker_scopes_the_search(self):
        self.window.set_urls([{"url": URLS[0], "title": "sunset clip"}])
        by_field = {
            self.window.filter_field.itemData(i): i
            for i in range(self.window.filter_field.count())
        }
        self.window.filter_field.setCurrentIndex(by_field["title"])
        self.window.filter_edit.setText("sunset")
        self.assertEqual(self.window.table.model().rowCount(), 1)
        self.assertEqual(self.window.filter_edit.placeholderText(), "Filter")
        self.window.filter_field.setCurrentIndex(by_field["id"])
        self.assertEqual(self.window.table.model().rowCount(), 0)

    def test_views_panel_filters_by_kind_and_host(self):
        window = self.window
        window.set_urls([
            URLS[0],
            "https://www.tiktok.com/@x/photo/99",
        ])
        window._refresh_views()
        kinds = {box.text().split()[0]: box for box in window.views._kind_boxes.values()}
        self.assertIn("Video", " ".join(box.text() for box in window.views._kind_boxes.values()))
        self.assertGreater(window.views.host_list.count(), 0)
        window.views._kind_boxes["video"].setChecked(False)
        self.assertEqual(window.table.model().rowCount(), 1)
        window.views._kind_boxes["video"].setChecked(True)
        facebook = None
        for row in range(window.views.host_list.count()):
            item = window.views.host_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == "facebook.com":
                facebook = item
        self.assertIsNotNone(facebook)
        facebook.setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(window.table.model().rowCount(), 1)

    def test_save_path_browse_commits_the_folder(self):
        window = self.window
        window.save_path_edit.setText(r"D:\Videos")
        window._commit_save_path()
        self.assertEqual(window._settings.value("output_root"), os.path.normpath(r"D:\Videos"))
        self.assertEqual(window.save_path_edit.text(), os.path.normpath(r"D:\Videos"))
        self.assertTrue(window.status.isHidden())

    def test_overview_counts_bytes_on_the_download_tab(self):
        self.window.set_urls([{"url": URLS[0], "total": 8_000_000}, {"url": URLS[1]}])
        self.window._on_progress(URLS[0], {
            "status": "downloading", "percent": 50.0, "total": 8_000_000,
            "speed": 1_000_000, "eta": 4,
        })
        self.window._refresh_stats()       # bytes and speed follow the poll timer
        self.assertEqual(self.window.overview.title.text(), "Download Overview")
        self.assertEqual(self.window.overview.reading("Links"), "2")
        self.assertEqual(self.window.overview.reading("Total"), "8 MB")
        self.assertEqual(self.window.overview.reading("Loaded"), "4 MB")
        self.assertEqual(self.window.overview.reading("Left"), "4 MB")
        self.assertEqual(self.window.overview.reading("Speed"), "977 KB/s")
        self.assertEqual(self.window.overview.reading("ETA"), "0:04")
        self.assertEqual(self.window.overview.reading("Running"), "1")
        self.assertEqual(self.window.overview.reading("Hosts"), "1")

    def test_overview_switches_to_the_grabber_readings(self):
        self.window.add_grab_urls([{"url": URLS[0], "total": 2_000_000}, {"url": URLS[1]}])
        self.window.grab_model.set_checked_rows([0], True)
        self.window.tabs.setCurrentIndex(1)
        self.assertEqual(self.window.overview.title.text(), "Grabber Overview")
        self.assertEqual(self.window.overview.reading("Links"), "2")
        self.assertEqual(self.window.overview.reading("Checked"), "1")
        self.assertEqual(self.window.overview.reading("Known"), "1")
        self.assertEqual(self.window.overview.reading("Unknown"), "1")
        self.window.tabs.setCurrentIndex(0)
        self.assertEqual(self.window.overview.title.text(), "Download Overview")

    def test_overview_close_button_hides_it_and_stops_polling(self):
        self.window.act_status.trigger()                  # status strip off too
        self.assertFalse(self.window.overview.isHidden())
        self.window.overview.close_btn.click()
        self.assertTrue(self.window.overview.isHidden())
        self.assertFalse(self.window.act_overview.isChecked())
        self.assertFalse(self.window._stats_timer.isActive())
        self.window.act_overview.trigger()
        self.assertFalse(self.window.overview.isHidden())
        self.assertTrue(self.window._stats_timer.isActive())
        self.window._save_settings()
        reopened = MainWindow(settings=self.window._settings)
        self.assertFalse(reopened.overview.isHidden())
        reopened.close()

    def test_view_menu_hides_the_bottom_tools(self):
        self.assertFalse(self.window.action_bar.isHidden())
        self.window.act_action_bar.trigger()
        self.assertTrue(self.window.action_bar.isHidden())
        self.assertFalse(self.window.act_action_bar.isChecked())
        self.window._save_settings()
        reopened = MainWindow(settings=self.window._settings)
        self.assertTrue(reopened.action_bar.isHidden())
        reopened.close()

    def test_tabs_split_the_list_from_the_url_grabber(self):
        self.assertEqual(self.window.tabs.tabText(0), "Download")
        self.assertEqual(self.window.tabs.tabText(1), "Grabber")
        self.assertEqual(self.window.tabs.currentIndex(), 0)
        self.assertTrue(self.window.tabs.widget(0).isAncestorOf(self.window.table))
        self.assertTrue(self.window.tabs.widget(1).isAncestorOf(self.window.grab_table))
        self.assertTrue(self.window.grab_table.isColumnHidden(COL_PROGRESS))
        self.assertFalse(self.window.tabs.widget(1).isAncestorOf(self.window.source_combo))
        self.assertFalse(self.window.download_btn.isHidden())
        self.assertTrue(self.window.add_btn.isHidden())
        self.window.tabs.setCurrentIndex(1)
        self.assertTrue(self.window.download_btn.isHidden())
        self.assertFalse(self.window.add_btn.isHidden())
        self.window.tabs.setCurrentIndex(0)
        self.assertFalse(self.window.download_btn.isHidden())
        self.assertTrue(self.window.add_btn.isHidden())

    def test_extract_fills_the_grabber_table_not_downloads(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append((worker, merge))
        self.window.source_edit.setText(URLS[0])
        self.window.set_urls([URLS[1]])
        self.window._start_collect()
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertTrue(started[0][1])
        self.assertEqual(self.window.model.urls(), [URLS[1]])
        self.window.add_grab_urls([URLS[0]])
        self.assertEqual(self.window.grab_model.urls(), [URLS[0]])
        self.assertEqual(self.window.model.urls(), [URLS[1]])

    def test_extract_loader_syncs_listed_links(self):
        window = self.window
        window.tabs.setCurrentIndex(1)
        window._collecting = True
        window._grab_current = URLS[0]
        window._sync_extract_loader()
        loader = window.extract_loader
        self.assertFalse(loader.isHidden())
        self.assertEqual(loader.title.text(), "Extracting links")
        self.assertEqual(loader.detail.text(), URLS[0])
        self.assertEqual(loader.count.text(), "Looking for links…")
        window.add_grab_urls([URLS[0]])
        self.assertEqual(loader.count.text(), "1 listed")
        self.assertEqual(window.grab_panel.reading("Status"), "Extracting…")
        self.assertEqual(window.counter.text(), "1 listed")
        window._collecting = False
        window._hide_extract_loader()
        self.assertTrue(loader.isHidden())

    def test_waiting_login_updates_the_extract_loader(self):
        window = self.window
        window._collecting = True
        window._grab_current = URLS[0]
        window._sync_extract_loader()
        window._on_waiting_login()
        self.assertEqual(window.extract_loader.title.text(), "Waiting for login")
        self.assertTrue(window.continue_btn.isEnabled())
        self.assertEqual(window.grab_panel.reading("Status"), "Waiting for login")

    def test_add_links_button_prompts_then_extracts(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append(worker)
        self.window._ask_links = lambda current="": URLS[0]
        self.window._add_links()
        self.assertEqual(self.window.source_edit.text(), URLS[0])
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertEqual(started[0].url, URLS[0])

    def test_add_links_dialog_prefills_and_reads_one_link_per_line(self):
        self.window.source_edit.setText(URLS[0])
        dialog = AddLinksDialog(self.window.source_edit.text(), self.window)
        self.assertEqual(dialog.text(), URLS[0])
        dialog.edit.setPlainText(f"{URLS[0]}\n{URLS[1]}\n")
        self.assertEqual(dialog.text().splitlines(), URLS)
        self.assertTrue(dialog.edit.placeholderText())

    def test_pasting_many_links_analyzes_them_with_the_watcher_off(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append(worker)
        self.window.act_grabber.setChecked(False)
        self.window._ask_links = lambda current="": f"{URLS[0]}\n{URLS[1]}\nnot-a-link"
        self.window._add_links()
        self.assertEqual(started[0].url, URLS[0])          # first one runs at once
        self.assertEqual(self.window._grab_queue, [URLS[1]])
        self.assertEqual(self.window.source_edit.text(), "")
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        log = self.window.log.toPlainText()
        self.assertIn("Link Grabber queued 2 link(s).", log)
        self.assertIn("Skipped 1 link(s)", log)

    def test_pasting_links_already_listed_queues_nothing(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append(worker)
        self.window.add_grab_urls(URLS)
        self.window._ask_links = lambda current="": "\n".join(URLS)
        self.window._add_links()
        self.assertEqual(started, [])
        self.assertEqual(self.window._grab_queue, [])
        self.assertFalse(self.window._grab_manual)
        self.assertIn("Skipped 2 link(s)", self.window.log.toPlainText())

    def test_pasting_unsupported_lines_only_warns(self):
        started, warned = [], []
        self.window._run = lambda worker, merge=False: started.append(worker)
        self.window._ask_links = lambda current="": "not-a-link\nalso nothing"
        with patch.object(window_module, "alert", lambda *args: warned.append(args)):
            self.window._add_links()
        self.assertEqual(started, [])
        self.assertEqual(self.window._grab_queue, [])
        self.assertEqual(warned[0][1], "warning")

    def test_cancelling_the_add_links_dialog_changes_nothing(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append(worker)
        self.window._ask_links = lambda current="": None
        self.window._add_links()
        self.assertEqual(started, [])
        self.assertEqual(self.window._grab_queue, [])

    def test_add_to_downloads_moves_grabber_rows(self):
        self.window.add_grab_urls(URLS)
        self.window._add_to_downloads()
        self.assertEqual(self.window.model.urls(), URLS)
        self.assertEqual(self.window.grab_model.rowCount(), 0)
        self.assertEqual(self.window.tabs.currentIndex(), 0)
        self.window.add_grab_urls([URLS[0], "https://www.facebook.com/reel/333"])
        self.window._add_to_downloads()
        self.assertEqual(self.window.model.urls(), URLS + ["https://www.facebook.com/reel/333"])
        self.assertEqual(self.window.grab_model.rowCount(), 0)

    def test_menu_bar_groups_the_actions(self):
        titles = [a.text() for a in self.window.menuBar().actions()]
        self.assertEqual(titles, ["&File", "&Edit", "&View", "&Tools", "&Help"])
        self.assertIs(self.window.menuBar(), self.window.menu_bar)
        self.assertIs(self.window.menu_bar.parentWidget(), self.window)

    def test_menu_bar_corners_hold_the_logo_and_window_controls(self):
        bar = self.window.menu_bar
        self.assertIs(bar.cornerWidget(Qt.Corner.TopLeftCorner), self.window.logo)
        self.assertIs(bar.cornerWidget(Qt.Corner.TopRightCorner), self.window.win_controls)
        self.assertFalse(self.window.logo.pixmap().isNull())
        for button in (self.window.min_btn, self.window.max_btn, self.window.close_btn):
            self.assertFalse(button.icon().isNull(), button.toolTip())

    def test_window_has_no_native_frame(self):
        self.assertTrue(
            self.window.windowFlags() & Qt.WindowType.FramelessWindowHint
        )

    def test_maximise_button_flips_to_restore(self):
        self.window._toggle_maximized()
        self.assertTrue(self.window.isMaximized())
        self.assertEqual(self.window.max_btn.property("iconName"), "win-restore")
        self.window._toggle_maximized()
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.max_btn.property("iconName"), "win-maximize")

    def test_frame_edges_only_grab_the_window_border(self):
        window = self.window
        self.assertFalse(window._resize_edges(QPoint(400, 300)))
        self.assertEqual(
            window._resize_edges(QPoint(0, 0)),
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
        )
        self.assertEqual(
            window._resize_edges(QPoint(window.width() - 1, window.height() - 1)),
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        )
        window.showMaximized()
        self.assertFalse(window._resize_edges(QPoint(0, 0)))

    def test_panels_reach_the_window_edge(self):
        window = self.window
        self.assertEqual(window.contentsMargins().left(), 0)
        self.assertEqual(window.contentsMargins().top(), 0)
        layout = window.centralWidget().layout()
        self.assertEqual(layout.contentsMargins().left(), 0)
        self.assertEqual(layout.contentsMargins().top(), 0)
        window.show()
        QApplication.processEvents()
        self.assertEqual(window.menu_bar.x(), 0)
        self.assertEqual(window.start_btn.parent().x(), 0)
        self.assertEqual(window.start_btn.parent().width(), window.width())

    def test_edge_band_grabs_presses_that_land_on_a_child(self):
        window = self.window
        window.show()
        QApplication.processEvents()

        def press(x, y):
            spot = window.mapToGlobal(QPoint(x, y))
            return QMouseEvent(
                QEvent.Type.MouseButtonPress, QPointF(0, 0), QPointF(spot), QPointF(spot),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

        self.assertEqual(
            window._frame_edges_for(window.table, press(1, window.height() // 2)),
            Qt.Edge.LeftEdge,
        )
        self.assertFalse(
            window._frame_edges_for(window.table, press(window.width() // 2, 300))
        )
        window.showMaximized()
        self.assertFalse(window._frame_edges_for(window.table, press(1, 300)))

    def test_menu_items_carry_the_keyboard_shortcuts(self):
        pairs = {
            self.window.act_download: "Ctrl+D",
            self.window.act_add: "Ctrl+Shift+D",
            self.window.act_settings: "Ctrl+,",
            self.window.act_log: "Ctrl+L",
            self.window.act_grabber: "Ctrl+G",
        }
        for action, keys in pairs.items():
            self.assertEqual(action.shortcut().toString(), keys, action.text())

    def test_view_menu_log_item_follows_the_log_panel(self):
        visible = not self.window.log.isHidden()
        self.window.act_log.trigger()
        self.assertEqual(self.window.log.isHidden(), visible)
        self.assertEqual(self.window.act_log.isChecked(), not visible)
        self.window._toggle_log()
        self.assertEqual(self.window.act_log.isChecked(), visible)

    def test_tools_menu_owns_the_grabber_and_the_strip_reports_it(self):
        self.window._toggle_grabber(False)
        self.assertFalse(self.window.act_grabber.isChecked())
        self.assertEqual(self.window.stats["grabber"].text(), "Grabber off")
        self.window.act_grabber.trigger()
        self.assertTrue(self.window.act_grabber.isChecked())
        self.assertEqual(self.window.stats["grabber"].text(), "Grabber on")

    def test_view_menu_locks_the_column_layout(self):
        self.window.act_lock_columns.trigger()
        self.assertTrue(self.window._columns_locked)
        self.assertFalse(self.window.table.horizontalHeader().sectionsMovable())
        self.window.act_lock_columns.trigger()
        self.assertFalse(self.window._columns_locked)

    def test_busy_disables_the_job_menu_items(self):
        self.window._set_busy(True)
        self.assertFalse(self.window.act_collect.isEnabled())
        self.assertFalse(self.window.act_add.isEnabled())
        self.assertFalse(self.window.act_download.isEnabled())
        self.assertTrue(self.window.act_cancel.isEnabled())
        self.window._set_busy(False)
        self.assertTrue(self.window.act_collect.isEnabled())
        self.assertTrue(self.window.act_add.isEnabled())
        self.assertFalse(self.window.act_cancel.isEnabled())

    def test_edit_menu_copies_selected_rows(self):
        self.window.set_urls(URLS)
        self.window.table.selectRow(0)
        self.window._copy_urls()
        self.assertEqual(QApplication.clipboard().text(), URLS[0])

    def test_remove_all_empties_the_table(self):
        self.window.set_urls(URLS)
        self.window._remove_all()
        self.assertEqual(self.window.model.rowCount(), 0)

    def test_collect_passes_the_playlist_answer_to_the_worker(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append(worker)
        mix = "https://www.youtube.com/watch?v=OaPcBJnGU5M&list=RDOaPcBJnGU5M&start_radio=1"

        self.window.source_edit.setText(mix)
        self.window._playlist_choice = lambda url: (url.split("&start_radio")[0], True)
        self.window._start_collect()
        self.assertTrue(started[0].feed)
        self.assertIn("list=RDOaPcBJnGU5M", started[0].url)

        self.window.source_edit.setText(mix)
        self.window._playlist_choice = lambda _: (
            "https://www.youtube.com/watch?v=OaPcBJnGU5M", False,
        )
        self.window._start_collect()
        self.assertFalse(started[1].feed)
        self.assertNotIn("list=", started[1].url)

    def test_cancelling_the_playlist_question_collects_nothing(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append(worker)
        self.window.source_edit.setText(
            "https://www.youtube.com/watch?v=OaPcBJnGU5M&list=RDOaPcBJnGU5M"
        )
        self.window._playlist_choice = lambda _: None
        self.window._start_collect()
        self.assertEqual(started, [])

    def test_link_grabber_queues_unique_background_links(self):
        self.window.act_grabber.setChecked(False)
        self.assertEqual(self.window._queue_grab_urls([URLS[0], URLS[0], URLS[1]]), 2)
        self.assertEqual(self.window._grab_queue, URLS)

    def test_progress_updates_the_counter(self):
        self.window.set_urls(URLS)
        self.window._on_progress(URLS[0], {"status": "done"})
        self.window._on_progress(URLS[1], {"status": "failed"})
        self.assertEqual(self.window.counter.text(), "2 ● 1")

    def test_new_list_shows_reel_one_at_the_top(self):
        # A leftover sort must not hide or reorder a fresh collection.
        self.window.set_urls(URLS)
        self.window.table.sortByColumn(COL_ID, Qt.SortOrder.DescendingOrder)
        self.window.set_urls(URLS)
        model = self.window.table.model()
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.index(0, COL_INDEX).data(), "1")

    def test_clear_empties_the_table(self):
        self.window.set_urls(URLS)
        self.window.clear_rows()
        self.assertEqual(self.window.table.model().rowCount(), 0)
        self.assertEqual(self.window.counter.text(), "0 ● 0")

    def test_table_has_checkboxes_and_hides_the_url_column(self):
        self.window.set_urls(URLS)
        self.assertEqual(
            self.window.table.selectionMode(),
            QAbstractItemView.SelectionMode.ExtendedSelection,
        )
        self.assertTrue(self.window.table.isColumnHidden(COL_URL))
        check = self.window.model.index(0, COL_CHECK)
        self.assertTrue(self.window.model.flags(check) & Qt.ItemFlag.ItemIsUserCheckable)
        self.window.model.setData(check, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        self.assertEqual(self.window.model.checked_urls(), [URLS[0]])

    def test_remove_selected_drops_rows_from_the_list(self):
        self.window.set_urls(URLS)
        self.window.table.selectRow(0)
        self.window._remove_selected()
        self.assertEqual(self.window.model.urls(), [URLS[1]])
        self.assertEqual(self.window.counter.text(), "1 ● 0")

    def test_remove_uses_checked_rows_when_nothing_is_selected(self):
        self.window.set_urls(URLS)
        self.window.model.set_checked_rows([1], True)
        self.window._remove_selected()
        self.assertEqual(self.window.model.urls(), [URLS[0]])

    def test_starts_in_dark_theme(self):
        self.assertTrue(theme.DEFAULT_DARK)
        self.assertTrue(self.window._dark)
        self.assertTrue(self.window.act_theme.isChecked())

    def test_theme_toggle_follows_the_view_menu_item(self):
        self.window._toggle_theme()
        self.assertFalse(self.window._dark)
        self.assertFalse(self.window.act_theme.isChecked())
        self.window.act_theme.trigger()
        self.assertTrue(self.window._dark)
        self.assertTrue(self.window.act_theme.isChecked())

    def test_theme_sets_the_window_frame_color_scheme(self):
        # The native title bar follows the color scheme, not the stylesheet.
        self.assertEqual(theme.color_scheme(False), Qt.ColorScheme.Light)
        self.assertEqual(theme.color_scheme(True), Qt.ColorScheme.Dark)

        asked = []
        original = QApplication.instance().styleHints().setColorScheme
        QApplication.instance().styleHints().setColorScheme = asked.append
        try:
            self.window._dark = False
            self.window._apply_theme()
            self.window._toggle_theme()   # back to dark
        finally:
            QApplication.instance().styleHints().setColorScheme = original
        self.assertEqual(asked, [Qt.ColorScheme.Light, Qt.ColorScheme.Dark])

    def test_settings_round_trip(self):
        self.window.source_edit.setText("https://www.facebook.com/jireel/reels")
        self.window._settings.setValue("channel", "jireel")
        self.window._settings.setValue("workers", 7)
        self.window._save_settings()
        reopened = MainWindow(settings=self.window._settings)
        self.assertEqual(reopened.source_edit.text(), "https://www.facebook.com/jireel/reels")
        self.assertEqual(reopened._channel(), "jireel")
        self.assertEqual(reopened._speed()["workers"], 7)
        reopened.close()

    def test_url_field_keeps_a_recent_dropdown(self):
        first = "https://www.tiktok.com/@viralfinds_hub"
        second = "https://www.facebook.com/jireel/reels"
        self.window._remember_url(first)
        self.window._remember_url(second)
        self.assertEqual(
            [self.window.source_combo.itemText(i) for i in range(self.window.source_combo.count())],
            [second, first],
        )
        self.assertEqual(self.window.source_edit.text(), second)
        self.window._save_settings()
        reopened = MainWindow(settings=self.window._settings)
        self.assertEqual(reopened.source_combo.count(), 2)
        self.assertEqual(reopened.source_combo.itemText(0), second)
        self.assertEqual(reopened.source_edit.text(), second)
        reopened.source_combo.setCurrentIndex(1)
        self.assertEqual(reopened.source_edit.text(), first)
        reopened.close()

    def test_settings_dialog_saves_tool_paths(self):
        dialog = SettingsDialog(self.window._settings, self.window)
        dialog.channel.setText("my page")
        dialog.output.setText("downloads")
        dialog.filename.setText("%(id)s.%(ext)s")
        dialog.chrome.setText("C:/Tools/chrome.exe")
        dialog.ffmpeg.setText("C:/Tools/ffmpeg.exe")
        dialog.workers.setValue(6)
        dialog.cookies_browser.setCurrentIndex(dialog.cookies_browser.findData("chrome"))
        dialog.cookies_profile.setText("Default")
        dialog.link_grabber.setChecked(False)
        dialog.auto_update.setChecked(False)
        dialog.accept()
        self.assertEqual(self.window._settings.value("channel"), "my page")
        self.assertEqual(self.window._settings.value("output_root"), "downloads")
        self.assertEqual(self.window._settings.value("filename_template"), "%(id)s.%(ext)s")
        self.assertEqual(self.window._settings.value("chrome_binary"), "C:/Tools/chrome.exe")
        self.assertEqual(self.window._settings.value("ffmpeg_location"), "C:/Tools/ffmpeg.exe")
        self.assertEqual(int(self.window._settings.value("workers")), 6)
        self.assertEqual(self.window._settings.value("cookies_browser"), "chrome")
        self.assertEqual(self.window._settings.value("cookies_profile"), "Default")
        self.assertFalse(self.window._settings.value("link_grabber", type=bool))
        self.assertFalse(self.window._settings.value("auto_update", type=bool))
        self.assertEqual(self.window._speed()["cookies_browser"], "chrome:Default")

    def test_runtime_auto_update_defaults_on(self):
        dialog = SettingsDialog(self.window._settings, self.window)
        self.assertTrue(dialog.auto_update.isChecked())
        dialog.restore_defaults()
        self.assertTrue(dialog.auto_update.isChecked())

    def test_default_output_folder_uses_platform_app_folder(self):
        expected = default_output_root()
        self.assertTrue(expected.endswith(APP_FOLDER_NAME))
        blank = QSettings(
            os.path.join(self.folder.name, "blank.ini"), QSettings.Format.IniFormat
        )
        dialog = SettingsDialog(blank, self.window)
        self.assertEqual(dialog.output.text(), expected)
        dialog.restore_defaults()
        self.assertEqual(dialog.output.text(), expected)

    def test_list_progress_is_stored_and_restored(self):
        self.window.source_edit.setText("https://www.facebook.com/jireel/reels")
        self.window.set_urls(URLS)
        self.window._on_progress(URLS[0], {"status": "done", "filepath": "a.mp4"})
        self.window._on_progress(URLS[1], {"status": "downloading", "percent": 42.0, "total": 1000})
        self.window._flush_store()
        self.assertEqual(self.window.download_btn.text(), "Continue Downloads")
        self.window._save_settings()
        reopened = MainWindow(settings=self.window._settings)
        self.assertEqual(reopened.model.rowCount(), 2)
        self.assertEqual(reopened.model.reel_at(0).status, "done")
        self.assertEqual(reopened.model.reel_at(1).status, "queued")
        self.assertAlmostEqual(reopened.model.reel_at(1).percent, 42.0)
        self.assertEqual(reopened.model.pending_urls(), [URLS[1]])
        self.assertEqual(reopened.download_btn.text(), "Continue Downloads")
        reopened.close()


if __name__ == "__main__":
    unittest.main()
