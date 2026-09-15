"""Check GitHub releases for newer CamDot builds."""
import json
import platform
import re
import sys
import urllib.error
import urllib.request

from app import __version__
from app.core.runtime import APP_NAME, APP_SLUG, GITHUB_REPO

_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


def arch_label():
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine


def platform_label():
    if sys.platform == "win32":
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    return "Linux"


def parse_version(text):
    match = _VERSION_RE.match((text or "").strip())
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest, current):
    return parse_version(latest) > parse_version(current)


def _request_json(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": APP_SLUG,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def asset_for_platform(release):
    needle = f"{platform_label()}-{arch_label()}"
    assets = release.get("assets", [])
    for asset in assets:
        name = asset.get("name", "")
        if needle in name and "-Setup" in name:
            return name, asset.get("browser_download_url", "")
    for asset in assets:
        name = asset.get("name", "")
        if needle in name:
            return name, asset.get("browser_download_url", "")
    return "", ""


def check_for_update(timeout=15):
    """Return update info dict or None when already current / unavailable."""
    try:
        release = _request_json(_API, timeout=timeout)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None
    tag = (release.get("tag_name") or "").lstrip("v")
    if not tag or not is_newer(tag, __version__):
        return None
    asset_name, download_url = asset_for_platform(release)
    return {
        "current": __version__,
        "latest": tag,
        "tag": release.get("tag_name", tag),
        "notes": (release.get("body") or "").strip(),
        "page_url": release.get("html_url") or _PAGE,
        "asset_name": asset_name,
        "download_url": download_url,
    }


def format_update_message(info):
    lines = [
        f"A newer {APP_NAME} release is available.",
        f"Installed: {info['current']}",
        f"Latest: {info['latest']}",
    ]
    if info.get("asset_name"):
        lines.append(f"Download: {info['asset_name']}")
    notes = (info.get("notes") or "").strip()
    if notes:
        lines.append("")
        lines.append(notes[:800])
    return "\n".join(lines)


def format_update_prompt(info):
    """Short summary for the update confirmation dialog."""
    lines = [
        f"A new version of {APP_NAME} is available.",
        "",
        f"Installed: {info['current']}",
        f"Latest: {info['latest']}",
    ]
    if info.get("asset_name"):
        lines.append(f"Package: {info['asset_name']}")
    notes = (info.get("notes") or "").strip()
    if notes:
        lines.append("")
        lines.append(notes[:500])
    return "\n".join(lines)
