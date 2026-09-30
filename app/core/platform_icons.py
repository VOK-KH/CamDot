"""Platform / host icons: bundled SVGs first, optional cached favicon for unknowns."""
import os
import re
import urllib.request
from functools import lru_cache
from urllib.parse import urlparse

from PySide6.QtGui import QIcon, QPixmap

from app.core import icons
from app.core.runtime import APP_SLUG, util_cache_dir

PLATFORM_KEYS = {
    "facebook": "platform-facebook",
    "instagram": "platform-instagram",
    "youtube": "platform-youtube",
    "tiktok": "platform-tiktok",
    "twitter": "platform-x",
    "bilibili": "platform-bilibili",
    "douyin": "platform-douyin",
    "kuaishou": "platform-kuaishou",
    "pinterest": "platform-pinterest",
}

FAVICON_HOST = "icons.duckduckgo.com"
FAVICON_MAX_BYTES = 100_000
_GOOGLE_FAVICON = "https://www.google.com/s2/favicons?domain={host}&sz=32"


def platform_from_extractor(extractor_key="", domain=""):
    key = (extractor_key or "").lower()
    if "bili" in key:
        return "bilibili"
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
    if "bilibili." in host or host in ("b23.tv", "bilibili.tv") or host.endswith(".b23.tv"):
        return "bilibili"
    if "douyin." in host or "iesdouyin." in host:
        return "douyin"
    if "kuaishou." in host or "gifshow." in host or host.endswith("kwai.com"):
        return "kuaishou"
    if "pinterest." in host or host == "pin.it":
        return "pinterest"
    if "threads." in host:
        return "threads"
    if "reddit." in host or host in ("redd.it", "old.reddit.com"):
        return "reddit"
    if "snapchat." in host:
        return "snapchat"
    if "xiaohongshu." in host or host == "xhslink.com" or host.endswith(".xhslink.com"):
        return "xiaohongshu"
    if "weibo." in host:
        return "weibo"
    if "twitch." in host:
        return "twitch"
    return ""


def _safe_domain(domain):
    host = (domain or "").lower().split(":")[0].removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9.-]+", host or ""):
        return ""
    return host


def cache_dir(output_root="output"):
    return os.path.join(util_cache_dir(), "favicons")


def favicon_cache_path(domain, dest_dir=None):
    """Cached favicon path under app data, or '' if missing."""
    host = _safe_domain(domain)
    if not host:
        return ""
    folder = dest_dir or cache_dir()
    for ext in ("ico", "png"):
        path = os.path.join(folder, f"{host}.{ext}")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return ""


def _download_favicon(url, dest, opener=None, allowed_hosts=None):
    allowed = set(allowed_hosts or ())
    try:
        request = urllib.request.Request(url, headers={"User-Agent": APP_SLUG})
        fetch = opener or urllib.request.urlopen
        with fetch(request, timeout=5) as response:
            host = urlparse(response.geturl()).hostname or ""
            if allowed and host not in allowed:
                return False
            data = response.read(FAVICON_MAX_BYTES + 1)
        if not data or len(data) > FAVICON_MAX_BYTES:
            return False
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(data)
        return True
    except Exception:
        return False


def fetch_favicon(domain, dest_dir, opener=None):
    """Download a site favicon into dest_dir (app cache). Returns the path or ''."""
    host = _safe_domain(domain)
    if not host:
        return ""
    os.makedirs(dest_dir, exist_ok=True)
    cached = favicon_cache_path(host, dest_dir)
    if cached:
        return cached
    dest_ico = os.path.join(dest_dir, f"{host}.ico")
    if _download_favicon(
        f"https://{FAVICON_HOST}/ip3/{host}.ico",
        dest_ico,
        opener=opener,
        allowed_hosts={FAVICON_HOST},
    ):
        return dest_ico
    dest_png = os.path.join(dest_dir, f"{host}.png")
    if _download_favicon(
        _GOOGLE_FAVICON.format(host=host),
        dest_png,
        opener=opener,
        allowed_hosts={"www.google.com", "google.com"},
    ):
        return dest_png
    return ""


@lru_cache(maxsize=64)
def _file_icon(path, size=16):
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QIcon()
    return QIcon(pixmap.scaled(size, size))


def host_color_icon(domain, fetch=True, size=16, color="#e7ecf3"):
    """Colored site favicon from app cache, fetched on first use when ``fetch`` is true."""
    host = _safe_domain(domain)
    folder = cache_dir()
    if fetch and host:
        fetch_favicon(host, folder)
    path = favicon_cache_path(host or domain, folder)
    if path:
        return _file_icon(path, size)
    name = platform_from_extractor("", domain)
    return icon_for(platform=name, domain=domain, fetch=False, color=color)


def icon_for(platform="", domain="", extractor_key="", output_root="output", fetch=False, color="#e7ecf3"):
    """Return a QIcon for the host. Known platforms use bundled SVGs."""
    name = platform or platform_from_extractor(extractor_key, domain)
    if fetch and domain:
        path = fetch_favicon(domain, cache_dir(output_root))
        if path:
            return _file_icon(path)
    if name in PLATFORM_KEYS:
        try:
            return icons.icon(PLATFORM_KEYS[name], color, 16)
        except OSError:
            pass
    try:
        return icons.icon("platform-generic", color, 16)
    except OSError:
        return QIcon()
