"""Download and apply CamDot app updates on Windows."""
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from app.core.runtime import APP_NAME, state_dir


def download_path(asset_name):
    folder = os.path.join(state_dir(), "updates")
    os.makedirs(folder, exist_ok=True)
    safe = asset_name.replace("/", "_").replace("\\", "_") or "CamDot-Setup.exe"
    return os.path.join(folder, safe)


def download_file(url, dest, *, timeout=300, block_size=256 * 1024):
    """Download url to dest. Returns dest on success."""
    request = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
    temp = dest + ".part"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        with open(temp, "wb") as handle:
            while True:
                chunk = response.read(block_size)
                if not chunk:
                    break
                handle.write(chunk)
                read += len(chunk)
        if total and read != total:
            raise OSError(f"Incomplete download ({read} of {total} bytes)")
    os.replace(temp, dest)
    return dest


def is_installed_build():
    """True for a packaged CamDot.exe, not `uv run camdot`."""
    return bool(getattr(sys, "frozen", False))


def download_update(info):
    """Download the GitHub asset for this platform into AppData/updates."""
    url = info.get("download_url") or ""
    asset = info.get("asset_name") or "CamDot-Setup.exe"
    if not url:
        raise ValueError("No download URL in update info")
    dest = download_path(asset)
    return download_file(url, dest)


def launch_installer(path):
    """Start the downloaded installer so it can replace this app."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return False
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [path, "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
            creationflags=flags,
        )
        return True
    os.startfile(path)  # noqa: S606
    return True


def apply_update(info):
    """Download the platform asset and run the Windows installer."""
    dest = download_update(info)
    if not launch_installer(dest):
        os.startfile(dest)  # noqa: S606
    return dest
