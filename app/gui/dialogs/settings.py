"""Application settings dialog."""
import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.download import DEFAULT_FRAGMENTS, DEFAULT_WORKERS, OUTPUT_TEMPLATE, resolve_filename_template
from app.core.runtime import default_output_root, resolve_output_root, state_dir
from app.core.theme import DEFAULT_DARK

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


class SettingsDialog(QDialog):
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        general = QWidget()
        form = QFormLayout(general)
        _compact_form(form)
        self.channel = QLineEdit()
        self.channel.setPlaceholderText("auto from the source URL")
        self.output = PathField("directory")
        self.output.setText(default_output_root())
        self.output.setToolTip(
            "Parent folder for finished media.\n"
            "Each output name becomes a subfolder here, for example:\n"
            f"{default_output_root()}\\MyChannel\\"
        )
        self.group_downloads = QCheckBox("Create a subfolder for each download")
        self.group_downloads.setToolTip(
            "When enabled, each item is saved in its own folder under the output name.\n"
            "When disabled, files are saved directly in the output name folder."
        )
        self.app_data = QLabel(state_dir())
        self.app_data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.app_data.setWordWrap(True)
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
        self.dark = QCheckBox("Use dark theme")
        self.show_log = QCheckBox("Show log panel at startup")
        self.link_grabber = QCheckBox(
            "Watch clipboard and collect supported links in background"
        )
        self.close_to_tray = QCheckBox("Keep running in the system tray")
        self.close_to_tray.setToolTip(
            "Close and minimise hide the window; clipboard grab and downloads continue."
        )
        self.auto_update = QCheckBox("Automatically update download tools daily")
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
        self.grab_add_at_top = QCheckBox("Add Grabber rows at the top")
        self.grab_auto_confirm = QCheckBox("Auto confirm Extract into Download")
        self.grab_autostart = QCheckBox("Autostart download after add")
        self.tiktok_age = QComboBox()
        for label, value in TIKTOK_AGE_CHOICES:
            self.tiktok_age.addItem(label, value)
        form.addRow("Output name", self.channel)
        form.addRow("Download folder", self.output)
        form.addRow("", self.group_downloads)
        form.addRow("App data folder", self.app_data)
        form.addRow("File name", self.filename)
        form.addRow("Parallel downloads", self.workers)
        form.addRow("Fragments per item", self.fragments)
        form.addRow("", self.dark)
        form.addRow("", self.show_log)
        form.addRow("", self.link_grabber)
        form.addRow("", self.close_to_tray)
        form.addRow("", self.auto_update)
        form.addRow("Download speed", speed_row)
        form.addRow("", self.grab_add_at_top)
        form.addRow("", self.grab_auto_confirm)
        form.addRow("", self.grab_autostart)
        form.addRow("TikTok newer than", self.tiktok_age)
        tabs.addTab(general, "General")

        tools = QWidget()
        tools_form = QFormLayout(tools)
        _compact_form(tools_form)
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
        tabs.addTab(tools, "Tools")

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

    def load(self):
        get = self.settings.value
        self.channel.setText(get("channel", "", str))
        self.output.setText(resolve_output_root(get("output_root", "", str)))
        self.group_downloads.setChecked(get("group_downloads", True, bool))
        self.app_data.setText(state_dir())
        self.filename.setText(get("filename_template", OUTPUT_TEMPLATE, str))
        self.workers.setValue(int(get("workers", DEFAULT_WORKERS)))
        self.fragments.setValue(int(get("fragments", DEFAULT_FRAGMENTS)))
        self.dark.setChecked(get("dark", DEFAULT_DARK, bool))
        self.show_log.setChecked(get("log_visible", False, bool))
        self.link_grabber.setChecked(get("link_grabber", True, bool))
        self.close_to_tray.setChecked(get("close_to_tray", True, bool))
        self.auto_update.setChecked(get("auto_update", True, bool))
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

    def restore_defaults(self):
        self.channel.clear()
        self.output.setText(default_output_root())
        self.group_downloads.setChecked(True)
        self.app_data.setText(state_dir())
        self.filename.setText(OUTPUT_TEMPLATE)
        self.workers.setValue(DEFAULT_WORKERS)
        self.fragments.setValue(DEFAULT_FRAGMENTS)
        self.dark.setChecked(DEFAULT_DARK)
        self.show_log.setChecked(False)
        self.link_grabber.setChecked(True)
        self.close_to_tray.setChecked(True)
        self.auto_update.setChecked(True)
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
        self.settings.setValue("dark", self.dark.isChecked())
        self.settings.setValue("log_visible", self.show_log.isChecked())
        self.settings.setValue("link_grabber", self.link_grabber.isChecked())
        self.settings.setValue("close_to_tray", self.close_to_tray.isChecked())
        self.settings.setValue("auto_update", self.auto_update.isChecked())
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
