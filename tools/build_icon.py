"""Build images/icons/camdot.ico from images/icons/app.png (PyInstaller and Inno Setup)."""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PNG = ROOT / "images" / "icons" / "app.png"
OUT = ROOT / "images" / "icons" / "camdot.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _png_bytes(image):
    from PySide6.QtCore import QBuffer, QIODevice

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise SystemExit("Could not encode an icon frame")
    data = bytes(buffer.data())
    buffer.close()
    return data


def _write_ico(path, frames):
    """Write a PNG-compressed ICO. Width/height 0 means 256."""
    header = struct.pack("<HHH", 0, 1, len(frames))
    entries = bytearray()
    blobs = []
    offset = 6 + 16 * len(frames)
    for image, blob in frames:
        side = image.width()
        blobs.append(blob)
        entries += struct.pack(
            "<BBBBHHII",
            0 if side >= 256 else side,
            0 if side >= 256 else side,
            0,
            0,
            1,
            32,
            len(blob),
            offset,
        )
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(sys.argv)
    source = QPixmap(str(PNG))
    if source.isNull():
        raise SystemExit(f"Missing artwork: {PNG}")

    frames = []
    for size in SIZES:
        image = source.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).toImage().convertToFormat(QImage.Format.Format_ARGB32)
        frames.append((image, _png_bytes(image)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    _write_ico(OUT, frames)
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
