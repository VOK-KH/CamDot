"""PyInstaller entry point for CamDot Windows builds."""
import sys


def _run_yt_dlp():
    sys.argv = ["yt-dlp", *sys.argv[2:]]
    import yt_dlp

    raise SystemExit(yt_dlp.main())


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--yt-dlp":
        _run_yt_dlp()
    from app.gui.window import main

    raise SystemExit(main())
