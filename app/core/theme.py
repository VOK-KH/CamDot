"""Stylesheets and palettes for the two UI themes."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

# The app ships dark; the toggle and Settings only override it.
DEFAULT_DARK = True
DEFAULT_PRIMARY = "#1877f2"
ICON_ON_DARK = "#eef2f7"
ICON_ON_LIGHT = "#1c1e21"
# Active tab, menu, and row selection use this alpha (0–255), not a solid fill.
SELECTION_ALPHA = 56
THEME_STYLES = (("Dark", True), ("Light", False))
_active_primary = DEFAULT_PRIMARY

# Widgets the style paints itself (progress bars, scrollbars, menus) read the
# palette rather than the stylesheet, so the dark theme needs both.
_DARK_PALETTE = {
    QPalette.ColorRole.Window: "#0f1419",
    QPalette.ColorRole.WindowText: "#e7ecf3",
    QPalette.ColorRole.Base: "#121821",
    QPalette.ColorRole.AlternateBase: "#151d28",
    QPalette.ColorRole.Text: "#dbe3ec",
    QPalette.ColorRole.Button: "#1a2230",
    QPalette.ColorRole.ButtonText: "#e7ecf3",
    QPalette.ColorRole.ToolTipBase: "#1a2230",
    QPalette.ColorRole.ToolTipText: "#e7ecf3",
    QPalette.ColorRole.Highlight: "#1877f2",
    QPalette.ColorRole.HighlightedText: "#ffffff",
}


def normalize_hex(value, fallback=DEFAULT_PRIMARY):
    """Return `#rrggbb`, or `fallback` when the text is not a color."""
    text = str(value or "").strip()
    if text and not text.startswith("#"):
        text = f"#{text}"
    color = QColor(text)
    if not color.isValid():
        color = QColor(fallback)
    return color.name(QColor.NameFormat.HexRgb)


def set_primary(value=None):
    """Remember the accent used by stylesheets, icons, and status paints."""
    global _active_primary
    _active_primary = normalize_hex(value or _active_primary)
    return _active_primary


def primary_color():
    return _active_primary


def accent_rgba(hex_color=None, alpha=SELECTION_ALPHA):
    """CSS `rgba()` for a translucent accent wash."""
    color = QColor(hex_color or primary_color())
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {int(alpha)})"


def accent_wash(alpha=SELECTION_ALPHA):
    """Accent color at selection opacity, for painters that bypass the stylesheet."""
    color = QColor(primary_color())
    color.setAlpha(int(alpha))
    return color


def icon_fg(dark):
    """Stroke color for icons sitting on the window chrome."""
    return ICON_ON_DARK if dark else ICON_ON_LIGHT


def color_scheme(dark):
    """Qt color scheme for the theme.

    Windows draws the native title bar from this, not from the stylesheet, so
    without it the frame keeps following the system theme.
    """
    return Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light


def palette(dark, base=None, primary=None):
    """Return the palette for the theme; `base` is the style's default palette."""
    result = QPalette(base) if base is not None else QPalette()
    accent = QColor(set_primary(primary) if primary is not None else primary_color())
    if dark:
        for role, color in _DARK_PALETTE.items():
            result.setColor(role, QColor(color))
        result.setColor(
            QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6b7785")
        )
        result.setColor(
            QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#6b7785")
        )
    wash = QColor(accent)
    wash.setAlpha(SELECTION_ALPHA)
    result.setColor(QPalette.ColorRole.Highlight, wash)
    result.setColor(
        QPalette.ColorRole.HighlightedText,
        QColor("#e7ecf3" if dark else "#1c1e21"),
    )
    return result

