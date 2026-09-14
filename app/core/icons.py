"""Load the artwork: recolored SVG icons plus the bundled PNG sets."""
import os
from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_CORE_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_CORE_DIR)
# Running from a checkout the images sit next to the package; an installed wheel
# carries a copy inside it (see [tool.hatch.build] in pyproject.toml).
_CANDIDATES = (
    os.path.join(os.path.dirname(_APP_DIR), "images"),
    os.path.join(_APP_DIR, "images"),
)


def images_dir():
    for path in _CANDIDATES:
        if os.path.isdir(path):
            return path
    return _CANDIDATES[0]


def icon_dir():
    return os.path.join(images_dir(), "icons")


@lru_cache(maxsize=64)
def _source(name):
    with open(os.path.join(icon_dir(), f"{name}.svg"), encoding="utf-8") as f:
        return f.read()


@lru_cache(maxsize=256)
def icon(name, color="#1c1e21", size=18):
    """Return the named icon stroked in `color`, rendered crisply at 2x."""
    svg = _source(name).replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


@lru_cache(maxsize=64)
def art(folder, name, height=32):
    """Return the PNG images/<folder>/<name>.png scaled to `height`."""
    pixmap = QPixmap(os.path.join(images_dir(), folder, f"{name}.png"))
    if pixmap.isNull() or pixmap.height() == height:
        return pixmap
    return pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


def art_icon(folder, name, height=32):
    return QIcon(art(folder, name, height))


def png(name, height=16):
    """Return the bundled PNG images/<name>.png scaled to `height`."""
    return art("", name, height)


def png_icon(name, height=16):
    return QIcon(png(name, height))
