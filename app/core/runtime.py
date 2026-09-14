"""Cross-platform runtime setup for yt-dlp and FFmpeg."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

APP_FOLDER_NAME = "Reels Downloader"
UPDATE_INTERVAL = 24 * 60 * 60
UPDATE_PACKAGES = ("yt-dlp[default,curl-cffi]", "imageio-ffmpeg")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_update_thread = None
_update_lock = threading.Lock()


def default_output_root():
    """Windows Downloads, macOS Documents, each with an app-name subfolder."""
    home = os.path.expanduser("~")
    parent = "Documents" if sys.platform == "darwin" else "Downloads"
    return os.path.join(home, parent, APP_FOLDER_NAME)


def resolve_output_root(configured=""):
    """Use a saved folder, or the platform default. Legacy relative `output` upgrades."""
    configured = os.path.normpath(configured.strip()) if configured else ""
    if not configured or configured == "output":
        return default_output_root()
    return configured


def resolve_ffmpeg(configured=""):
    """Return configured/PATH FFmpeg or imageio-ffmpeg's bundled executable."""
    configured = (configured or "").strip()
    if configured:
        return configured
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        executable = get_ffmpeg_exe()
        return executable if executable and os.path.isfile(executable) else ""
    except (ImportError, RuntimeError):
        return ""


def runtime_versions():
    """Small diagnostics payload used by tests and setup output."""
    try:
        import yt_dlp
        ytdlp = yt_dlp.version.__version__
    except (ImportError, AttributeError):
        ytdlp = ""
    ffmpeg = resolve_ffmpeg()
    return {"yt_dlp": ytdlp, "ffmpeg": ffmpeg}


def state_dir():
    """Per-user folder for small caches that are not downloads."""
    base = os.getenv("LOCALAPPDATA") if sys.platform == "win32" else None
    base = base or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "reels-downloader")


def _state_path():
    return os.path.join(state_dir(), "runtime-update.json")


def _last_attempt(path):
    try:
        with open(path, encoding="utf-8") as f:
            return float(json.load(f).get("attempted_at", 0))
    except (OSError, ValueError, TypeError):
        return 0


def _record_attempt(path, returncode):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump({"attempted_at": time.time(), "returncode": returncode}, f)
    os.replace(temp, path)


def update_runtime(*, force=False, state_path=None, runner=subprocess.run):
    """Update managed tools with uv. Returns True only after a successful run."""
    uv = shutil.which("uv")
    if not uv:
        return False
    state_path = state_path or _state_path()
    if not force and time.time() - _last_attempt(state_path) < UPDATE_INTERVAL:
        return True
    command = [
        uv, "pip", "install", "--upgrade", "--python", sys.executable,
        *UPDATE_PACKAGES,
    ]
    try:
        result = runner(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
            timeout=300,
            check=False,
        )
        code = result.returncode
    except (OSError, subprocess.SubprocessError):
        code = 1
    try:
        _record_attempt(state_path, code)
    except OSError:
        pass
    return code == 0


def schedule_auto_update(enabled=True):
    """Run the daily tool update in one background thread, never blocking UI."""
    global _update_thread
    if not enabled:
        return None
    with _update_lock:
        if _update_thread and _update_thread.is_alive():
            return _update_thread
        _update_thread = threading.Thread(
            target=update_runtime,
            name="runtime-auto-update",
            daemon=True,
        )
        _update_thread.start()
        return _update_thread


def setup_main():
    """Console setup command for explicit install/update diagnostics."""
    ok = update_runtime(force=True)
    versions = runtime_versions()
    print(f"yt-dlp: {versions['yt_dlp'] or 'missing'}")
    print(f"FFmpeg: {versions['ffmpeg'] or 'missing'}")
    print("Runtime tools are ready." if ok and all(versions.values()) else "Runtime setup incomplete.")
    return 0 if ok and all(versions.values()) else 1