LIGHT = """
QWidget#root { background: #f2f3f5; color: #1c1e21; }
QLabel { color: #1c1e21; font-size: 12px; }

QLineEdit, QComboBox, QSpinBox {
    background: #ffffff;
    border: 1px solid #c4c8ce;
    border-radius: 3px;
    padding: 3px 6px;
    color: #1c1e21;
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #1877f2; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #1c1e21;
    selection-background-color: __ACCENT_WASH__;
    selection-color: #1c1e21;
    border: 1px solid #c4c8ce;
    outline: 0;
}

QToolButton {
    background: #ffffff;
    border: 1px solid #c4c8ce;
    border-radius: 3px;
    padding: 2px 6px;
    min-width: 20px;
    color: #1c1e21;
}
QToolButton:hover { background: #e9ebee; }
QToolButton:checked { background: #d8e4f5; border-color: #1877f2; }

QTableView {
    background: #ffffff;
    alternate-background-color: #fafbfc;
    gridline-color: #dcdfe3;
    border: 1px solid #c4c8ce;
    color: #1c1e21;
    selection-background-color: __ACCENT_WASH__;
    selection-color: #1c1e21;
}
QTreeView {
    selection-background-color: __ACCENT_WASH__;
    selection-color: #1c1e21;
}
QTreeView::item:selected, QTableView::item:selected {
    background-color: __ACCENT_WASH__;
    color: #1c1e21;
}
QTableView::indicator { width: 14px; height: 14px; }
QHeaderView::section {
    background: #e9ebee;
    color: #3a3d42;
    border: 0;
    border-right: 1px solid #dcdfe3;
    border-bottom: 1px solid #c4c8ce;
    padding: 4px 6px;
    font-weight: 600;
}
QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #c4c8ce;
    color: #3a3d42;
}
QLabel#grabberHint { color: #4b4f56; font-size: 12px; }
QWidget#emptyTable { background: transparent; }
QLabel#emptyTableHint { color: #6b7078; font-size: 13px; }

QFrame#grabberPanel { background: #ffffff; border: 1px solid #b9bec6; border-radius: 4px; }
QWidget#grabberHead { background: #dfe4ea; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QLabel#grabberTitle { color: #3a3d42; font-size: 11px; font-weight: 700; }
QFrame#grabberPanel QLabel#grabberName { color: #4b4f56; font-size: 11px; }
QFrame#grabberPanel QLabel#grabberValue { color: #1c1e21; font-size: 11px; font-weight: 600; }
QToolButton#grabberHeadBtn { background: transparent; border: 0; padding: 1px 2px; min-width: 14px; }
QToolButton#grabberHeadBtn:hover { background: #c6ccd4; }
QPushButton#grabberAbort { background: #e9ebee; border: 1px solid #c4c8ce; border-radius: 3px; padding: 3px 10px; }
QPushButton#grabberAbort:hover { background: #dfe4ea; }
QPushButton#grabberAbort:disabled { color: #9aa0a6; background: #f2f3f5; }

QFrame#extractLoader { background: rgba(242, 243, 245, 180); }
QFrame#extractLoaderCard {
    background: #ffffff;
    border: 1px solid #c4c8ce;
    border-radius: 8px;
}
QLabel#extractLoaderTitle { color: #1c1e21; font-size: 14px; font-weight: 700; }
QLabel#extractLoaderDetail { color: #4b4f56; font-size: 12px; }
QLabel#extractLoaderCount { color: #1877f2; font-size: 12px; font-weight: 600; }
QPushButton#extractLoaderAbort {
    background: #e9ebee;
    border: 1px solid #c4c8ce;
    border-radius: 3px;
    padding: 4px 12px;
    color: #1c1e21;
}
QPushButton#extractLoaderAbort:hover { background: #dfe4ea; }

QFrame#viewsPanel { background: #eef2f7; border-left: 1px solid #dcdfe3; }
QLabel#viewsTitle { color: #3a3d42; font-size: 11px; font-weight: 700; }
QCheckBox#viewsKind { color: #1c1e21; font-size: 12px; spacing: 6px; }
QFrame#viewsDivider { background: #c4c8ce; border: 0; max-height: 1px; }
QListWidget#viewsHostList {
    background: #ffffff;
    border: 1px solid #c4c8ce;
    color: #1c1e21;
    font-size: 11px;
    alternate-background-color: #fafbfc;
}

QWidget#overviewPanel { background: #eef2f7; border: 0; border-top: 1px solid #dcdfe3; }
QLabel#overviewTitle { color: #3a3d42; font-size: 11px; font-weight: 700; }
QWidget#overviewPanel QLabel#overviewName { color: #6b7078; font-size: 11px; }
QWidget#overviewPanel QLabel#overviewValue { color: #1c1e21; font-size: 11px; font-weight: 600; }
QWidget#propertiesPanel { background: #eef2f7; border: 0; border-top: 1px solid #dcdfe3; }
QLabel#propertiesTitle { color: #3a3d42; font-size: 11px; font-weight: 700; }
QWidget#propertiesPanel QLineEdit { min-height: 18px; padding: 1px 5px; font-size: 11px; }
QToolButton#overviewClose {
    background: transparent;
    border: 0;
    border-radius: 2px;
    padding: 1px 3px;
    min-width: 14px;
}
QToolButton#overviewClose:hover { background: #d4d7dc; }

QWidget#actionBar { background: #e9ebee; border-top: 1px solid #dcdfe3; }
QWidget#actionBar QLabel { color: #4b4f56; }
QWidget#actionBar QFrame#toolSep { color: #c4c8ce; max-width: 8px; }
QWidget#actionBar QToolButton {
    background: transparent;
    border: 0;
    border-radius: 3px;
    padding: 4px 6px;
    min-width: 26px;
    min-height: 24px;
}
QWidget#actionBar QToolButton:hover { background: #d4d7dc; }
QWidget#actionBar QToolButton:checked { background: #cfe0fb; }
QWidget#actionBar QToolButton:!enabled { color: #9aa0a6; }
QWidget#actionBar QComboBox { background: #ffffff; }
QLineEdit#savePathEdit { background: #ffffff; min-width: 140px; }

QSplitter#mainSplit::handle, QSplitter#workSplit::handle {
    background: #dcdfe3;
}
QSplitter#mainSplit::handle:horizontal, QSplitter#workSplit::handle:horizontal {
    width: 6px;
}
QSplitter#mainSplit::handle:vertical, QSplitter#workSplit::handle:vertical {
    height: 6px;
}
QLabel#jobCounter { color: #3a3d42; font-weight: 600; }

QWidget#toolBar {
    background: #e9ebee;
    border-bottom: 1px solid #dcdfe3;
}
QWidget#toolBar QToolButton { background: transparent; border: 0; border-radius: 3px; }
QWidget#toolBar QToolButton:hover { background: #d4d7dc; }
QWidget#toolBar QToolButton:checked { background: #cfe0fb; }
QWidget#toolBar QToolButton:disabled { background: transparent; }
QWidget#toolBar QFrame#toolSep { color: #c4c8ce; max-width: 8px; }

QStatusBar#statusStrip { background: #e9ebee; border-top: 1px solid #dcdfe3; }
QStatusBar#statusStrip::item { border: 0; }
QStatusBar#statusStrip QLabel { color: #4b4f56; font-size: 11px; }

QMenuBar {
    background: #e9ebee;
    color: #1c1e21;
    border-bottom: 1px solid #dcdfe3;
    padding: 1px 2px;
}
QWidget#winControls QToolButton {
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 3px 12px;
}
QWidget#winControls QToolButton:hover { background: #d4d7dc; }
QWidget#winControls QToolButton#winClose:hover { background: #e81123; }
QMenuBar::item { padding: 4px 9px; background: transparent; border-radius: 3px; }
QMenuBar::item:selected, QMenuBar::item:pressed {
    background: __ACCENT_WASH__;
    color: #1c1e21;
}

QMenu {
    background: #ffffff;
    color: #1c1e21;
    border: 1px solid #c4c8ce;
    padding: 4px;
}
QMenu::item { padding: 5px 16px 5px 12px; }
QMenu::item:selected { background: __ACCENT_WASH__; color: #1c1e21; }
QMenu::separator { height: 1px; background: #dcdfe3; margin: 4px 8px; }

QTabBar::tab {
    background: transparent;
    color: #3a3d42;
    padding: 6px 12px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:hover:!selected { background: rgba(0, 0, 0, 18); }
QTabBar::tab:selected {
    background: __ACCENT_WASH__;
    color: #1c1e21;
    border-bottom: 2px solid #1877f2;
}
"""

