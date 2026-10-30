"""Platform / host icons: bundled SVGs, bundled provider PNGs, and cached favicons."""
import os
import re
import urllib.request
from functools import lru_cache
from urllib.parse import urlparse

from PySide6.QtCore import Qt
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
    "kwai": "platform-kuaishou",
    "pinterest": "platform-pinterest",
    "snackvideo": "platform-snackvideo",
    "xiaohongshu": "platform-xiaohongshu",
    "medaltv": "platform-medaltv",
    "threads": "platform-threads",
    "suno": "platform-suno",
    "reddit": "platform-reddit",
    "dailymotion": "platform-dailymotion",
    "snapchat": "platform-snapchat",
    "weibo": "platform-weibo",
    "twitch": "platform-twitch",
    "scraped": "platform-scraped",
}

# Bundled PNG logos under images/icons/platforms/<name>.png
PLATFORM_PNG_LOGOS = {
    "facebook": "facebook",
    "instagram": "instagram",
    "pinterest": "pinterest",
    "youtube": "youtube",
    "tiktok": "tiktok",
    "douyin": "douyin",
    "kwai": "kwai",
    "snackvideo": "snackvideo",
    "kuaishou": "kuaishou",
    "xiaohongshu": "xiaohongshu",
    "medaltv": "medaltv",
    "threads": "threads",
    "suno": "suno",
    "twitter": "twitter",
    "reddit": "reddit",
    "dailymotion": "dailymotion",
    "bilibili": "bilibili",
    "snapchat": "snapchat",
    "weibo": "weibo",
    "twitch": "twitch",
    "scraped": "scraped",
    "dramabox": "dramabox",
    "netshort": "netshort",
    "flickreels": "flickreels",
    "stardusttv": "stardusttv",
    "starshort": "starshort",
    "goodshort": "goodshort",
    "dramawave": "dramawave",
    "freereels": "freereels",
    "reelshort": "reelshort",
    "hongguo": "hongguo",
    "idrama": "idrama",
    "bilitv": "bilitv",
    "wetv": "wetv",
    "iqiyi": "iqiyi",
    "dramabite": "dramabite",
    "vigloo": "vigloo",
    "kisskh": "kisskh",
    "flextv": "flextv",
    "melolo": "melolo",
    "kolabkhmer": "kolabkhmer",
    # Extra QuickPlay provider logos bundled in images/icons/platforms/
    "meloshort": "meloshort",
    "reelife": "reelife",
    "shortmax": "shortmax",
    "dramarush": "dramarush",
    "rapidtv": "rapidtv",
    "dramanova": "dramanova",
    "fundrama": "fundrama",
    "dramapops": "dramapops",
    "snackshort": "snackshort",
    "sodareels": "sodareels",
    "cubetv": "cubetv",
    "shortwave": "shortwave",
    "reelala": "reelala",
    "shotshort": "shotshort",
    "microdrama": "microdrama",
    "radreels": "radreels",
    "sereal": "sereal",
    "cashdrama": "cashdrama",
    "flickshort": "flickshort",
    "dotdrama": "dotdrama",
    "moboreels": "moboreels",
    "sarostv": "sarostv",
    "velolo": "velolo",
    "shortbox": "shortbox",
    "pinedrama": "pinedrama",
    "bstation": "bstation",
    "luminareels": "luminareels",
    "shortsky": "shortsky",
    "bonustv": "bonustv",
    "vibeshort": "vibeshort",
    "dramaverse": "dramaverse",
    "storyreel": "storyreel",
    "lupacine": "lupacine",
}

_EXTRACTOR_PLATFORM_ALIASES = (
    ("bilitv", "bilitv"),
    ("bili", "bilibili"),
    ("facebook", "facebook"),
    ("instagram", "instagram"),
    ("youtube", "youtube"),
    ("tiktok", "tiktok"),
    ("twitter", "twitter"),
    ("douyin", "douyin"),
    ("kwai", "kwai"),
    ("snackvideo", "snackvideo"),
    ("kuaishou", "kuaishou"),
    ("pinterest", "pinterest"),
    ("xiaohongshu", "xiaohongshu"),
    ("xhs", "xiaohongshu"),
    ("medal", "medaltv"),
    ("threads", "threads"),
    ("suno", "suno"),
    ("reddit", "reddit"),
    ("dailymotion", "dailymotion"),
    ("snapchat", "snapchat"),
    ("weibo", "weibo"),
    ("twitch", "twitch"),
    ("dramabox", "dramabox"),
    ("netshort", "netshort"),
    ("flickreels", "flickreels"),
    ("stardusttv", "stardusttv"),
    ("starshort", "starshort"),
    ("goodshort", "goodshort"),
    ("dramawave", "dramawave"),
    ("freereels", "freereels"),
    ("reelshort", "reelshort"),
    ("hongguo", "hongguo"),
    ("idrama", "idrama"),
    ("wetv", "wetv"),
    ("iqiyi", "iqiyi"),
    ("iq.com", "iqiyi"),
    ("dramabite", "dramabite"),
    ("vigloo", "vigloo"),
    ("kisskh", "kisskh"),
    ("flextv", "flextv"),
    ("melolo", "melolo"),
    ("kolabkhmer", "kolabkhmer"),
)

