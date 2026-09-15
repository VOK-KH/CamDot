"""Tests for UI font registration."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core import fonts


class FontSetup(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
