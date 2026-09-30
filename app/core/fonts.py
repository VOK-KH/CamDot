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
# Segoe UI has no Khmer. These system fonts shape Khmer clusters instead of
# stacking the vowel signs on one advance.
_SCRIPT_FALLBACKS = (
    "Leelawadee UI",
    "Khmer UI",
    "Khmer OS",
    "Khmer OS Battambang",
    "DaunPenh",
    "Noto Sans Khmer",
    "Noto Sans Khmer UI",
)

_FONT_CANDIDATES = {
    "win32": (
        lambda: os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
        ("segoeui.ttf", "segoeuib.ttf", "arial.ttf", "calibri.ttf"),
    ),
    "darwin": (
        lambda: "/System/Library/Fonts",
        ("Helvetica.ttc", "Supplemental/Arial.ttf", "Supplemental/Helvetica.ttc"),
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
    preferred = _PREFERRED
    if sys.platform == "darwin":
        preferred = ("Helvetica Neue", "Helvetica", *preferred)
    for name in preferred:
        if name in families:
            return name
    for name in sorted(families):
        if not name.startswith("."):
            return name
    return "Helvetica" if sys.platform == "darwin" else "Sans Serif"


def register_fonts():
    """Load system/bundled fonts. Requires QGuiApplication (e.g. QApplication)."""
    families = set(QFontDatabase.families())
    if not any(name in families for name in _PREFERRED[:4]):
        _register_font_files()
    return pick_ui_family()


def parse_families(text):
    """Comma-separated family names, in the order the user typed them."""
    if text is None:
        return []
    if isinstance(text, (list, tuple)):
        parts = text
    else:
        parts = str(text).replace(";", ",").split(",")
    seen = []
    for part in parts:
        name = str(part).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def ui_font(extra=()):
    """The Windows UI font. Extra families, when set, are used before it.

    With no extras the system font is left as Windows created it, so font
    linking still covers Khmer and other scripts. A custom list replaces that
    chain, so the system family and the script fonts are appended after it.
    """
    register_fonts()
    font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
    extras = parse_families(extra)
    if not extras:
        return font
    families = []
    for name in extras + [font.family()] + list(_SCRIPT_FALLBACKS):
        if name and name not in families:
            families.append(name)
    font.setFamilies(families)
    return font


def setup_app_font(app, extra=()):
    """Apply the UI font to the whole application."""
    font = ui_font(extra)
    app.setFont(font)
    return font