DARK = """
QWidget#root { background: #0f1419; color: #e7ecf3; }
QLabel { color: #c5d0dc; font-size: 12px; }

QLineEdit, QComboBox, QSpinBox {
    background: #1a2230;
    border: 1px solid #2b3a4d;
    border-radius: 3px;
    padding: 3px 6px;
    color: #e7ecf3;
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #1877f2; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #1a2230;
    color: #e7ecf3;
    selection-background-color: __ACCENT_WASH__;
    selection-color: #e7ecf3;
    border: 1px solid #2b3a4d;
    outline: 0;
}

QToolButton {
    background: #1a2230;
    border: 1px solid #2b3a4d;
    border-radius: 3px;
    padding: 2px 6px;
    min-width: 20px;
    color: #e7ecf3;
}
QToolButton:hover { background: #243044; }
QToolButton:checked { background: #1f4f99; border-color: #1877f2; }

QTableView {
    background: #121821;
    alternate-background-color: #151d28;
    gridline-color: #26303d;
    border: 1px solid #26303d;
    color: #dbe3ec;
    selection-background-color: __ACCENT_WASH__;
    selection-color: #dbe3ec;
}
QTreeView {
    selection-background-color: __ACCENT_WASH__;
    selection-color: #dbe3ec;
}
QTreeView::item:selected, QTableView::item:selected {
    background-color: __ACCENT_WASH__;
    color: #dbe3ec;
}
QTableView::indicator { width: 14px; height: 14px; }
QHeaderView::section {
    background: #1a2230;
    color: #9fb0c3;
    border: 0;
    border-right: 1px solid #26303d;
    border-bottom: 1px solid #26303d;
    padding: 4px 6px;
    font-weight: 600;
}
QPlainTextEdit {
    background: #0b1016;
    border: 1px solid #26303d;
    color: #b8c4d4;
}
QLabel#grabberHint { color: #8c98a8; font-size: 12px; }
QWidget#emptyTable { background: transparent; }
QLabel#emptyTableHint { color: #8c98a8; font-size: 13px; }

QFrame#grabberPanel { background: #1a2230; border: 1px solid #34465e; border-radius: 4px; }
QWidget#grabberHead { background: #223046; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QLabel#grabberTitle { color: #e7ecf3; font-size: 11px; font-weight: 700; }
QFrame#grabberPanel QLabel#grabberName { color: #9fb0c3; font-size: 11px; }
QFrame#grabberPanel QLabel#grabberValue { color: #e7ecf3; font-size: 11px; font-weight: 600; }
QToolButton#grabberHeadBtn { background: transparent; border: 0; padding: 1px 2px; min-width: 14px; }
QToolButton#grabberHeadBtn:hover { background: #2f4062; }
QPushButton#grabberAbort { background: #243044; border: 1px solid #2b3a4d; border-radius: 3px; padding: 3px 10px; }
QPushButton#grabberAbort:hover { background: #2c3a52; }
QPushButton#grabberAbort:disabled { color: #6b7785; background: #1c242f; }

QFrame#extractLoader { background: rgba(11, 16, 22, 170); }
QFrame#extractLoaderCard {
    background: #1a2230;
    border: 1px solid #34465e;
    border-radius: 8px;
}
QLabel#extractLoaderTitle { color: #e7ecf3; font-size: 14px; font-weight: 700; }
QLabel#extractLoaderDetail { color: #9fb0c3; font-size: 12px; }
QLabel#extractLoaderCount { color: #7eb0ff; font-size: 12px; font-weight: 600; }
QPushButton#extractLoaderAbort {
    background: #243044;
    border: 1px solid #2b3a4d;
    border-radius: 3px;
    padding: 4px 12px;
    color: #e7ecf3;
}
QPushButton#extractLoaderAbort:hover { background: #2c3a52; }

QFrame#viewsPanel { background: #151d28; border-left: 1px solid #26303d; }
QLabel#viewsTitle { color: #c5d0dc; font-size: 11px; font-weight: 700; }
QCheckBox#viewsKind { color: #e7ecf3; font-size: 12px; spacing: 6px; }
QFrame#viewsDivider { background: #34465e; border: 0; max-height: 1px; }
QListWidget#viewsHostList {
    background: #121821;
    border: 1px solid #26303d;
    color: #e7ecf3;
    font-size: 11px;
    alternate-background-color: #151d28;
}

QWidget#overviewPanel { background: #151d28; border: 0; border-top: 1px solid #26303d; }
QLabel#overviewTitle { color: #c5d0dc; font-size: 11px; font-weight: 700; }
QWidget#overviewPanel QLabel#overviewName { color: #8c98a8; font-size: 11px; }
QWidget#overviewPanel QLabel#overviewValue { color: #e7ecf3; font-size: 11px; font-weight: 600; }
QWidget#propertiesPanel { background: #151d28; border: 0; border-top: 1px solid #26303d; }
QLabel#propertiesTitle { color: #c5d0dc; font-size: 11px; font-weight: 700; }
QWidget#propertiesPanel QLineEdit { min-height: 18px; padding: 1px 5px; font-size: 11px; }
QToolButton#overviewClose {
    background: transparent;
    border: 0;
    border-radius: 2px;
    padding: 1px 3px;
    min-width: 14px;
}
QToolButton#overviewClose:hover { background: #243044; }

QWidget#actionBar { background: #141a23; border-top: 1px solid #26303d; }
QWidget#actionBar QLabel { color: #9fb0c3; }
QWidget#actionBar QFrame#toolSep { color: #2b3a4d; max-width: 8px; }
QWidget#actionBar QToolButton {
    background: transparent;
    border: 0;
    border-radius: 3px;
    padding: 4px 6px;
    min-width: 26px;
    min-height: 24px;
}
QWidget#actionBar QToolButton:hover { background: #243044; }
QWidget#actionBar QToolButton:checked { background: #1f4f99; }
QWidget#actionBar QToolButton:!enabled { color: #6b7785; }
QWidget#actionBar QComboBox { background: #1a2230; }
QLineEdit#savePathEdit { background: #1a2230; min-width: 140px; }

QSplitter#mainSplit::handle, QSplitter#workSplit::handle {
    background: #26303d;
}
QSplitter#mainSplit::handle:horizontal, QSplitter#workSplit::handle:horizontal {
    width: 6px;
}
QSplitter#mainSplit::handle:vertical, QSplitter#workSplit::handle:vertical {
    height: 6px;
}
QLabel#jobCounter { color: #e7ecf3; font-weight: 600; }

QWidget#toolBar {
    background: #141a23;
    border-bottom: 1px solid #26303d;
}
QWidget#toolBar QToolButton { background: transparent; border: 0; border-radius: 3px; }
QWidget#toolBar QToolButton:hover { background: #243044; }
QWidget#toolBar QToolButton:checked { background: #1f4f99; }
QWidget#toolBar QToolButton:disabled { background: transparent; }
QWidget#toolBar QFrame#toolSep { color: #2b3a4d; max-width: 8px; }

QStatusBar#statusStrip { background: #141a23; border-top: 1px solid #26303d; }
QStatusBar#statusStrip::item { border: 0; }
QStatusBar#statusStrip QLabel { color: #9fb0c3; font-size: 11px; }

QMenuBar {
    background: #141a23;
    color: #c5d0dc;
    border-bottom: 1px solid #26303d;
    padding: 1px 2px;
}
QWidget#winControls QToolButton {
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 3px 12px;
}
QWidget#winControls QToolButton:hover { background: #243044; }
QWidget#winControls QToolButton#winClose:hover { background: #e81123; }
QMenuBar::item { padding: 4px 9px; background: transparent; border-radius: 3px; }
QMenuBar::item:selected, QMenuBar::item:pressed {
    background: __ACCENT_WASH__;
    color: #e7ecf3;
}

QMenu {
    background: #1a2230;
    color: #e7ecf3;
    border: 1px solid #2b3a4d;
    padding: 4px;
}
QMenu::item { padding: 5px 16px 5px 12px; }
QMenu::item:selected { background: __ACCENT_WASH__; color: #e7ecf3; }
QMenu::separator { height: 1px; background: #26303d; margin: 4px 8px; }

QTabBar::tab {
    background: transparent;
    color: #9fb0c3;
    padding: 6px 12px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:hover:!selected { background: rgba(255, 255, 255, 16); }
QTabBar::tab:selected {
    background: __ACCENT_WASH__;
    color: #e7ecf3;
    border-bottom: 2px solid #1877f2;
}
"""

