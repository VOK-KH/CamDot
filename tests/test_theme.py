"""Theme helpers: primary accent swap and light/dark chrome."""
import unittest

from app.core import theme


class ThemeColors(unittest.TestCase):
    def test_normalize_hex_accepts_short_and_bare_values(self):
        self.assertEqual(theme.normalize_hex("#CC3366"), "#cc3366")
        self.assertEqual(theme.normalize_hex("1877f2"), "#1877f2")
        self.assertEqual(theme.normalize_hex("not-a-color"), theme.DEFAULT_PRIMARY)

    def test_stylesheet_replaces_the_primary_accent(self):
        css = theme.stylesheet(True, "#cc3366")
        self.assertIn("#cc3366", css)
        self.assertNotIn("#1877f2", css)
        self.assertEqual(theme.primary_color(), "#cc3366")

    def test_light_action_bar_uses_dark_label_color(self):
        css = theme.stylesheet(False, theme.DEFAULT_PRIMARY)
        self.assertIn("color: #1c1e21", css)
        self.assertIn('QToolButton[pill="true"]', css)

    def test_icon_fg_follows_the_theme_style(self):
        self.assertEqual(theme.icon_fg(True), theme.ICON_ON_DARK)
        self.assertEqual(theme.icon_fg(False), theme.ICON_ON_LIGHT)
