"""Tests for UI font registration."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core import fonts


class FontSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pick_ui_family_prefers_segoe(self):
        with patch.object(fonts.QFontDatabase, "families", return_value=["Segoe UI", "Arial"]):
            self.assertEqual(fonts.pick_ui_family(), "Segoe UI")

    def test_register_fonts_loads_when_missing(self):
        with patch.object(fonts.QFontDatabase, "families", return_value=[]):
            with patch.object(fonts, "_register_font_files", return_value=True) as register:
                with patch.object(fonts.QFontDatabase, "families", side_effect=[[], ["Arial"]]):
                    family = fonts.register_fonts()
        register.assert_called_once()
        self.assertEqual(family, "Arial")

    def test_ui_font_follows_the_system_font(self):
        system = fonts.QFontDatabase.systemFont(fonts.QFontDatabase.SystemFont.GeneralFont)
        font = fonts.ui_font()
        self.assertEqual(font.family(), system.family())
        self.assertEqual(font.hintingPreference(), system.hintingPreference())

    def test_custom_families_are_placed_ahead_of_the_system_font(self):
        system = fonts.QFontDatabase.systemFont(fonts.QFontDatabase.SystemFont.GeneralFont)
        font = fonts.ui_font("Khmer OS, Noto Sans Khmer")
        families = list(font.families())
        self.assertEqual(families[:2], ["Khmer OS", "Noto Sans Khmer"])
        self.assertIn("Leelawadee UI", families)
        if system.family() and system.family() not in ("Khmer OS", "Noto Sans Khmer"):
            self.assertLess(
                families.index("Noto Sans Khmer"), families.index(system.family()),
            )
        if system.family() and system.family() != "Leelawadee UI":
            self.assertLess(families.index(system.family()), families.index("Leelawadee UI"))


if __name__ == "__main__":
    unittest.main()
