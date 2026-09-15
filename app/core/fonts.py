"""Register UI fonts for offscreen Qt and frozen builds."""
import os
import sys

from PySide6.QtGui import QFont, QFontDatabase

_PREFERRED = (
    "Segoe UI",
    "Arial",
    "Helvetica Neue",
    "Helvetica",
    "DejaVu Sans",
    "Liberation Sans",
    "Sans Serif",
)

_FONT_CANDIDATES = {
    "win32": (
        lambda: os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
        ("segoeui.ttf", "segoeuib.ttf", "arial.ttf", "calibri.ttf"),
    ),
    "darwin": (
        lambda: "/System/Library/Fonts/Supplemental",
        ("Arial.ttf", "Helvetica.ttc"),
    ),
    "linux": (
        lambda: "/usr/share/fonts/truetype/dejavu",
        ("DejaVuSans.ttf",),
    ),
}


def _bundled_font_dir():
    core_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(core_dir)
    root = os.path.dirname(app_dir)
    for path in (
        os.path.join(root, "images", "fonts"),
        os.path.join(app_dir, "images", "fonts"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "images", "fonts"),
    ):
        if path and os.path.isdir(path):
            return path
    return ""


def _register_font_files():
    registered = False
    platform_key = sys.platform if sys.platform in _FONT_CANDIDATES else "linux"
    font_dir_fn, names = _FONT_CANDIDATES[platform_key]
    font_dir = font_dir_fn()
    for name in names:
        path = os.path.join(font_dir, name)
        if os.path.isfile(path) and QFontDatabase.addApplicationFont(path) >= 0:
            registered = True
            break
    bundled = _bundled_font_dir()
    if bundled:
        for name in os.listdir(bundled):
            if name.lower().endswith((".ttf", ".otf", ".ttc")):
                if QFontDatabase.addApplicationFont(os.path.join(bundled, name)) >= 0:
                    registered = True
                    break
    return registered


def pick_ui_family():
    families = set(QFontDatabase.families())
    for name in _PREFERRED:
        if name in families:
            return name
    if families:
        return sorted(families)[0]
    return "Sans Serif"


def register_fonts():
    """Load system/bundled fonts. Requires QGuiApplication (e.g. QApplication)."""
    families = set(QFontDatabase.families())
    if not any(name in families for name in _PREFERRED[:4]):
        _register_font_files()
    return pick_ui_family()


def setup_app_font(app):
    """Apply the UI font to the whole application."""
    family = register_fonts()
    font = QFont(family, 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    return font
