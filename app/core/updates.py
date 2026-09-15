"""Check GitHub releases for newer CamDot builds."""
import json
import os
import platform
import re
import sys
import time
import urllib.error
import urllib.request

from app import __version__
from app.core.runtime import APP_NAME, APP_SLUG, GITHUB_REPO

GITHUB_CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000
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
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": APP_SLUG,
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers["Cache-Control"] = "no-cache"
    headers["Pragma"] = "no-cache"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def asset_label(name):
    """Human platform label from a CamDot release asset filename."""
    lower = (name or "").lower()
    bits = []
    if "windows" in lower:
        bits.append("Windows")
    elif "macos" in lower or "darwin" in lower:
        bits.append("macOS")
    elif "linux" in lower:
        bits.append("Linux")
    if "arm64" in lower or "aarch64" in lower:
        bits.append("arm64")
    elif "x86_64" in lower or "amd64" in lower:
        bits.append("x86_64")
    if "setup" in lower or "installer" in lower:
        bits.append("Setup")
    elif lower.endswith(".dmg"):
        bits.append("DMG")
    elif ".tar" in lower:
        bits.append("tarball")
    elif lower.endswith(".exe"):
        bits.append("portable")
    return " ".join(bits) or (name or "Download")


def listed_assets(release):
    rows = []
    for asset in release.get("assets") or []:
        name = asset.get("name") or ""
        url = asset.get("browser_download_url") or ""
        if name and url:
            rows.append({"name": name, "url": url, "label": asset_label(name)})
    return rows


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


def parse_release(release, current=None):
    """Normalize a GitHub release payload for UI, Telegram, and installers."""
    tag_raw = (release.get("tag_name") or "").strip()
    tag = tag_raw.lstrip("v")
    asset_name, download_url = asset_for_platform(release)
    return {
        "current": current if current is not None else __version__,
        "latest": tag,
        "tag": tag_raw or (f"v{tag}" if tag else ""),
        "notes": (release.get("body") or "").strip(),
        "page_url": release.get("html_url") or _PAGE,
        "asset_name": asset_name,
        "download_url": download_url,
        "assets": listed_assets(release),
    }


def fetch_release(tag="", timeout=15):
    """Latest published release, or a specific tag when `tag` is set."""
    url = _API
    if tag:
        name = tag if str(tag).startswith("v") else f"v{tag}"
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{name}"
    return _request_json(url, timeout=timeout)


def check_for_update(timeout=15):
    """Return update info dict or None when already current / unavailable."""
    try:
        release = fetch_release(timeout=timeout)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None
    info = parse_release(release)
    if not info["latest"] or not is_newer(info["latest"], info["current"]):
        return None
    return info


def format_update_message(info):
    tag = info.get("tag") or info.get("latest") or ""
    lines = [
        f"A newer {APP_NAME} release is available.",
        f"Installed: {info.get('current', '')}",
        f"Tag: {tag}",
    ]
    assets = info.get("assets") or []
    if assets:
        lines.append("Downloads:")
        for asset in assets:
            lines.append(f"- {asset.get('label') or asset['name']}: {asset['url']}")
    elif info.get("download_url"):
        lines.append(f"Download: {info.get('asset_name') or ''} {info['download_url']}".strip())
    notes = (info.get("notes") or "").strip()
    if notes:
        lines.append("")
        lines.append(notes[:800])
    return "\n".join(lines)


def should_offer_update(info, settings):
    """Return False when the user skipped or snoozed this release."""
    latest = (info.get("latest") or "").strip()
    if not latest:
        return True
    if settings.value("skipped_update_version", "", str).strip() == latest:
        return False
    try:
        remind_after = float(settings.value("update_remind_after", 0) or 0)
    except (TypeError, ValueError):
        remind_after = 0
    return not (remind_after and time.time() < remind_after)


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