_HOST_PLATFORM_SUFFIXES = (
    (("facebook.com", "fb.com", "fb.watch"), "facebook"),
    (("instagram.com", "instagr.am"), "instagram"),
    (("tiktok.com",), "tiktok"),
    (("youtube.com", "youtu.be"), "youtube"),
    (("x.com", "twitter.com", "t.co"), "twitter"),
    (("bilitv.com",), "bilitv"),
    (("bilibili.tv", "bilibili.com", "b23.tv"), "bilibili"),
    (("douyin.com", "iesdouyin.com"), "douyin"),
    (("kwai.com", "kwai-video.com", "kw.ai", "s.kw.ai"), "kwai"),
    (("snackvideo.com", "sck.io"), "snackvideo"),
    (("kuaishou.com", "gifshow.com"), "kuaishou"),
    (("pinterest.com", "pin.it"), "pinterest"),
    (("xiaohongshu.com", "xhslink.com"), "xiaohongshu"),
    (("medal.tv",), "medaltv"),
    (("threads.com", "threads.net"), "threads"),
    (("suno.com", "suno.ai"), "suno"),
    (("reddit.com", "redd.it", "old.reddit.com", "v.redd.it", "i.redd.it"), "reddit"),
    (("dailymotion.com", "dai.ly"), "dailymotion"),
    (("snapchat.com",), "snapchat"),
    (("weibo.com", "weibo.cn"), "weibo"),
    (("twitch.tv",), "twitch"),
    (("dramaboxdb.com", "dramabox.com", "dramaboxapp.com"), "dramabox"),
    (("netshort.com",), "netshort"),
    (("flickreels.net", "flickreels.com"), "flickreels"),
    (("stardusttv.net",), "stardusttv"),
    (("starshort.tv",), "starshort"),
    (("goodshort.com",), "goodshort"),
    (("mydramawave.com", "dramawave.com"), "dramawave"),
    (("free-reels.com", "freereels.com"), "freereels"),
    (("reelshort.com",), "reelshort"),
    (("hongguoduanju.com",), "hongguo"),
    (("idrama.video",), "idrama"),
    (("wetv.vip", "v.qq.com"), "wetv"),
    (("iq.com", "iqiyi.com"), "iqiyi"),
    (("dramabite.media",), "dramabite"),
    (("vigloo.com",), "vigloo"),
    (("kisskh.org", "kisskh.ovh", "kisskh.co", "kisskh.do", "kisskh.la", "kisskh.id", "kisskh.me"), "kisskh"),
    (("flextv.cc",), "flextv"),
    (("melolo.org", "melolo.com"), "melolo"),
    (("kolabkhmer.com",), "kolabkhmer"),
)

FAVICON_HOST = "icons.duckduckgo.com"
FAVICON_MAX_BYTES = 100_000
_GOOGLE_FAVICON = "https://www.google.com/s2/favicons?domain={host}&sz=32"


def platform_from_extractor(extractor_key="", domain=""):
    key = (extractor_key or "").lower()
    for token, platform in _EXTRACTOR_PLATFORM_ALIASES:
        if token in key:
            return platform
    host = (domain or "").lower().removeprefix("www.").removeprefix("m.")
    for suffixes, platform in _HOST_PLATFORM_SUFFIXES:
        if any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
            return platform
    if "facebook." in host:
        return "facebook"
    if "instagram." in host:
        return "instagram"
    if "tiktok." in host:
        return "tiktok"
    if "youtube." in host:
        return "youtube"
    if "bilibili." in host:
        return "bilibili"
    if "douyin." in host or "iesdouyin." in host:
        return "douyin"
    if "kuaishou." in host or "gifshow." in host:
        return "kuaishou"
    if "pinterest." in host:
        return "pinterest"
    if "threads." in host:
        return "threads"
    if "reddit." in host:
        return "reddit"
    if "snapchat." in host:
        return "snapchat"
    if "xiaohongshu." in host:
        return "xiaohongshu"
    if "weibo." in host:
        return "weibo"
    if "twitch." in host:
        return "twitch"
    if "kisskh." in host:
        return "kisskh"
    stem = host.split(".")[0] if host else ""
    if stem in PLATFORM_PNG_LOGOS:
        return stem
    return ""


def _safe_domain(domain):
    host = (domain or "").lower().split(":")[0].removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9.-]+", host or ""):
        return ""
    return host


def cache_dir(output_root="output"):
    return os.path.join(util_cache_dir(), "favicons")


def bundled_platform_png_path(platform_id):
    """Path to bundled PNG in images/icons/platforms/<name>.png, or ''."""
    logo = PLATFORM_PNG_LOGOS.get((platform_id or "").lower())
    if not logo:
        return ""
    path = os.path.join(icons.icon_dir(), "platforms", f"{logo}.png")
    return path if os.path.isfile(path) else ""


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


@lru_cache(maxsize=128)
def _file_icon(path, size=16):
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QIcon()
    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(scaled)


def host_color_icon(domain, fetch=True, size=16, color="#e7ecf3"):
    """Colored site favicon from bundled logo or app cache."""
    name = platform_from_extractor("", domain)
    bundled = bundled_platform_png_path(name)
    if bundled:
        return _file_icon(bundled, size)
    host = _safe_domain(domain)
    folder = cache_dir()
    if fetch and host:
        fetch_favicon(host, folder)
    path = favicon_cache_path(host or domain, folder)
    if path:
        return _file_icon(path, size)
    return icon_for(platform=name, domain=domain, fetch=False, color=color)


def icon_for(platform="", domain="", extractor_key="", output_root="output", fetch=False, color="#e7ecf3"):
    """Return a QIcon for the host. Bundled SVGs and provider PNGs come first."""
    name = platform or platform_from_extractor(extractor_key, domain)
    bundled = bundled_platform_png_path(name)
    if bundled:
        icon = _file_icon(bundled)
        if not icon.isNull():
            return icon
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
