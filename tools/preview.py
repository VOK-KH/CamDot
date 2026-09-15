"""Render the window to a PNG so the layout can be reviewed without a display.

Usage: uv run python tools/preview.py [out.png] [--dark]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.gui import MainWindow
from app.core import theme

STATUSES = ["done"] * 14 + ["downloading"] * 3 + ["queued"] * 8 + ["failed"]


def main():
    out = next((a for a in sys.argv[1:] if not a.startswith("-")), "preview.png")
    dark = "--dark" in sys.argv

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet(dark))

    # A throwaway settings file, so a preview never picks up or clobbers real ones.
    settings = QSettings(
        os.path.join(tempfile.mkdtemp(), "preview.ini"), QSettings.Format.IniFormat
    )
    window = MainWindow(dark=dark, settings=settings)
    window.resize(1180, 680)
    window.source_edit.setText("https://www.facebook.com/jireel/reels")

    urls = [f"https://www.facebook.com/reel/10015{i:07d}" for i in range(len(STATUSES))]
    window.set_urls(urls)
    for i, (url, status) in enumerate(zip(urls, STATUSES)):
        if status == "downloading":
            window._on_progress(url, {
                "status": "downloading", "percent": 42.0,
                "total": 8_400_000, "speed": 1_250_000, "eta": 5,
                "description": "Demo caption for the reel",
                "title": "Name on Reels",
            })
        elif status != "queued":
            window._on_progress(url, {
                "status": status,
                "description": "Demo caption for the reel",
                "title": "Name on Reels",
            })
        if i < 4:
            window.model.set_checked_rows([i], True)
    window.table.selectRow(15)
    window._toggle_properties(True)
    window._append_log("Downloading 26 reel(s) into output\\jireel")
    window._append_log("4 reel(s) at a time, 8 fragment(s) per reel.")
    window.log.setVisible(True)

    window.show()
    # The status bar fills its GPU section from a worker thread; give that
    # signal a few event loop turns so the strip is complete in the shot.
    for _ in range(20):
        app.processEvents()
        if window.stats["gpu"].text() != "—":
            break
        time.sleep(0.05)
    app.processEvents()
    window.grab().save(out)
    print(os.path.abspath(out))


if __name__ == "__main__":
    main()
