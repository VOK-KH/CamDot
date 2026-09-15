"""Build images/icons/camdot.ico from the app SVG (used by PyInstaller and Inno Setup)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "images" / "icons" / "app.svg"
OUT = ROOT / "images" / "icons" / "camdot.ico"
COLOR = "#1877f2"


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        raise SystemExit(f"Invalid SVG: {SVG}")

    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = []
    for size in sizes:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), QColor(COLOR))
        painter.end()
        images.append(QPixmap.fromImage(image))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not images[-1].save(str(OUT), "ICO"):
        raise SystemExit(f"Could not write {OUT}")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
