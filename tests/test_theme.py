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

    def test_active_chrome_uses_a_translucent_accent(self):
        css = theme.stylesheet(True, "#22aa44")
        wash = "rgba(34, 170, 68, 56)"
        self.assertIn(wash, css)
        self.assertIn(f"QMenuBar::item:pressed {{\n    background: {wash};", css)
        self.assertIn(f"QMenu::item:selected {{ background: {wash};", css)
        self.assertIn(f"QTabBar::tab:selected {{\n    background: {wash};", css)
        self.assertIn(f"QTreeView {{\n    selection-background-color: {wash};", css)
        self.assertNotIn("QMenuBar::item:pressed { background: #22aa44;", css)
        wash_color = theme.accent_wash()
        self.assertEqual(wash_color.alpha(), theme.SELECTION_ALPHA)
        self.assertLess(wash_color.alpha(), 255)