# Labelled action-bar buttons share the default gray pill; icon-only tools stay compact.
ACTION_BAR_DARK = """
QWidget#actionBar QPushButton, QWidget#headerBar QPushButton,
QWidget#actionBar QToolButton[pill="true"] {
    background: #2a2f3a;
    color: #eef2f7;
    border: 1px solid #3a4250;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 500;
}
QWidget#actionBar QPushButton:hover, QWidget#headerBar QPushButton:hover,
QWidget#actionBar QToolButton[pill="true"]:hover { background: #363d4b; }
QWidget#actionBar QPushButton:disabled, QWidget#headerBar QPushButton:disabled,
QWidget#actionBar QToolButton[pill="true"]:disabled { color: #6b7280; background: #20242c; }
QWidget#actionBar QToolButton[pill="true"]::menu-button {
    width: 12px;
    border: none;
    border-left: 1px solid #3a4250;
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
}
QWidget#actionBar QToolButton[pill="true"]::menu-button:hover { background: #404859; }
"""

ACTION_BAR_LIGHT = """
QWidget#actionBar QPushButton, QWidget#headerBar QPushButton,
QWidget#actionBar QToolButton[pill="true"] {
    background: #ffffff;
    color: #1c1e21;
    border: 1px solid #c4c8ce;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 500;
}
QWidget#actionBar QPushButton:hover, QWidget#headerBar QPushButton:hover,
QWidget#actionBar QToolButton[pill="true"]:hover { background: #e9ebee; }
QWidget#actionBar QPushButton:disabled, QWidget#headerBar QPushButton:disabled,
QWidget#actionBar QToolButton[pill="true"]:disabled { color: #9aa0a6; background: #f2f3f5; }
QWidget#actionBar QToolButton[pill="true"]::menu-button {
    width: 12px;
    border: none;
    border-left: 1px solid #c4c8ce;
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
}
QWidget#actionBar QToolButton[pill="true"]::menu-button:hover { background: #dfe4ea; }
"""


def stylesheet(dark, primary=None):
    """Window chrome plus action-bar pills; `#1877f2` is swapped for `primary`."""
    accent = set_primary(primary)
    css = (DARK if dark else LIGHT) + (ACTION_BAR_DARK if dark else ACTION_BAR_LIGHT)
    return (
        css.replace("__ACCENT_WASH__", accent_rgba(accent))
        .replace("#1877f2", accent)
    )
