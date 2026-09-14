"""Application settings dialog."""
import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.download import DEFAULT_FRAGMENTS, DEFAULT_WORKERS, OUTPUT_TEMPLATE, resolve_filename_template
from app.core.runtime import default_output_root, resolve_output_root
from app.core.theme import DEFAULT_DARK

COOKIE_BROWSERS = (
    ("None", ""),
    ("Chrome", "chrome"),
    ("Edge", "edge"),
    ("Firefox", "firefox"),
    ("Brave", "brave"),
)


class PathField(QWidget):
    def __init__(self, mode="file", parent=None):
        super().__init__(parent)
        self.mode = mode
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.edit = QLineEdit()
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
        self.resize(570, 330)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        general = QWidget()
        form = QFormLayout(general)
        self.channel = QLineEdit()
        self.channel.setPlaceholderText("auto from the source URL")
        self.output = PathField("directory")
        self.output.setText(default_output_root())
        self.filename = QLineEdit()
        self.filename.setPlaceholderText(OUTPUT_TEMPLATE)
        self.filename.setToolTip(
            "yt-dlp file name inside the download folder. "
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
        self.auto_update = QCheckBox("Automatically update yt-dlp and FFmpeg daily")
        form.addRow("Output name", self.channel)
        form.addRow("Download folder", self.output)
        form.addRow("File name", self.filename)
        form.addRow("Parallel downloads", self.workers)
        form.addRow("Fragments per item", self.fragments)
        form.addRow("", self.dark)
        form.addRow("", self.show_log)
        form.addRow("", self.link_grabber)
        form.addRow("", self.auto_update)
        tabs.addTab(general, "General")

        tools = QWidget()
        tools_form = QFormLayout(tools)
        self.chrome = PathField()
        self.chrome.edit.setPlaceholderText("Facebook reels collection only")
        self.ffmpeg = PathField()
        self.ffmpeg.edit.setPlaceholderText("automatic from PATH")
        self.cookies_browser = QComboBox()
        for label, value in COOKIE_BROWSERS:
            self.cookies_browser.addItem(label, value)
        self.cookies_profile = QLineEdit()
        self.cookies_profile.setPlaceholderText("optional browser profile name")
        tools_form.addRow("Chrome executable", self.chrome)
        tools_form.addRow("FFmpeg executable/folder", self.ffmpeg)
        tools_form.addRow("Cookies from browser", self.cookies_browser)
        tools_form.addRow("Browser profile", self.cookies_profile)
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
        self.filename.setText(get("filename_template", OUTPUT_TEMPLATE, str))
        self.workers.setValue(int(get("workers", DEFAULT_WORKERS)))
        self.fragments.setValue(int(get("fragments", DEFAULT_FRAGMENTS)))
        self.dark.setChecked(get("dark", DEFAULT_DARK, bool))
        self.show_log.setChecked(get("log_visible", False, bool))
        self.link_grabber.setChecked(get("link_grabber", True, bool))
        self.auto_update.setChecked(get("auto_update", True, bool))
        self.chrome.setText(get("chrome_binary", "", str))
        self.ffmpeg.setText(get("ffmpeg_location", "", str))
        browser = get("cookies_browser", "", str)
        index = self.cookies_browser.findData(browser)
        self.cookies_browser.setCurrentIndex(max(index, 0))
        self.cookies_profile.setText(get("cookies_profile", "", str))

    def restore_defaults(self):
        self.channel.clear()
        self.output.setText(default_output_root())
        self.filename.setText(OUTPUT_TEMPLATE)
        self.workers.setValue(DEFAULT_WORKERS)
        self.fragments.setValue(DEFAULT_FRAGMENTS)
        self.dark.setChecked(DEFAULT_DARK)
        self.show_log.setChecked(False)
        self.link_grabber.setChecked(True)
        self.auto_update.setChecked(True)
        self.chrome.setText("")
        self.ffmpeg.setText("")
        self.cookies_browser.setCurrentIndex(0)
        self.cookies_profile.clear()

    def accept(self):
        output = self.output.text() or default_output_root()
        self.settings.setValue("channel", self.channel.text().strip())
        self.settings.setValue("output_root", os.path.normpath(output))
        self.settings.setValue(
            "filename_template", resolve_filename_template(self.filename.text())
        )
        self.settings.setValue("workers", self.workers.value())
        self.settings.setValue("fragments", self.fragments.value())
        self.settings.setValue("dark", self.dark.isChecked())
        self.settings.setValue("log_visible", self.show_log.isChecked())
        self.settings.setValue("link_grabber", self.link_grabber.isChecked())
        self.settings.setValue("auto_update", self.auto_update.isChecked())
        self.settings.setValue("chrome_binary", self.chrome.text())
        self.settings.setValue("ffmpeg_location", self.ffmpeg.text())
        self.settings.setValue("cookies_browser", self.cookies_browser.currentData() or "")
        self.settings.setValue("cookies_profile", self.cookies_profile.text().strip())
        super().accept()
