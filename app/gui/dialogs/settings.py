"""Application settings dialog."""
import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core import telegram_notify
from app.core.download import DEFAULT_FRAGMENTS, DEFAULT_WORKERS, OUTPUT_TEMPLATE, resolve_filename_template
from app.core.runtime import default_output_root, resolve_output_root
from app.core.theme import DEFAULT_DARK, DEFAULT_PRIMARY, THEME_STYLES, normalize_hex

COOKIE_BROWSERS = (
    ("None", ""),
    ("Chrome", "chrome"),
    ("Edge", "edge"),
    ("Firefox", "firefox"),
    ("Brave", "brave"),
)

TIKTOK_AGE_CHOICES = (
    ("Any time", ""),
    ("Last 24 hours", "1"),
    ("Last 7 days", "7"),
    ("Last 30 days", "30"),
    ("Last 3 months", "90"),
    ("Last 6 months", "180"),
)


class PathField(QWidget):
    def __init__(self, mode="file", parent=None):
        super().__init__(parent)
        self.mode = mode
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.edit = QLineEdit()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        button = QPushButton("Browse…")
        button.clicked.connect(self.browse)
        row.addWidget(self.edit, 1)
        row.addWidget(button)

    def browse(self):
        if self.mode == "directory":
            path = QFileDialog.getExistingDirectory(self, "Choose folder", self.edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Choose executable", self.edit.text())
        if path:
            self.edit.setText(path)

    def text(self):
        return self.edit.text().strip()

    def setText(self, text):
        self.edit.setText(text)


class ColorField(QWidget):
    """A swatch that opens the system color picker."""

    def __init__(self, color=DEFAULT_PRIMARY, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.button = QPushButton()
        self.button.setFixedSize(92, 24)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._pick)
        self.label = QLabel()
        row.addWidget(self.button, 0)
        row.addWidget(self.label, 1)
        self.set_hex(color)

    def _pick(self):
        chosen = QColorDialog.getColor(QColor(self.hex()), self, "Primary color")
        if chosen.isValid():
            self.set_hex(chosen.name())

    def hex(self):
        return self._hex

    def set_hex(self, color):
        self._hex = normalize_hex(color, DEFAULT_PRIMARY)
        self.button.setStyleSheet(
            f"background: {self._hex}; border: 1px solid #6b7280; border-radius: 3px;"
        )
        self.label.setText(self._hex)


class SettingsDialog(QDialog):
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_general_tab()
        self._build_download_tab()
        self._build_grabber_tab()
        self._build_notifications_tab()
        self._build_appearance_tab()
        self._build_tools_tab()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self.restore_defaults
        )
        layout.addWidget(buttons)
        self.load()

    def _add_tab(self, title):
        page = QWidget()
        form = QFormLayout(page)
        _compact_form(form)
        self.tabs.addTab(page, title)
        return form

    def _build_general_tab(self):
        form = self._add_tab("General")
        self.channel = QLineEdit()
        self.channel.setPlaceholderText("auto from the source URL")
        self.show_log = QCheckBox("Show log panel at startup")
        self.close_to_tray = QCheckBox("Keep running in the system tray")
        self.close_to_tray.setToolTip(
            "Close and minimise hide the window; clipboard grab and downloads continue."
        )
        self.check_app_updates = QCheckBox("Check GitHub for app updates (startup and every few hours)")
        self.check_app_updates.setToolTip(
            "Calls the GitHub Releases API. If a newer tag exists, CamDot asks before downloading."
        )
        self.auto_update = QCheckBox("Automatically update download tools daily (dev installs only)")
        self.auto_update.setToolTip(
            "Installed CamDot builds bundle their download tools; this applies when running from source."
        )
        self.telegram_reports = QCheckBox("Send anonymous crash and usage reports")
        self.telegram_reports.setToolTip(
            "Includes app version, platform, device id, and feedback you submit. "
            "Never includes download URLs unless you send feedback."
        )
        form.addRow("Output name", self.channel)
        form.addRow("", self.show_log)
        form.addRow("", self.close_to_tray)
        form.addRow("", self.check_app_updates)
        form.addRow("", self.auto_update)
        form.addRow("", self.telegram_reports)

    def _build_download_tab(self):
        form = self._add_tab("Download")
        self.output = PathField("directory")
        self.output.setText(default_output_root())
        self.output.setToolTip(
            "Parent folder for finished media.\n"
            "Each output name becomes a subfolder here, for example:\n"
            f"{default_output_root()}\\MyChannel\\"
        )
        self.group_downloads = QCheckBox("Put each item in its own named folder")
        self.group_downloads.setToolTip(
            "Off by default. When on, CamDot adds a caption folder under the save path.\n"
            "Prefer Set download directory on the table for a shared folder."
        )
        self.filename = QLineEdit()
        self.filename.setPlaceholderText(OUTPUT_TEMPLATE)
        self.filename.setToolTip(
            "File name inside the download folder. "
            "Default uses the caption or title, then the id."
        )
        self.workers = QSpinBox()
        self.workers.setRange(1, 16)
        self.fragments = QSpinBox()
        self.fragments.setRange(1, 32)
        self.speed_limit_on = QCheckBox("Speed limit")
        self.speed_limit = QLineEdit()
        self.speed_limit.setPlaceholderText("50K")
        self.speed_limit.setToolTip("Optional speed cap, e.g. 50K or 2M")
        speed_row = QWidget()
        speed_layout = QHBoxLayout(speed_row)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        speed_layout.setSpacing(8)
        speed_layout.addWidget(self.speed_limit_on)
        speed_layout.addWidget(self.speed_limit, 1)
        form.addRow("Download folder", self.output)
        form.addRow("", self.group_downloads)
        form.addRow("File name", self.filename)
        form.addRow("Parallel downloads", self.workers)
        form.addRow("Fragments per item", self.fragments)
        form.addRow("Download speed", speed_row)

    def _build_grabber_tab(self):
        form = self._add_tab("Grabber")
        self.link_grabber = QCheckBox(
            "Watch clipboard and collect supported links in background"
        )
        self.grab_add_at_top = QCheckBox("Add Grabber rows at the top")
        self.grab_auto_confirm = QCheckBox("Auto confirm Extract into Download")
        self.grab_autostart = QCheckBox("Autostart download after add")
        self.tiktok_age = QComboBox()
        for label, value in TIKTOK_AGE_CHOICES:
            self.tiktok_age.addItem(label, value)
        form.addRow("", self.link_grabber)
        form.addRow("", self.grab_add_at_top)
        form.addRow("", self.grab_auto_confirm)
        form.addRow("", self.grab_autostart)
        form.addRow("TikTok newer than", self.tiktok_age)

    def _build_notifications_tab(self):
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(10, 8, 10, 8)
        col.setSpacing(8)
        self.notify_enabled = QCheckBox("Enable Telegram download notifications")
        self.notify_enabled.setToolTip(
            "When a download job finishes, CamDot messages every approved Telegram account."
        )
        self.notify_token = QLineEdit()
        self.notify_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.notify_token.setPlaceholderText("Bot token from @BotFather")
        self.notify_token.setToolTip(
            "Paste the token for your bot. Users send /start to that bot, then you approve them here."
        )
        token_row = QWidget()
        token_layout = QHBoxLayout(token_row)
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.setSpacing(6)
        token_layout.addWidget(self.notify_token, 1)
        self.notify_refresh = QPushButton("Check /start")
        self.notify_refresh.setToolTip("Fetch new Telegram users who messaged the bot with /start")
        self.notify_refresh.clicked.connect(self._refresh_notify_accounts)
        token_layout.addWidget(self.notify_refresh)
        hint = QLabel(
            "Open the bot in Telegram, tap Start, then Check /start. "
            "Approve an account to receive a message when downloads finish."
        )
        hint.setWordWrap(True)
        self.notify_accounts = QTableWidget(0, 3)
        self.notify_accounts.setHorizontalHeaderLabels(("Account", "Username", "Status"))
        self.notify_accounts.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.notify_accounts.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.notify_accounts.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.notify_accounts.verticalHeader().setVisible(False)
        header = self.notify_accounts.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        actions = QWidget()
        action_row = QHBoxLayout(actions)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        self.notify_approve = QPushButton("Approve")
        self.notify_reject = QPushButton("Reject")
        self.notify_approve.clicked.connect(
            lambda: self._set_selected_notify_status(telegram_notify.STATUS_APPROVED))
        self.notify_reject.clicked.connect(
            lambda: self._set_selected_notify_status(telegram_notify.STATUS_REJECTED))
        action_row.addWidget(self.notify_approve)
        action_row.addWidget(self.notify_reject)
        action_row.addStretch(1)
        self.notify_status = QLabel("")
        self.notify_status.setWordWrap(True)
        col.addWidget(self.notify_enabled)
        col.addWidget(QLabel("Bot token"))
        col.addWidget(token_row)
        col.addWidget(hint)
        col.addWidget(self.notify_accounts, 1)
        col.addWidget(actions)
        col.addWidget(self.notify_status)
        self.notify_enabled.toggled.connect(self._sync_notify_widgets)
        self.tabs.addTab(page, "Notifications")
        self._notify_rows = []
        self._notify_offset = 0

    def _sync_notify_widgets(self):
        on = self.notify_enabled.isChecked()
        for widget in (
            self.notify_token, self.notify_refresh, self.notify_accounts,
            self.notify_approve, self.notify_reject,
        ):
            widget.setEnabled(on)

    def _fill_notify_table(self):
        self.notify_accounts.setRowCount(len(self._notify_rows))
        for row, account in enumerate(self._notify_rows):
            values = (
                telegram_notify.account_label(account),
                account.get("username") or "—",
                telegram_notify.STATUS_LABELS.get(account.get("status"), "Pending"),
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, account["chat_id"])
                self.notify_accounts.setItem(row, column, item)

    def _selected_notify_chat_id(self):
        row = self.notify_accounts.currentRow()
        if row < 0:
            return ""
        item = self.notify_accounts.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ""

    def _refresh_notify_accounts(self):
        token = self.notify_token.text().strip()
        if not token:
            self.notify_status.setText("Enter a bot token first.")
            return
        try:
            self._notify_rows, self._notify_offset, pending = telegram_notify.poll_starts(
                token, self._notify_offset, self._notify_rows, reply=True,
            )
        except (RuntimeError, OSError) as exc:
            self.notify_status.setText(str(exc))
            return
        self._fill_notify_table()
        if pending:
            self.notify_status.setText(
                f"{len(pending)} new account(s) waiting for approval."
            )
        else:
            self.notify_status.setText("No new /start messages.")

    def _set_selected_notify_status(self, status):
        chat_id = self._selected_notify_chat_id()
        if not chat_id:
            self.notify_status.setText("Select an account first.")
            return
        self._notify_rows, account = telegram_notify.set_status(
            self._notify_rows, chat_id, status)
        self._fill_notify_table()
        token = self.notify_token.text().strip()
        if token and account:
            telegram_notify.send_status_reply(token, account)
        label = telegram_notify.STATUS_LABELS.get(status, status)
        self.notify_status.setText(
            f"{telegram_notify.account_label(account)} is {label.lower()}."
        )

    def _build_appearance_tab(self):
        look = self._add_tab("Appearance")
        self.theme_style = QComboBox()
        for label, dark in THEME_STYLES:
            self.theme_style.addItem(label, dark)
        self.theme_style.setToolTip("Dark or light window chrome, tables, and toolbars.")
        self.primary = ColorField()
        self.primary.setToolTip("Accent for tabs, focus rings, checked tools, and the app icon.")
        look.addRow("Theme style", self.theme_style)
        look.addRow("Primary color", self.primary)

    def _build_tools_tab(self):
        tools_form = self._add_tab("Tools")
        self.chrome = PathField()
        self.chrome.edit.setPlaceholderText("Facebook reels collection only")
        self.ffmpeg = PathField()
        self.ffmpeg.edit.setPlaceholderText("automatic from PATH")
        self.cookies_browser = QComboBox()
        for label, value in COOKIE_BROWSERS:
            self.cookies_browser.addItem(label, value)
        self.cookies_profile = QLineEdit()
        self.cookies_profile.setPlaceholderText("optional browser profile name")
        self.cookies_curl = QPlainTextEdit()
        self.cookies_curl.setPlaceholderText(
            "Kuaishou / Douyin: paste a Cookie header or a copied cURL command"
        )
        self.cookies_curl.setMinimumHeight(72)
        self.cookies_curl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        self.cookies_browser.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed,
        )
        self.cookies_profile.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed,
        )
        tools_form.addRow("Chrome executable", self.chrome)
        tools_form.addRow("FFmpeg executable/folder", self.ffmpeg)
        tools_form.addRow("Cookies from browser", self.cookies_browser)
        tools_form.addRow("Browser profile", self.cookies_profile)
        tools_form.addRow("Cookie / cURL", self.cookies_curl)

    def load(self):
        get = self.settings.value
        self.channel.setText(get("channel", "", str))
        self.output.setText(resolve_output_root(get("output_root", "", str)))
        self.group_downloads.setChecked(get("group_downloads", False, bool))
        self.filename.setText(get("filename_template", OUTPUT_TEMPLATE, str))
        self.workers.setValue(int(get("workers", DEFAULT_WORKERS)))
        self.fragments.setValue(int(get("fragments", DEFAULT_FRAGMENTS)))
        dark = get("dark", DEFAULT_DARK, bool)
        index = self.theme_style.findData(dark)
        self.theme_style.setCurrentIndex(max(index, 0))
        self.primary.set_hex(get("theme_primary", DEFAULT_PRIMARY, str))
        self.show_log.setChecked(get("log_visible", False, bool))
        self.link_grabber.setChecked(get("link_grabber", True, bool))
        self.close_to_tray.setChecked(get("close_to_tray", True, bool))
        self.check_app_updates.setChecked(get("check_app_updates", True, bool))
        self.auto_update.setChecked(get("auto_update", True, bool))
        self.telegram_reports.setChecked(get("telegram_reports", True, bool))
        self.speed_limit_on.setChecked(get("speed_limit_on", False, bool))
        self.speed_limit.setText(get("speed_limit", "", str))
        self.grab_add_at_top.setChecked(get("grab_add_at_top", False, bool))
        self.grab_auto_confirm.setChecked(get("grab_auto_confirm", False, bool))
        self.grab_autostart.setChecked(get("grab_autostart", False, bool))
        self.chrome.setText(get("chrome_binary", "", str))
        self.ffmpeg.setText(get("ffmpeg_location", "", str))
        browser = get("cookies_browser", "", str)
        index = self.cookies_browser.findData(browser)
        self.cookies_browser.setCurrentIndex(max(index, 0))
        self.cookies_profile.setText(get("cookies_profile", "", str))
        self.cookies_curl.setPlainText(get("cookies_curl", "", str))
        age = get("tiktok_age_days", "", str)
        age_index = self.tiktok_age.findData(age)
        self.tiktok_age.setCurrentIndex(max(age_index, 0))
        self.notify_enabled.setChecked(telegram_notify.enabled(self.settings))
        self.notify_token.setText(telegram_notify.bot_token(self.settings))
        self._notify_rows = telegram_notify.load_accounts(self.settings)
        self._notify_offset = telegram_notify.update_offset(self.settings)
        self._fill_notify_table()
        self._sync_notify_widgets()

    def restore_defaults(self):
        self.channel.clear()
        self.output.setText(default_output_root())
        self.group_downloads.setChecked(False)
        self.filename.setText(OUTPUT_TEMPLATE)
        self.workers.setValue(DEFAULT_WORKERS)
        self.fragments.setValue(DEFAULT_FRAGMENTS)
        self.theme_style.setCurrentIndex(max(self.theme_style.findData(DEFAULT_DARK), 0))
        self.primary.set_hex(DEFAULT_PRIMARY)
        self.show_log.setChecked(False)
        self.link_grabber.setChecked(True)
        self.close_to_tray.setChecked(True)
        self.check_app_updates.setChecked(True)
        self.auto_update.setChecked(True)
        self.telegram_reports.setChecked(True)
        self.speed_limit_on.setChecked(False)
        self.speed_limit.clear()
        self.grab_add_at_top.setChecked(False)
        self.grab_auto_confirm.setChecked(False)
        self.grab_autostart.setChecked(False)
        self.chrome.setText("")
        self.ffmpeg.setText("")
        self.cookies_browser.setCurrentIndex(0)
        self.cookies_profile.clear()
        self.cookies_curl.clear()
        self.tiktok_age.setCurrentIndex(0)
        self.notify_enabled.setChecked(False)
        self.notify_token.clear()
        self._notify_rows = []
        self._notify_offset = 0
        self._fill_notify_table()
        self.notify_status.clear()
        self._sync_notify_widgets()

    def accept(self):
        output = self.output.text() or default_output_root()
        self.settings.setValue("channel", self.channel.text().strip())
        self.settings.setValue("output_root", os.path.normpath(output))
        self.settings.setValue("group_downloads", self.group_downloads.isChecked())
        self.settings.setValue(
            "filename_template", resolve_filename_template(self.filename.text())
        )
        self.settings.setValue("workers", self.workers.value())
        self.settings.setValue("fragments", self.fragments.value())
        self.settings.setValue("dark", bool(self.theme_style.currentData()))
        self.settings.setValue("theme_primary", self.primary.hex())
        self.settings.setValue("log_visible", self.show_log.isChecked())
        self.settings.setValue("link_grabber", self.link_grabber.isChecked())
        self.settings.setValue("close_to_tray", self.close_to_tray.isChecked())
        self.settings.setValue("check_app_updates", self.check_app_updates.isChecked())
        self.settings.setValue("auto_update", self.auto_update.isChecked())
        self.settings.setValue("telegram_reports", self.telegram_reports.isChecked())
        self.settings.setValue("speed_limit_on", self.speed_limit_on.isChecked())
        self.settings.setValue("speed_limit", self.speed_limit.text().strip())
        self.settings.setValue("grab_add_at_top", self.grab_add_at_top.isChecked())
        self.settings.setValue("grab_auto_confirm", self.grab_auto_confirm.isChecked())
        self.settings.setValue("grab_autostart", self.grab_autostart.isChecked())
        self.settings.setValue("chrome_binary", self.chrome.text())
        self.settings.setValue("ffmpeg_location", self.ffmpeg.text())
        self.settings.setValue("cookies_browser", self.cookies_browser.currentData() or "")
        self.settings.setValue("cookies_profile", self.cookies_profile.text().strip())
        self.settings.setValue("cookies_curl", self.cookies_curl.toPlainText().strip())
        self.settings.setValue("tiktok_age_days", self.tiktok_age.currentData() or "")
        telegram_notify.save_state(
            self.settings,
            self._notify_rows,
            offset=self._notify_offset,
            token=self.notify_token.text(),
            enabled_flag=self.notify_enabled.isChecked(),
        )
        super().accept()


def _compact_form(form):
    """Keep labels next to fields and extra space under the last row."""
    form.setContentsMargins(10, 8, 10, 8)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(6)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
