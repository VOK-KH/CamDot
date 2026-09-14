"""Platform / host icons: bundled SVGs first, optional cached favicon for unknowns."""
import os
import re
import urllib.request
from functools import lru_cache
from urllib.parse import urlparse

from PySide6.QtGui import QIcon, QPixmap

from app.core import icons

PLATFORM_KEYS = {
    "facebook": "platform-facebook",
    "instagram": "platform-instagram",
    "youtube": "platform-youtube",
    "tiktok": "platform-tiktok",
    "twitter": "platform-x",
}

FAVICON_HOST = "icons.duckduckgo.com"
FAVICON_MAX_BYTES = 100_000


def platform_from_extractor(extractor_key="", domain=""):
    key = (extractor_key or "").lower()
    for name in PLATFORM_KEYS:
        if name in key:
            return name
    host = (domain or "").lower().removeprefix("www.")
    if "facebook." in host or host.endswith("fb.com") or host == "fb.com":
        return "facebook"
    if "instagram." in host:
        return "instagram"
    if "tiktok." in host:
        return "tiktok"
    if "youtube." in host or host == "youtu.be":
        return "youtube"
    if host in ("x.com", "twitter.com", "t.co") or host.endswith(".x.com"):
        return "twitter"
    return ""


def _safe_domain(domain):
    host = (domain or "").lower().split(":")[0].removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9.-]+", host or ""):
        return ""
    return host


def cache_dir(output_root="output"):
    return os.path.join(output_root, ".cache", "favicons")


def fetch_favicon(domain, dest_dir, opener=None):
    """Download a favicon for an unknown host into dest_dir. Returns the path or ''."""
    host = _safe_domain(domain)
    if not host:
        return ""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{host}.ico")
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    url = f"https://{FAVICON_HOST}/ip3/{host}.ico"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "reels-downloader"})
        fetch = opener or urllib.request.urlopen
        with fetch(request, timeout=5) as response:
            if urlparse(response.geturl()).hostname not in (FAVICON_HOST,):
                return ""
            data = response.read(FAVICON_MAX_BYTES + 1)
        if not data or len(data) > FAVICON_MAX_BYTES:
            return ""
        with open(dest, "wb") as f:
            f.write(data)
        return dest
    except Exception:
        return ""


@lru_cache(maxsize=64)
def _file_icon(path, size=16):
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QIcon()
    return QIcon(pixmap.scaled(size, size))


def icon_for(platform="", domain="", extractor_key="", output_root="output", fetch=False, color="#e7ecf3"):
    """Return a QIcon for the host. Known platforms use bundled SVGs."""
    name = platform or platform_from_extractor(extractor_key, domain)
    bundled = PLATFORM_KEYS.get(name, "platform-generic")
    try:
        return icons.icon(bundled, color, 16)
    except OSError:
        pass
    if fetch and domain and name not in PLATFORM_KEYS:
        path = fetch_favicon(domain, cache_dir(output_root))
        if path:
            return _file_icon(path)
    try:
        return icons.icon("platform-generic", color, 16)
    except OSError:
        return QIcon()
