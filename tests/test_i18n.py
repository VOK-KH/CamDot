"""UI language follows the system locale, with an explicit override."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.core.i18n import apply_language, tr
from app.gui.dialogs.settings import SettingsDialog


class Language(unittest.TestCase):
    def tearDown(self):
        apply_language("en")

    def test_english_keeps_the_source_text(self):
        apply_language("en")
        self.assertEqual(tr("Download"), "Download")
        self.assertEqual(tr("&File"), "&File")

    def test_khmer_translates_known_text(self):
        apply_language("km")
        self.assertEqual(tr("Download"), "ទាញយក")
        self.assertEqual(tr("&File"), "ឯកសារ")
        self.assertEqual(tr("Not a real label"), "Not a real label")

    def test_system_language_follows_the_os_locale(self):
        with patch("app.core.i18n.QLocale") as locale:
            locale.system.return_value.name.return_value = "km_KH"
            self.assertEqual(apply_language("system"), "km")
            self.assertEqual(tr("Status"), "ស្ថានភាព")
        with patch("app.core.i18n.QLocale") as locale:
            locale.system.return_value.name.return_value = "en_US"
            self.assertEqual(apply_language("system"), "en")
            self.assertEqual(tr("Download"), "Download")


class SettingsLanguage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        apply_language("en")

    def test_appearance_saves_language_and_extra_fonts(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = QSettings(
            os.path.join(folder.name, "test.ini"), QSettings.Format.IniFormat
        )
        dialog = SettingsDialog(settings)
        dialog.ui_language.setCurrentIndex(dialog.ui_language.findData("km"))
        dialog.ui_fonts.setText(" Khmer OS, Noto Sans Khmer ")
        dialog.accept()
        self.assertEqual(settings.value("ui_language"), "km")
        self.assertEqual(settings.value("ui_fonts"), "Khmer OS, Noto Sans Khmer")
