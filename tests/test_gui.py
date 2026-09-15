"""Smoke tests for the PySide6 window (offscreen, no Chrome, no downloads)."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.fonts import register_fonts

register_fonts()

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt, QThreadPool
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
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
from app.gui.dialogs.platforms import PlatformsDialog
from app.gui.widgets import GrabberPanel
from app.core.runtime import APP_FOLDER_NAME, default_output_root
from app.gui.dialogs.settings import SettingsDialog
from app.gui.jobs import JobWorker

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
            "platform-douyin", "platform-kuaishou", "platform-pinterest", "platform-generic",
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

    def test_bilibili_video_uses_the_id(self):
        self.assertEqual(
            derive_channel(
                "https://www.bilibili.tv/en/video/4794551511289856"
                "?bstar_from=bstar-web.homepage.recommend.all"
            ),
            "4794551511289856",
        )

    def test_douyin_modal_uses_the_id(self):
        self.assertEqual(
            derive_channel(
                "https://www.douyin.com/jingxuan?modal_id=7683008214744581018"
            ),
            "7683008214744581018",
        )


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
        self.state_folder = tempfile.TemporaryDirectory()
        settings = QSettings(
            os.path.join(self.folder.name, "test.ini"), QSettings.Format.IniFormat
        )
        settings.setValue("output_root", self.folder.name)
        settings.setValue("link_grabber", False)
        settings.setValue("close_to_tray", False)
        self._state_patch = patch("app.core.runtime.state_dir", return_value=self.state_folder.name)
        self._state_patch.start()
        self.window = MainWindow(settings=settings)

    def tearDown(self):
        self.window._quitting = True
        self.window.close()
        self.window.deleteLater()
        QApplication.processEvents()
        self._state_patch.stop()
        self.folder.cleanup()
        self.state_folder.cleanup()

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
        for name in ("Hoster", "Status", "Name", "Uploader", "Save to", "Download from", "Added"):
            self.assertIn(name, labels)
        self.assertIn("Reset columns", labels)
        self.assertIn("Lock column layout", labels)
        self.assertIn("Horizontal scrollbar", labels)
        scroll = [a for a in menu.actions() if a.text() == "Horizontal scrollbar"][0]
        self.assertFalse(scroll.isChecked())
        handlers[scroll](True)
        self.assertEqual(
            self.window.table.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
        )
        self.assertTrue(self.window._settings.value("h_scrollbar", type=bool))

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

    def test_globe_tooltip_is_not_the_update_string(self):
        tip = self.window.sites_btn.toolTip()
        self.assertNotIn("yt-dlp", tip)
        self.assertNotIn("FFmpeg", tip)
        self.assertIn("platform", tip.lower())

    def test_globe_opens_platforms_dialog(self):
        with patch.object(PlatformsDialog, "exec", return_value=0) as shown:
            self.window.sites_btn.click()
        shown.assert_called_once()

    def test_help_supported_sites_opens_platforms_dialog(self):
        with patch.object(PlatformsDialog, "exec", return_value=0) as shown:
            self.window._show_supported_sites()
        shown.assert_called_once()

    def test_platforms_dialog_lists_active_and_coming_soon(self):
        dialog = PlatformsDialog(self.window)
        labels = [child.text() for child in dialog.findChildren(QLabel)]
        self.assertIn("Active", labels)
        self.assertIn("Coming soon", labels)
        self.assertIn("Facebook", labels)
        self.assertIn("Threads", labels)
        buttons = [
            button.text().replace("&", "")
            for button in dialog.findChildren(QPushButton)
        ]
        self.assertTrue({"Close", "OK"} & set(buttons))
        box = dialog.findChild(QDialogButtonBox)
        self.assertIsNotNone(box)
        dialog.close()

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

    def test_views_kind_narrows_both_tables(self):
        self.window.set_urls(URLS)
        self.window.add_grab_urls(URLS)
        self.window._refresh_views()
        self.assertEqual(self.window.table.model().rowCount(), 2)
        self.assertEqual(self.window.grab_table.model().rowCount(), 2)
        self.window.views._kind_boxes["video"].setChecked(False)
        self.assertEqual(self.window.table.model().rowCount(), 0)
        self.assertEqual(self.window.grab_table.model().rowCount(), 0)
        self.window.views._kind_boxes["video"].setChecked(True)
        self.assertEqual(self.window.table.model().rowCount(), 2)
        self.assertFalse(hasattr(self.window, "filter_edit"))
        self.assertFalse(hasattr(self.window, "filter_field"))

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

    def test_views_kind_and_host_show_icons(self):
        window = self.window
        window.set_urls([
            URLS[0],
            "https://www.tiktok.com/@x/photo/99",
        ])
        window._refresh_views()
        window.views.apply_icons("#e7ecf3")
        for key, box in window.views._kind_boxes.items():
            self.assertFalse(box.icon().isNull(), key)
        facebook = None
        for row in range(window.views.host_list.count()):
            item = window.views.host_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == "facebook.com":
                facebook = item
        self.assertIsNotNone(facebook)
        self.assertFalse(facebook.icon().isNull())

    def test_views_unknown_host_fetches_favicon_in_background(self):
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
            b"\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
            b"x\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00"
            b"\x00IEND\xaeB`\x82"
        )
        fetched = []

        def fake_fetch(domain, dest_dir, opener=None):
            fetched.append(domain)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, f"{domain}.ico")
            with open(dest, "wb") as f:
                f.write(png)
            return dest

        panel = self.window.views
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.gui.widgets.views.platform_icons.cache_dir", return_value=folder):
                with patch(
                    "app.gui.widgets.views.platform_icons.fetch_favicon",
                    side_effect=fake_fetch,
                ) as mocked:
                    panel.set_counts(
                        {"facebook.com": 2, "odd.host": 1, "-": 1},
                        {"video": 3, "music": 0, "image": 0},
                    )
                    for _ in range(80):
                        QApplication.processEvents()
                        if mocked.called:
                            break
                        time.sleep(0.01)
                    QThreadPool.globalInstance().waitForDone(2000)
                    QApplication.processEvents()
                    self.assertEqual(fetched, ["odd.host"])
                    mocked.assert_called_once()
                    odd = None
                    for row in range(panel.host_list.count()):
                        item = panel.host_list.item(row)
                        if item.data(Qt.ItemDataRole.UserRole) == "odd.host":
                            odd = item
                    self.assertIsNotNone(odd)
                    self.assertFalse(odd.icon().isNull())

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
        self.assertEqual(self.window.overview.reading("Done"), "0")
        self.assertEqual(self.window.overview.reading("Left"), "4 MB")
        self.assertEqual(self.window.overview.reading("Speed"), "977 KB/s")
        self.assertEqual(self.window.overview.reading("ETA"), "0:04")
        self.assertGreaterEqual(self.window.overview.maximumHeight(), 96)
        self.assertLessEqual(self.window.overview.maximumHeight(), 110)
        self.assertEqual(self.window.overview.minimumHeight(), 56)

    def test_overview_splitter_cannot_grow_past_max(self):
        cap = self.window.overview.maximumHeight()
        self.window.splitter.setSizes([80, 80, cap + 120])
        self.window._clamp_overview_size()
        self.assertLessEqual(self.window.splitter.sizes()[2], cap)
        self.assertGreaterEqual(self.window.splitter.sizes()[0], 80)

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

    def _menu_titles(self, table):
        return [action.text() for action in self.window._context_menu_for(table).actions()]

    def test_grabber_context_menu_is_a_review_list(self):
        self.window.add_grab_urls(URLS)
        self.window.grab_table.selectRow(0)
        titles = self._menu_titles(self.window.grab_table)
        self.assertIn("Add to downloads", titles)
        self.assertIn("Open in browser", titles)
        self.assertIn("Copy URL", titles)
        self.assertIn("Copy caption", titles)
        self.assertIn("Invert checks", titles)
        self.assertIn("Move up", titles)
        self.assertIn("Move down", titles)
        self.assertNotIn("Show downloaded file", titles)
        self.assertNotIn("Open directory", titles)
        self.assertNotIn("Open reel in browser", titles)

    def test_download_context_menu_still_shows_the_file(self):
        self.window.set_urls(URLS)
        self.window.table.selectRow(0)
        titles = self._menu_titles(self.window.table)
        self.assertIn("Show downloaded file", titles)
        self.assertIn("Open directory", titles)
        self.assertIn("Open reel in browser", titles)
        self.assertIn("Copy URL", titles)
        self.assertNotIn("Add to downloads", titles)
        self.assertNotIn("Open in browser", titles)

    def test_grabber_empty_area_offers_add_and_paste(self):
        self.window.add_grab_urls(URLS)
        self.window.grab_table.clearSelection()
        titles = self._menu_titles(self.window.grab_table)
        self.assertEqual(
            titles,
            ["Add new links", "Paste from clipboard", "Remove all from list"],
        )

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

    def test_remove_asks_before_deleting_the_file(self):
        path = os.path.join(self.folder.name, "clip [111].mp4")
        with open(path, "wb") as f:
            f.write(b"x")
        self.window.set_urls(URLS)
        self.window.model.apply_event(URLS[0], {"status": "done", "filepath": path})
        self.window.table.selectRow(0)
        with patch.object(window_module, "alert", return_value=QMessageBox.StandardButton.Yes) as asked:
            self.window._remove_selected()
        self.assertEqual(asked.call_args.args[1], "question")
        self.assertFalse(os.path.isfile(path))
        self.assertEqual(self.window.model.urls(), [URLS[1]])

    def test_remove_keeps_the_file_when_delete_is_declined(self):
        path = os.path.join(self.folder.name, "clip [111].mp4")
        with open(path, "wb") as f:
            f.write(b"x")
        self.window.set_urls(URLS)
        self.window.model.apply_event(URLS[0], {"status": "done", "filepath": path})
        self.window.table.selectRow(0)
        with patch.object(window_module, "alert", return_value=QMessageBox.StandardButton.No):
            self.window._remove_selected()
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(self.window.model.urls(), [URLS[1]])

    def test_failed_download_asks_to_delete_leftover_file(self):
        path = os.path.join(self.folder.name, "clip [111].mp4.part")
        with open(path, "wb") as f:
            f.write(b"x")
        self.window.set_urls(URLS)
        self.window.model.apply_event(URLS[0], {"status": "failed", "filepath": path})
        self.window._worker = type("W", (), {"mode": "download", "request_stop": lambda self: None})()
        with patch.object(window_module, "alert", return_value=QMessageBox.StandardButton.Yes) as asked:
            self.window._on_finished("1 item(s) failed.")
        self.assertEqual(asked.call_args_list[0].args[1], "question")
        self.assertEqual(asked.call_args_list[-1].args[1], "warning")
        self.assertFalse(os.path.isfile(path))
        self.assertEqual(self.window.model.urls(), URLS)

    def test_download_job_shows_a_finished_notification(self):
        self.window.set_urls(URLS)
        self.window.model.apply_event(URLS[0], {"status": "done"})
        self.window.model.apply_event(URLS[1], {"status": "done"})
        self.window._worker = type("W", (), {"mode": "download", "request_stop": lambda self: None})()
        with patch.object(window_module, "alert") as asked:
            self.window._on_finished("")
        self.assertEqual(asked.call_count, 1)
        self.assertEqual(asked.call_args.args[1], "info")
        self.assertEqual(asked.call_args.args[2], "Downloads finished")
        self.assertIn("2 of 2", asked.call_args.args[3])

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

    def test_settings_tools_tab_packs_fields_to_the_top(self):
        dialog = SettingsDialog(self.window._settings, self.window)
        form = dialog.chrome.parentWidget().layout()
        self.assertIsInstance(form, QFormLayout)
        self.assertEqual(
            form.formAlignment(),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self.assertEqual(
            dialog.chrome.sizePolicy().verticalPolicy(),
            QSizePolicy.Policy.Fixed,
        )
        self.assertEqual(
            dialog.cookies_curl.sizePolicy().verticalPolicy(),
            QSizePolicy.Policy.Expanding,
        )

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

    def test_properties_panel_updates_the_selected_title(self):
        self.window.set_urls([{"url": URLS[0], "title": "Old name"}])
        self.window.table.selectRow(0)
        self.window._toggle_properties(True)
        self.assertFalse(self.window.properties.isHidden())
        self.assertEqual(self.window.properties.name.text(), "Old name")
        self.assertEqual(self.window.properties.download_from.text(), URLS[0])
        self.window.properties.name.setText("New name")
        self.window.properties.comment.setText("note")
        self.window.properties.fields_edited.emit()
        self.assertEqual(self.window.model.reel_at(0).title, "New name")
        self.assertEqual(self.window.model.reel_at(0).comment, "note")
        self.window._save_settings()
        reopened = MainWindow(settings=self.window._settings)
        self.assertFalse(reopened.properties.isHidden())
        reopened.close()

    def test_grabber_auto_flags_live_on_window_and_settings(self):
        self.assertFalse(self.window.grab_add_at_top)
        self.assertFalse(self.window.grab_auto_confirm)
        self.assertFalse(self.window.grab_autostart)
        self.window._set_grab_add_at_top(True)
        self.window._set_grab_auto_confirm(True)
        self.window._set_grab_autostart(True)
        self.assertTrue(self.window._settings.value("grab_add_at_top", type=bool))
        self.assertTrue(self.window._settings.value("grab_auto_confirm", type=bool))
        self.assertTrue(self.window._settings.value("grab_autostart", type=bool))
        self.window.add_grab_urls([URLS[0]])
        self.window.add_grab_urls([URLS[1]])
        self.assertEqual(self.window.grab_model.urls(), [URLS[1], URLS[0]])

    def test_auto_confirm_moves_grabber_rows_after_successful_extract(self):
        started = []
        self.window._run = lambda worker, merge=False: started.append(worker)
        self.window.grab_auto_confirm = True
        self.window.grab_autostart = True
        self.window.add_grab_urls(URLS)
        self.window._collecting = True
        self.window._worker = type("W", (), {
            "mode": "collect", "request_stop": lambda self: None,
        })()
        self.window._on_finished("")
        self.assertTrue(self.window._pending_auto_confirm)
        self.window._thread = None
        self.window._apply_pending_auto_confirm()
        self.assertEqual(self.window.model.urls(), URLS)
        self.assertEqual(self.window.grab_model.rowCount(), 0)
        self.assertTrue(started)
        self.window._worker = None

    def test_auto_confirm_skips_cancelled_extract(self):
        self.window.grab_auto_confirm = True
        self.window.add_grab_urls(URLS)
        self.window._collecting = True
        self.window._grab_aborted = True
        self.window._worker = type("W", (), {
            "mode": "collect", "request_stop": lambda self: None,
        })()
        self.window._on_finished("Cancelled.")
        self.assertFalse(self.window._pending_auto_confirm)
        self.window._apply_pending_auto_confirm()
        self.assertEqual(self.window.grab_model.urls(), URLS)
        self.assertEqual(self.window.model.rowCount(), 0)
        self.window._worker = None

    def test_download_gear_and_settings_expose_speed_controls(self):
        self.window.tabs.setCurrentIndex(0)
        menu = self.window._build_options_menu()
        labels = [a.text() for a in menu.actions() if a.text()]
        self.assertIn("Package or Link Properties", labels)
        self.assertIn("Overview Panel visible", labels)
        spins = menu.findChildren(QSpinBox)
        self.assertEqual(len(spins), 2)
        self.assertEqual({box.maximum() for box in spins}, {16, 32})
        self.assertTrue(menu.findChildren(QLineEdit))
        dialog = SettingsDialog(self.window._settings, self.window)
        self.assertEqual(dialog.workers.minimum(), 1)
        self.assertEqual(dialog.workers.maximum(), 16)
        self.assertEqual(dialog.fragments.maximum(), 32)
        dialog.workers.setValue(5)
        dialog.fragments.setValue(12)
        dialog.speed_limit_on.setChecked(True)
        dialog.speed_limit.setText("50K")
        self.assertTrue(hasattr(dialog, "close_to_tray"))
        self.assertFalse(dialog.close_to_tray.isChecked())
        dialog.close_to_tray.setChecked(True)
        dialog.accept()
        self.assertTrue(self.window._settings.value("close_to_tray", True, bool))
        self.assertEqual(int(self.window._settings.value("workers")), 5)
        self.assertEqual(int(self.window._settings.value("fragments")), 12)
        self.assertEqual(self.window._speed()["limit_rate"], "50K")
        self.assertEqual(self.window._speed()["media_kinds"], {"video", "music", "image"})

    def test_job_worker_accepts_media_kinds_and_source_folders(self):
        folders = {"https://www.facebook.com/reel/1": "Hello caption"}
        worker = JobWorker(
            "download", "jireel", urls=["https://www.facebook.com/reel/1"],
            media_kinds={"video", "image"}, source_folders=folders,
        )
        self.assertEqual(worker.media_kinds, {"video", "image"})
        self.assertEqual(worker.source_folders, folders)

    def test_grabber_gear_lists_extract_options(self):
        self.window.tabs.setCurrentIndex(1)
        menu = self.window._build_options_menu()
        labels = [a.text() for a in menu.actions() if a.text()]
        for name in (
            "Add at top", "Auto confirm", "Autostart Download",
            "Overview Panel visible", "Sidebar visible",
            "Customize this Bottom Panel", "Package or Link Properties",
        ):
            self.assertIn(name, labels)


if __name__ == "__main__":
    unittest.main()
