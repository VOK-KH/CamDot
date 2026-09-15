"""Small GUI helpers that do not need Qt widgets."""
import re
from urllib.parse import parse_qs, urlparse

from app.core.collect import tiktok_username_for_sec_uid
from app.gui.constants import RECENT_URL_LIMIT
from app.core.urls import is_tiktok_user_feed, tiktok_sec_uid


def remember_recent(urls, url, limit=RECENT_URL_LIMIT):
    """Move `url` to the front of the recent list, dropping duplicates and overflow."""
    url = (url or "").strip()
    if not url:
        return list(urls)
    return [url, *[item for item in urls if item != url]][:limit]


def derive_channel(source, preferred=""):
    """Return a safe output folder name from settings or the pasted URL."""
    if preferred.strip():
        raw = preferred.strip()
    elif is_tiktok_user_feed(source):
        sec_uid = tiktok_sec_uid(source)
        raw = tiktok_username_for_sec_uid(sec_uid) or f"tiktok-{sec_uid[-10:]}"
    else:
        parts = urlparse(source if "://" in source else "https://" + source)
        segments = [part for part in parts.path.split("/") if part]
        query = parse_qs(parts.query)
        if query.get("v"):
            raw = query["v"][0]
        elif query.get("modal_id"):
            raw = query["modal_id"][0]
        elif query.get("id"):
            raw = query["id"][0]
        elif segments:
            head = segments[0]
            if head.lower() in (
                "people", "reel", "reels", "watch", "p", "tv", "videos", "shorts",
                "video", "play", "en", "id", "th", "vi", "ms",
            ):
                raw = segments[-1]
            elif len(segments) >= 2 and segments[1].lower() in ("video", "play"):
                raw = segments[-1]
            else:
                raw = head.lstrip("@")
        else:
            raw = "downloads"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
    return safe or "downloads"
