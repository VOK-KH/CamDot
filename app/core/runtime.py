"""Cross-platform runtime setup for yt-dlp and FFmpeg."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

APP_NAME = "CamDot"
APP_FOLDER_NAME = APP_NAME
APP_SLUG = "camdot"
SETTINGS_ORG = APP_NAME
GITHUB_REPO = "VOK-KH/CamDot"
UPDATE_INTERVAL = 24 * 60 * 60
UPDATE_PACKAGES = ("yt-dlp[default,curl-cffi]", "imageio-ffmpeg")


def yt_dlp_command_prefix():
    """Argv prefix for spawning yt-dlp (works in dev and PyInstaller builds)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]

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
    path = os.path.join(base, APP_SLUG)
    legacy = os.path.join(base, "reels-downloader")
    if not os.path.exists(path) and os.path.isdir(legacy):
        try:
            os.rename(legacy, path)
        except OSError:
            return legacy
    return path


def chrome_profile_dir():
    """Persistent Chrome user-data-dir for Selenium logins."""
    return os.path.join(state_dir(), "chrome-profile")


def collect_csv_path(channel):
    """Collection CSV for a channel (not next to downloaded videos)."""
    return os.path.join(state_dir(), "collect", f"{channel}.csv")


def channel_state_dir(channel):
    """Per-channel folder for list.json and .downloaded.txt."""
    return os.path.join(state_dir(), "channels", channel)


def util_cache_dir():
    """Favicon and other small caches under AppData."""
    return os.path.join(state_dir(), "cache")


def _is_empty_dir(path):
    if not os.path.isdir(path):
        return True
    try:
        return not os.listdir(path)
    except OSError:
        return False


def _merge_tree(src, dest):
    """Move items from src into dest; keep dest files when names collide."""
    os.makedirs(dest, exist_ok=True)
    try:
        names = os.listdir(src)
    except OSError:
        return
    for name in names:
        from_path = os.path.join(src, name)
        to_path = os.path.join(dest, name)
        try:
            if os.path.isdir(from_path):
                if not os.path.exists(to_path):
                    shutil.move(from_path, to_path)
                elif os.path.isdir(to_path):
                    _merge_tree(from_path, to_path)
            elif not os.path.exists(to_path):
                shutil.move(from_path, to_path)
        except OSError:
            continue
    try:
        os.rmdir(src)
    except OSError:
        pass


def _relocate(src, dest):
    """Move src to dest if dest is missing or empty; otherwise merge."""
    if not os.path.exists(src):
        return
    if os.path.abspath(src) == os.path.abspath(dest):
        return
    if not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        try:
            shutil.move(src, dest)
        except OSError:
            pass
        return
    if os.path.isdir(src) and os.path.isdir(dest):
        if _is_empty_dir(dest):
            try:
                os.rmdir(dest)
                shutil.move(src, dest)
            except OSError:
                _merge_tree(src, dest)
        else:
            _merge_tree(src, dest)


def sweep_download_folder(output_root):
    """Move leftover util files out of the user download folder into AppData.

    Videos and .part files stay under output_root. Safe to call on every startup.
    """
    if not output_root or not os.path.isdir(output_root):
        return
    root = os.path.abspath(output_root)
    _relocate(os.path.join(root, ".chrome-profile"), chrome_profile_dir())
    _relocate(os.path.join(root, ".cache"), util_cache_dir())
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        src = os.path.join(root, name)
        if os.path.isfile(src) and name.lower().endswith(".csv"):
            dest = collect_csv_path(os.path.splitext(name)[0])
            if not os.path.exists(dest):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try:
                    shutil.move(src, dest)
                except OSError:
                    pass
            continue
        if not os.path.isdir(src) or name.startswith("."):
            continue
        dest_dir = channel_state_dir(name)
        for fname in ("list.json", ".downloaded.txt"):
            leftover = os.path.join(src, fname)
            dest = os.path.join(dest_dir, fname)
            if os.path.isfile(leftover) and not os.path.exists(dest):
                os.makedirs(dest_dir, exist_ok=True)
                try:
                    shutil.move(leftover, dest)
                except OSError:
                    pass


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


def update_runtime(*, force=False, source="auto", state_path=None, runner=subprocess.run):
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
    try:
        from app.core.telegram_report import device_id_from_state, report_tools_use

        report_tools_use(
            device_id=device_id_from_state(),
            source=source,
            ok=code == 0,
            versions=runtime_versions(),
        )
    except Exception:
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
    ok = update_runtime(force=True, source="setup")
    versions = runtime_versions()
    print(f"Engine: {versions['yt_dlp'] or 'missing'}")
    print(f"FFmpeg: {versions['ffmpeg'] or 'missing'}")
    print("Runtime tools are ready." if ok and all(versions.values()) else "Runtime setup incomplete.")
    return 0 if ok and all(versions.values()) else 1
