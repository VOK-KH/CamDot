"""Multi-library web media extractor and downloader fallback.

Used when yt-dlp has no native extractor for a site or fails to extract formats:
1. curl_cffi (Chrome TLS/HTTP2 impersonation for Cloudflare / bot-protected sites)
2. requests (session HTTP client)
3. urllib.request (standard library HTTP fallback)
4. ffmpeg (direct HLS .m3u8 / DASH .mpd stream remuxing)
"""
import hashlib
import html as _html
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from app.core.jobs import StopRequested, check_stop
from app.core.runtime import resolve_ffmpeg
from app.core.sysinfo import ffmpeg_hwaccel_args
from app.core.urls import (
    detect_platform,
    dramabox_play_ids,
    flickreels_play_ids,
    goodshort_play_ids,
    hongguo_play_ids,
    instagram_shortcode,
    instagram_username,
    is_scraped_media_url,
)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_SUNO_UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_META_TAG_RE = re.compile(r"<meta\b[^>]+>", re.IGNORECASE)
_ATTR_RE = re.compile(
    r'([a-zA-Z0-9_:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))'
)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_JSON_RE = re.compile(
    r'<script[^>]+(?:id=["\'](?:__NEXT_DATA__|__NUXT_DATA__|__UNIVERSAL_DATA_FOR_REHYDRATION__)["\']|type=["\']application/(?:ld\+)?json["\'])[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_VIDEO_SRC_RE = re.compile(
    r'<(?:video|source|audio)\b[^>]+?\bsrc=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_STREAM_URL_RE = re.compile(
    r'https?:(?:\\?/\\?/|//)[^\s"\'<>\\]+?\.(?:m3u8|mpd|mp4|webm|mp3|m4a)(?:\?[^\s"\'<>\\]*)?',
    re.IGNORECASE,
)
_IMAGE_URL_RE = re.compile(
    r'https?:(?:\\?/\\?/|//)[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\s"\'<>\\]*)?',
    re.IGNORECASE,
)
_SJS_RE = re.compile(r"<script\b[^>]+\bdata-sjs>(\{.+?\})</script>", re.IGNORECASE | re.DOTALL)
_IG_ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-S921B Build/UP1A.231005.007; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.0.0 "
    "Mobile Safari/537.36 Instagram 340.0.0.36.90 Android "
    "(34/14; 480dpi; 1080x2340; samsung; SM-S921B; e1s; s5e9945; en_US; 629151101)"
)
_IG_ANDROID_APP_ID = "3419628305025917"
_HREF_RE = re.compile(r'<a\b[^>]+?\bhref=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_EPISODE_HREF_RE = re.compile(
    r"(?:/(?:ep|episode|episodes|chapter|watch|play)[-_/\d]|(?:\?|&)(?:ep|episode|chapter)=)",
    re.IGNORECASE,
)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _unescape_url(raw):
    if not raw:
        return ""
    text = str(raw).strip()
    text = (
        text.replace(r"\/", "/")
        .replace(r"\u002F", "/")
        .replace(r"\u002f", "/")
        .replace(r"\u0026", "&")
        .replace(r"\u003d", "=")
        .replace(r"\u003D", "=")
    )
    return _html.unescape(text).strip()


def _origin_headers(url, extra=None):
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if origin:
        headers["Referer"] = origin + "/"
    if extra:
        headers.update(extra)
    return headers


def _urllib_is_mocked():
    return getattr(urllib.request.urlopen, "__module__", "") != "urllib.request"


def fetch_text(url, *, headers=None, timeout=20, opener=None):
    """Fetch `(html_text, final_url)` trying curl_cffi -> requests -> urllib."""
    req_headers = _origin_headers(url, headers)
    if opener is not None or _urllib_is_mocked():
        request = urllib.request.Request(url, headers=req_headers)
        open_fn = opener or urllib.request.urlopen
        with open_fn(request, timeout=timeout) as resp:
            final_url = getattr(resp, "geturl", lambda: url)() or url
            body = resp.read().decode("utf-8", errors="replace")
            return body, final_url

    # 1. Try curl_cffi with Chrome TLS fingerprint
    try:
        from curl_cffi import requests as curl_requests
        resp = curl_requests.get(
            url,
            headers=req_headers,
            impersonate="chrome",
            allow_redirects=True,
            timeout=timeout,
        )
        if resp.status_code < 400 and resp.text:
            return resp.text, str(resp.url or url)
    except Exception:
        pass

    # 2. Try requests
    try:
        import requests
        resp = requests.get(
            url,
            headers=req_headers,
            allow_redirects=True,
            timeout=timeout,
        )
        if resp.status_code < 400 and resp.text:
            return resp.text, str(resp.url or url)
    except Exception:
        pass

    # 3. Standard library urllib.request
    request = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        final_url = getattr(resp, "geturl", lambda: url)() or url
        body = resp.read().decode("utf-8", errors="replace")
        return body, final_url


def fetch_bytes(url, *, referer="", timeout=60, opener=None, on_chunk=None):
    """Download binary content trying curl_cffi -> requests -> urllib."""
    headers = _origin_headers(referer or url)
    if referer:
        headers["Referer"] = referer

    if opener is not None or _urllib_is_mocked():
        request = urllib.request.Request(url, headers=headers)
        open_fn = opener or urllib.request.urlopen
        with open_fn(request, timeout=timeout) as resp:
            data = resp.read()
            if on_chunk and data:
                on_chunk(len(data), len(data))
            return data

    # 1. curl_cffi (streamed for live speed/ETA progress)
    try:
        from curl_cffi import requests as curl_requests
        resp = curl_requests.get(
            url,
            headers=headers,
            impersonate="chrome",
            allow_redirects=True,
            stream=True,
            timeout=timeout,
        )
        try:
            if resp.status_code < 400:
                total = int(resp.headers.get("Content-Length") or resp.headers.get("content-length") or 0) or None
                chunks = []
                downloaded = 0
                iter_fn = getattr(resp, "iter_content", None)
                if callable(iter_fn):
                    for chunk in iter_fn(chunk_size=65536):
                        if not chunk:
                            continue
                        chunks.append(chunk)
                        downloaded += len(chunk)
                        if on_chunk:
                            on_chunk(downloaded, total)
                    data = b"".join(chunks)
                else:
                    data = resp.content
                    if on_chunk and data:
                        on_chunk(len(data), total or len(data))
                if data:
                    return data
        finally:
            close_fn = getattr(resp, "close", None)
            if callable(close_fn):
                close_fn()
    except Exception:
        pass

    # 2. requests (chunked for progress)
    try:
        import requests
        with requests.get(
            url,
            headers=headers,
            allow_redirects=True,
            stream=True,
            timeout=timeout,
        ) as resp:
            if resp.status_code < 400:
                total = int(resp.headers.get("Content-Length") or 0) or None
                chunks = []
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if on_chunk:
                        on_chunk(downloaded, total)
                data = b"".join(chunks)
                if data:
                    return data
    except Exception:
        pass

    # 3. urllib.request
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        total_hdr = None
        if hasattr(resp, "headers") and resp.headers:
            try:
                total_hdr = int(resp.headers.get("Content-Length") or 0) or None
            except (TypeError, ValueError):
                total_hdr = None
        data = resp.read()
        if on_chunk and data:
            on_chunk(len(data), total_hdr or len(data))
        return data


def _parse_meta_tags(page_html):
    meta = {}
    for tag in _META_TAG_RE.findall(page_html or ""):
        attrs = {}
        for match in _ATTR_RE.finditer(tag):
            key = match.group(1).lower()
            val = match.group(2) or match.group(3) or match.group(4) or ""
            attrs[key] = _html.unescape(val)
        name = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        content = attrs.get("content") or ""
        if name and content and name not in meta:
            meta[name] = content.strip()
    return meta


def _media_kind_for_url(media_url):
    path = urlparse(media_url).path.lower()
    ext = os.path.splitext(path)[1]
    if ext in (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"):
        return "music"
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        return "image"
    return "video"


def _ext_for_media_url(media_url, kind="video"):
    path = urlparse(media_url).path.lower()
    ext = os.path.splitext(path)[1]
    if ext in (".m3u8", ".mpd", ".ts"):
        return ".mp4"
    if ext in (
        ".mp4", ".webm", ".mkv", ".mov",
        ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus",
        ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ):
        return ext
    if kind == "music":
        return ".mp3"
    if kind == "image":
        return ".jpg"
    return ".mp4"


_JSON_MEDIA_KEYS = (
    "video_url", "videoUrl", "play_url", "playUrl", "playAddr", "downloadAddr",
    "stream_url", "streamUrl", "m3u8_url", "m3u8Url", "hls_url", "hlsUrl",
    "masterUrl", "mp4Url", "contentUrl", "audio_url", "audioUrl",
    "main_url", "backup_url",
)
_JSON_IMAGE_KEYS = (
    "display_url", "image_url", "imageUrl", "cover_url", "coverUrl", "pic_url",
)
_JSON_TITLE_KEYS = (
    "title", "name", "bookName", "dramaName", "seriesName", "chapterName", "episodeName",
)


def _walk_json_media(obj, base_url="", found_streams=None, found_images=None, titles=None, depth=0):
    if depth > 25 or obj is None:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str):
                cleaned = _unescape_url(value)
                if key in _JSON_TITLE_KEYS and cleaned and not cleaned.startswith("http"):
                    titles.append(cleaned)
                if cleaned.startswith(("http://", "https://", "//")):
                    if cleaned.startswith("//"):
                        cleaned = "https:" + cleaned
                    lower = cleaned.lower()
                    if key in _JSON_MEDIA_KEYS or any(
                        token in lower for token in (".m3u8", ".mpd", ".mp4", ".webm", ".mp3", ".m4a", "mime_type=video")
                    ):
                        if not any(lower.endswith(ext) for ext in (".js", ".css", ".html", ".json", ".svg", ".ico")):
                            found_streams.append(cleaned)
                    elif key in _JSON_IMAGE_KEYS or any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
                        found_images.append(cleaned)
            elif isinstance(value, (dict, list)):
                _walk_json_media(value, base_url, found_streams, found_images, titles, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_media(item, base_url, found_streams, found_images, titles, depth + 1)


def _suno_media_info(url, page_html="", final_url=""):
    match = _SUNO_UUID_RE.search(url or "") or _SUNO_UUID_RE.search(final_url or "") or _SUNO_UUID_RE.search(page_html or "")
    if not match:
        return None
    song_id = match.group(1).lower()
    meta = _parse_meta_tags(page_html)
    title = meta.get("og:title") or meta.get("twitter:title") or song_id
    description = meta.get("og:description") or meta.get("description") or ""
    audio_url = meta.get("og:audio") or f"https://cdn1.suno.ai/{song_id}.mp3"
    video_url = meta.get("og:video") or f"https://cdn1.suno.ai/{song_id}.mp4"
    image_url = meta.get("og:image") or f"https://cdn2.suno.ai/image_{song_id}.jpeg"
    return {
        "id": song_id,
        "title": title,
        "description": description,
        "uploader": "SUNO",
        "media": [
            ("music", _unescape_url(audio_url)),
            ("video", _unescape_url(video_url)),
            ("image", _unescape_url(image_url)),
        ],
    }


def resolution_label(width=0, height=0, filepath=""):
    """Human quality tag such as ``720p MP4`` or ``1080p`` from dimensions + path."""
    try:
        w = int(width or 0)
        h = int(height or 0)
    except (TypeError, ValueError):
        w, h = 0, 0
    short = min(w, h) if (w > 0 and h > 0) else max(w, h)
    res = ""
    if short >= 2160:
        res = "4K"
    elif short >= 1440:
        res = "2K"
    elif short >= 1080:
        res = "1080p"
    elif short >= 720:
        res = "720p"
    elif short >= 540:
        res = "540p"
    elif short >= 480:
        res = "480p"
    elif short >= 360:
        res = "360p"
    elif short > 0:
        res = f"{short}p"
    ext = os.path.splitext(filepath or "")[1].lstrip(".").upper()
    if ext in ("PART", "YTDL", ""):
        ext = ""
    if res and ext:
        return f"{res} {ext}"
    return res


def mp4_video_info(path):
    """Read ``(duration_sec, width, height)`` from an MP4/MOV/M4A file's ``moov`` atom."""
    if not path or not os.path.isfile(path):
        return None, 0, 0
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".mp4", ".mov", ".m4a", ".m4v"):
        return None, 0, 0
    dur = None
    width, height = 0, 0
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            def scan(end_pos, depth=0):
                nonlocal dur, width, height
                if depth > 6:
                    return
                while handle.tell() + 8 <= end_pos:
                    pos = handle.tell()
                    hdr = handle.read(8)
                    if len(hdr) < 8:
                        break
                    box_size, box_type = struct.unpack(">I4s", hdr)
                    hdr_len = 8
                    if box_size == 1:
                        ext_hdr = handle.read(8)
                        if len(ext_hdr) < 8:
                            break
                        box_size = struct.unpack(">Q", ext_hdr)[0]
                        hdr_len = 16
                    elif box_size == 0:
                        box_size = end_pos - pos
                    if box_size < hdr_len or pos + box_size > end_pos:
                        break
                    if box_type in (b"moov", b"trak"):
                        scan(pos + box_size, depth + 1)
                    elif box_type == b"mvhd" and dur is None:
                        body = handle.read(min(32, box_size - hdr_len))
                        if len(body) >= 20:
                            version = body[0]
                            if version == 0 and len(body) >= 20:
                                timescale, duration = struct.unpack(">II", body[12:20])
                                if timescale > 0:
                                    dur = round(duration / timescale, 2)
                            elif version == 1 and len(body) >= 32:
                                timescale, duration = struct.unpack(">IQ", body[20:32])
                                if timescale > 0:
                                    dur = round(duration / timescale, 2)
                    elif box_type == b"tkhd":
                        body = handle.read(min(96, box_size - hdr_len))
                        if len(body) >= 84:
                            version = body[0]
                            w_off = 76 if version == 0 else 88
                            if len(body) >= w_off + 8:
                                w_fixed, h_fixed = struct.unpack(">II", body[w_off:w_off + 8])
                                w, h = w_fixed >> 16, h_fixed >> 16
                                if w > width and h > height:
                                    width, height = w, h
                    handle.seek(pos + box_size)

            scan(size)
    except (OSError, struct.error, ValueError):
        pass
    return dur, width, height


def mp4_duration_seconds(path):
    """Read duration in seconds from an MP4/MOV/M4A file's ``moov/mvhd`` atom."""
    dur, _w, _h = mp4_video_info(path)
    return dur


_HONGGUO_SERIES_CACHE = {}
_DRAMABOX_SERIES_CACHE = {}
_GOODSHORT_SERIES_CACHE = {}
_FLICKREELS_SERIES_CACHE = {}
_NEXT_DATA_SCRIPT_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_NUXT_ARRAY_RE = re.compile(
    r"<script[^>]*>(\[\[\s*[\"']ShallowReactive[\"'].*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def _parse_flickreels_nuxt_data(page_html):
    """Extract (series_info, chapters, stream_url) from FlickReels Nuxt 3 payload."""
    if not page_html:
        return {}, [], ""
    match = _NUXT_ARRAY_RE.search(page_html)
    if not match:
        return {}, [], ""
    try:
        arr = json.loads(match.group(1))
    except (ValueError, json.JSONDecodeError):
        return {}, [], ""
    if not isinstance(arr, list) or not arr:
        return {}, [], ""

    stream_url = ""
    for item in arr:
        if isinstance(item, str) and ".m3u8" in item.lower() and item.startswith("http"):
            stream_url = _unescape_url(item)
            break

    def deref(idx, depth=0):
        if depth > 7 or not isinstance(idx, int) or idx < 0 or idx >= len(arr):
            return idx
        val = arr[idx]
        if isinstance(val, list):
            if len(val) == 2 and isinstance(val[0], str) and val[0] in (
                "ShallowReactive", "Reactive", "Ref", "EmptyRef", "EmptyShallowRef",
            ):
                return deref(val[1], depth + 1)
            return [deref(x, depth + 1) for x in val]
        if isinstance(val, dict):
            return {k: deref(v, depth + 1) for k, v in val.items()}
        return val

    root = deref(0)
    data = (root.get("data") if isinstance(root, dict) else None) or {}
    if not isinstance(data, dict):
        return {}, [], stream_url
    for key, val in data.items():
        if key.startswith("chapters-list-") and isinstance(val, dict):
            chapters = val.get("list") if isinstance(val.get("list"), list) else []
            playlet_id = str(val.get("playlet_id") or "").strip()
            if playlet_id and chapters:
                _FLICKREELS_SERIES_CACHE[playlet_id] = (val, chapters)
            return val, chapters, stream_url
    return {}, [], stream_url


def _decrypt_flickreels_wbc(cipher, key="aHq$7%cNBqQb@qQxwiGnt&"):
    """Decrypt a FlickReels 'wbc...' collection payload into a dict (or {})."""
    if not isinstance(cipher, str) or not cipher.startswith("wbc") or not key:
        return {}
    try:
        import base64
        rev = cipher[3:][::-1].replace("-", "+").replace("_", "/").replace("~", "=")
        pad = (-len(rev)) % 4
        if pad:
            rev += "=" * pad
        raw = base64.b64decode(rev)
        key_bytes = [ord(c) for c in key]
        klen = len(key_bytes)
        plain = "".join(chr(b ^ key_bytes[i % klen]) for i, b in enumerate(raw))
        parsed = json.loads(plain)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _fetch_flickreels_chapter_list(playlet_id, *, timeout=12):
    """Call POST https://apiweb.flickreels.net/web/playlet/chapterList for all episodes."""
    if not playlet_id or _urllib_is_mocked():
        return {}, []
    body = {
        "guid": str(uuid.uuid4()),
        "language_id": "1",
        "os": "pc",
        "playlet_id": str(playlet_id),
    }
    raw = "&".join(f"{k}={body[k]}" for k in sorted(body)) + "&signSalt=nW8GqjbdSYRI"
    sign = hashlib.md5(raw.encode("utf-8")).hexdigest().lower()
    headers = {
        "User-Agent": DEFAULT_UA,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "sign": sign,
        "Web-System": "pc",
        "Origin": "https://www.flickreels.net",
        "Referer": "https://www.flickreels.net/",
    }
    try:
        from curl_cffi import requests as curl_requests
        resp = curl_requests.post(
            "https://apiweb.flickreels.net/web/playlet/chapterList",
            json=body, headers=headers, impersonate="chrome", timeout=timeout,
        )
        if resp.status_code < 400 and resp.text:
            payload = resp.json()
            val = (payload or {}).get("data") or {}
            if isinstance(val, dict):
                if isinstance(val.get("collection"), str) and val["collection"].startswith("wbc"):
                    val["collection"] = _decrypt_flickreels_wbc(val["collection"])
                chapters = val.get("list") if isinstance(val.get("list"), list) else []
                if chapters:
                    _FLICKREELS_SERIES_CACHE[str(playlet_id)] = (val, chapters)
                    return val, chapters
    except Exception:
        pass
    return {}, []


def _fetch_flickreels_play_stream(playlet_id, chapter_id, ep_num=None, *, timeout=12):
    """Resolve a FlickReels episode HLS stream via web play API or ad-unlock fallback."""
    if not playlet_id:
        return ""
    if chapter_id:
        body = {
            "chapter_id": str(chapter_id),
            "guid": str(uuid.uuid4()),
            "language_id": "1",
            "os": "pc",
            "playlet_id": str(playlet_id),
        }
        raw = "&".join(f"{k}={body[k]}" for k in sorted(body)) + "&signSalt=nW8GqjbdSYRI"
        sign = hashlib.md5(raw.encode("utf-8")).hexdigest().lower()
        headers = {
            "User-Agent": DEFAULT_UA,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "sign": sign,
            "Web-System": "pc",
            "Origin": "https://www.flickreels.net",
            "Referer": "https://www.flickreels.net/",
        }
        api_url = "https://apiweb.flickreels.net/web/playlet/play"
        try:
            from curl_cffi import requests as curl_requests
            resp = curl_requests.post(
                api_url, json=body, headers=headers, impersonate="chrome", timeout=timeout,
            )
            if resp.status_code < 400 and resp.text:
                payload = resp.json()
                data = (payload or {}).get("data") or {}
                if isinstance(data, dict) and data.get("hls_url"):
                    return _unescape_url(data["hls_url"])
        except Exception:
            pass
    # Locked chapters (is_lock == 1, episodes 12+) only return a QR deep_link on the web endpoint;
    # fall back to the mobile ad-unlock episode resolver with automatic rate-limit backoff.
    if ep_num and not _urllib_is_mocked():
        unlock_url = (
            f"https://api.sansekai.my.id/api/flickreels/get-episode"
            f"?playlet_id={playlet_id}&episodeNumber={int(ep_num)}&lang=en"
        )
        try:
            import time as _time
            from curl_cffi import requests as curl_requests
            for attempt in range(4):
                resp = curl_requests.get(
                    unlock_url, impersonate="chrome", timeout=max(timeout, 15),
                )
                if resp.status_code == 429 and attempt < 3:
                    _time.sleep(6.5 * (attempt + 1))
                    continue
                if resp.status_code < 400 and resp.text:
                    payload = resp.json()
                    data = (payload or {}).get("data") or payload or {}
                    if isinstance(data, dict) and data.get("hls_url"):
                        return _unescape_url(data["hls_url"])
                break
        except Exception:
            pass
    return ""


def _flickreels_media_info(url, page_html="", final_url=""):
    playlet_id, ep_slug = flickreels_play_ids(final_url or url)
    series_info, chapters, stream_url = _parse_flickreels_nuxt_data(page_html)
    if not chapters and playlet_id and playlet_id in _FLICKREELS_SERIES_CACHE:
        series_info, chapters = _FLICKREELS_SERIES_CACHE[playlet_id]
    if not chapters and playlet_id:
        series_info, chapters = _fetch_flickreels_chapter_list(playlet_id)
    if isinstance((series_info or {}).get("collection"), str) and series_info["collection"].startswith("wbc"):
        series_info["collection"] = _decrypt_flickreels_wbc(series_info["collection"])
    series_title = str((series_info or {}).get("title") or "").strip()
    if (ep_slug or "").lower() == "full-movie":
        coll = (series_info or {}).get("collection")
        if isinstance(coll, dict):
            coll_stream = _unescape_url(coll.get("hls_url") or "")
            if not coll_stream and playlet_id and coll.get("chapter_id"):
                coll_stream = _fetch_flickreels_play_stream(playlet_id, coll["chapter_id"])
            if coll_stream:
                rid = str(coll.get("chapter_id") or f"{playlet_id}-full-movie")
                dur = None
                if coll.get("duration") not in (None, ""):
                    try:
                        dur = float(coll["duration"])
                    except (TypeError, ValueError):
                        dur = None
                title = f"{series_title} (Full Movie)" if series_title else rid
                return {
                    "id": rid,
                    "title": title,
                    "description": "",
                    "uploader": series_title or "flickreels.net",
                    "duration": dur,
                    "series": series_title,
                    "filename_prefix": f"Full_Movie_ {series_title}" if series_title else "",
                    "media": [("video", coll_stream)],
                }
    ep_num = 1
    m_ep = re.search(r"episode-(\d+)", ep_slug or "", re.I)
    if m_ep:
        ep_num = int(m_ep.group(1))
    chosen = None
    for ch in chapters or ():
        if isinstance(ch, dict) and int(ch.get("chapter_num") or 0) == ep_num:
            chosen = ch
            break
    rid = str((chosen or {}).get("chapter_id") or ep_slug or playlet_id or "flickreels")
    if not stream_url and playlet_id:
        chap_id = (chosen or {}).get("chapter_id") or ""
        stream_url = _fetch_flickreels_play_stream(playlet_id, chap_id, ep_num=ep_num)
    if not stream_url:
        return None
    series_title = str((series_info or {}).get("title") or "").strip()
    dur = None
    if isinstance(chosen, dict) and chosen.get("duration") not in (None, ""):
        try:
            dur = float(chosen["duration"])
        except (TypeError, ValueError):
            dur = None
    ep_title = f"{series_title} E{ep_num}" if series_title else rid
    prefix = f"EP{ep_num:02d}_ {series_title}" if series_title else ""
    return {
        "id": rid,
        "title": ep_title,
        "description": "",
        "uploader": series_title or "flickreels.net",
        "duration": dur,
        "series": series_title,
        "episode_number": ep_num,
        "filename_prefix": prefix,
        "media": [("video", stream_url)],
    }


def _parse_goodshort_initial_state(page_html):
    """Extract (book_info, chapters, current_chapter) from GoodShort window.__INITIAL_STATE__."""
    if not page_html:
        return {}, [], {}
    idx = page_html.find("window.__INITIAL_STATE__=")
    if idx == -1:
        return {}, [], {}
    brace = page_html.find("{", idx)
    if brace == -1:
        return {}, [], {}
    try:
        state, _ = json.JSONDecoder().raw_decode(page_html[brace:])
    except (ValueError, json.JSONDecodeError):
        return {}, [], {}
    if not isinstance(state, dict):
        return {}, [], {}
    bim = state.get("BookInfoModule") if isinstance(state.get("BookInfoModule"), dict) else {}
    br = state.get("BookRead") if isinstance(state.get("BookRead"), dict) else {}
    book_info = (
        (bim.get("book") if isinstance(bim.get("book"), dict) and bim.get("book") else None)
        or (br.get("bookInfo") if isinstance(br.get("bookInfo"), dict) and br.get("bookInfo") else None)
        or {}
    )
    chapters = (
        (br.get("chapterList") if isinstance(br.get("chapterList"), list) and br.get("chapterList") else None)
        or (bim.get("chapterVoList") if isinstance(bim.get("chapterVoList"), list) and bim.get("chapterVoList") else None)
        or []
    )
    current = br.get("chapterInfo") if isinstance(br.get("chapterInfo"), dict) else {}
    book_id = str(book_info.get("bookId") or "").strip()
    if book_id and chapters:
        _GOODSHORT_SERIES_CACHE[book_id] = (book_info, chapters)
    return book_info, chapters, current


def _goodshort_media_info(url, page_html="", final_url="", opener=None, timeout=15):
    slug, chap_id = goodshort_play_ids(url)
    book_id = slug.split("-")[-1] if slug else ""
    book_info, chapters, current = _parse_goodshort_initial_state(page_html)
    if not chapters and book_id and book_id in _GOODSHORT_SERIES_CACHE:
        book_info, chapters = _GOODSHORT_SERIES_CACHE[book_id]
    chosen = None
    ep_num = 1
    if chapters:
        if chap_id:
            for idx, item in enumerate(chapters, start=1):
                if isinstance(item, dict) and str(item.get("id") or "") == str(chap_id):
                    chosen = item
                    ep_num = idx
                    break
        if chosen is None and not chap_id:
            chosen = chapters[0] if isinstance(chapters[0], dict) else None
    if chosen is None and current:
        chosen = current
    if not isinstance(chosen, dict):
        return None
    stream_url = _unescape_url(chosen.get("m3u8Path") or (current or {}).get("m3u8Path") or "")
    if not stream_url:
        return None
    book_name = str(book_info.get("bookName") or "").strip()
    rid = str(chosen.get("id") or chap_id or book_id or "goodshort")
    ep_title = f"{book_name} E{ep_num}" if book_name else rid
    prefix = f"EP{ep_num:02d}_ {book_name}" if book_name else ""
    return {
        "id": rid,
        "title": ep_title,
        "description": "",
        "uploader": book_name or "goodshort.com",
        "series": book_name,
        "episode_number": ep_num,
        "filename_prefix": prefix,
        "media": [("video", stream_url)],
    }


def _parse_dramabox_next_data(page_html):
    """Extract (book_info, chapters, chapter_id, free_source) from DramaBox __NEXT_DATA__."""
    if not page_html:
        return {}, [], "", ""
    match = _NEXT_DATA_SCRIPT_RE.search(page_html)
    if not match:
        return {}, [], "", ""
    try:
        data = json.loads(match.group(1))
    except (ValueError, json.JSONDecodeError):
        return {}, [], "", ""
    props = ((data.get("props") or {}).get("pageProps") or {}) if isinstance(data, dict) else {}
    if not isinstance(props, dict):
        return {}, [], "", ""
    book_info = props.get("bookInfo") if isinstance(props.get("bookInfo"), dict) else {}
    chapters = props.get("chapterList") if isinstance(props.get("chapterList"), list) else []
    chapter_id = str(props.get("chapterId") or "").strip()
    free_source = _unescape_url(props.get("freeSource") or "")
    book_id = str(book_info.get("bookId") or props.get("sourceBookId") or "").strip()
    if book_id and chapters:
        _DRAMABOX_SERIES_CACHE[book_id] = (book_info, chapters)
    return book_info, chapters, chapter_id, free_source


def _dramabox_media_info(url, page_html="", final_url="", opener=None, timeout=15):
    book_id, chapter_id = dramabox_play_ids(url)
    if not book_id and not chapter_id and final_url and final_url != url:
        book_id, chapter_id = dramabox_play_ids(final_url)

    book_info, chapters, page_chap_id, free_source = _parse_dramabox_next_data(page_html)
    if not chapters and book_id and book_id in _DRAMABOX_SERIES_CACHE:
        book_info, chapters = _DRAMABOX_SERIES_CACHE[book_id]

    target_id = chapter_id or page_chap_id
    chosen = None
    ep_num = 1
    if chapters:
        if target_id:
            for idx, item in enumerate(chapters, start=1):
                if isinstance(item, dict) and str(item.get("id") or "") == target_id:
                    chosen = item
                    ep_num = idx
                    break
        if chosen is None and not target_id:
            chosen = chapters[0] if isinstance(chapters[0], dict) else None
            ep_num = 1
            if chosen:
                target_id = str(chosen.get("id") or "")

    stream_url = ""
    if isinstance(chosen, dict):
        stream_url = _unescape_url(chosen.get("mp4") or chosen.get("m3u8Url") or "")
    if not stream_url and free_source:
        stream_url = free_source

    # If cached series chapterList didn't have freeSource for a locked episode, fetch the episode page
    if not stream_url and not page_html and opener is None and not _urllib_is_mocked():
        try:
            ep_html, ep_final = fetch_text(url, timeout=timeout)
            return _dramabox_media_info(url, ep_html, ep_final, opener=opener, timeout=timeout)
        except Exception:
            return None

    if not stream_url:
        return None

    book_name = str(book_info.get("bookName") or "").strip()
    raw_dur = chosen.get("duration") if isinstance(chosen, dict) else None
    dur = None
    if raw_dur not in (None, ""):
        try:
            val = float(raw_dur)
            dur = round(val / 1000.0, 2) if val > 1000 else round(val, 2)
        except (TypeError, ValueError):
            dur = None
    rid = target_id or book_id or "dramabox"
    ep_title = f"{book_name} E{ep_num}" if book_name else rid
    prefix = f"EP{ep_num:02d}_ {book_name}" if book_name else ""
    return {
        "id": rid,
        "title": ep_title,
        "description": "",
        "uploader": book_name or "dramaboxdb.com",
        "duration": dur,
        "series": book_name,
        "episode_number": ep_num,
        "filename_prefix": prefix,
        "media": [("video", stream_url)],
    }


def _parse_hongguo_router_data(page_html):
    """Extract (series_detail, public_video_seo) from Hongguo _ROUTER_DATA JSON."""
    if not page_html:
        return {}, {}
    idx = page_html.find("_ROUTER_DATA")
    if idx == -1:
        return {}, {}
    brace = page_html.find("{", idx)
    if brace == -1:
        return {}, {}
    try:
        data, _ = json.JSONDecoder().raw_decode(page_html[brace:])
    except (ValueError, json.JSONDecodeError):
        return {}, {}
    loader = data.get("loaderData") if isinstance(data, dict) else None
    if not isinstance(loader, dict):
        return {}, {}
    for route_data in loader.values():
        if not isinstance(route_data, dict):
            continue
        series_detail = route_data.get("seriesDetail")
        if isinstance(series_detail, dict) and series_detail.get("series_id"):
            seo = route_data.get("publicVideoSeo")
            return series_detail, (seo if isinstance(seo, dict) else {})
    return {}, {}


def _fetch_hongguo_fallback_stream(vid, *, referer="https://hongguoduanju.com/", timeout=15, opener=None):
    """POST /api/video/protected/fallback-play-info to get direct MP4 main_url."""
    if not vid:
        return ""
    api_url = "https://hongguoduanju.com/api/video/protected/fallback-play-info"
    payload_bytes = json.dumps({"item_id": str(vid)}).encode("utf-8")
    headers = {
        "User-Agent": DEFAULT_UA,
        "Referer": referer or "https://hongguoduanju.com/",
        "Origin": "https://hongguoduanju.com",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if opener is not None or _urllib_is_mocked():
        req = urllib.request.Request(api_url, data=payload_bytes, headers=headers, method="POST")
        open_fn = opener or urllib.request.urlopen
        with open_fn(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        return _unescape_url((body or {}).get("main_url") or "")

    for attempt in range(4):
        if attempt > 0:
            time.sleep(0.35 * attempt)
        try:
            from curl_cffi import requests as curl_requests
            resp = curl_requests.post(
                api_url,
                data=payload_bytes,
                headers=headers,
                impersonate="chrome",
                timeout=timeout,
            )
            if resp.status_code < 400 and resp.text:
                body = resp.json()
                main_url = _unescape_url((body or {}).get("main_url") or "")
                if main_url:
                    return main_url
        except Exception:
            pass
        try:
            import requests
            resp = requests.post(api_url, data=payload_bytes, headers=headers, timeout=timeout)
            if resp.status_code < 400 and resp.text:
                body = resp.json()
                main_url = _unescape_url((body or {}).get("main_url") or "")
                if main_url:
                    return main_url
        except Exception:
            pass
    return ""


def _hongguo_media_info(url, page_html="", final_url="", opener=None, timeout=15):
    series_id, episode_id = hongguo_play_ids(url)
    if not series_id and not episode_id and final_url and final_url != url:
        series_id, episode_id = hongguo_play_ids(final_url)
    series_detail, seo = _parse_hongguo_router_data(page_html)
    if series_detail and series_detail.get("series_id"):
        _HONGGUO_SERIES_CACHE[str(series_detail["series_id"])] = series_detail
    elif series_id and series_id in _HONGGUO_SERIES_CACHE:
        series_detail = _HONGGUO_SERIES_CACHE[series_id]
    elif series_id and not page_html and opener is None and not _urllib_is_mocked():
        try:
            detail_html, _ = fetch_text(
                f"https://hongguoduanju.com/detail?series_id={series_id}",
                timeout=timeout,
            )
            series_detail, seo = _parse_hongguo_router_data(detail_html)
            if series_detail and series_detail.get("series_id"):
                _HONGGUO_SERIES_CACHE[str(series_detail["series_id"])] = series_detail
        except Exception:
            pass
    if not series_detail and not seo:
        return None
    series_name = str(series_detail.get("series_name") or "").strip()
    vids = [str(v) for v in (series_detail.get("vid_list") or ()) if v]
    if not episode_id:
        episode_id = str(seo.get("itemId") or (vids[0] if vids else "")).strip()
    if not episode_id:
        return None
    ep_num = (vids.index(episode_id) + 1) if episode_id in vids else 1
    stream_url = _fetch_hongguo_fallback_stream(
        episode_id,
        referer=final_url or url,
        timeout=timeout,
        opener=opener,
    )
    if not stream_url:
        return None
    ep_title = f"{series_name} E{ep_num}" if series_name else episode_id
    prefix = f"EP{ep_num:02d}_ {series_name}" if series_name else ""
    return {
        "id": episode_id,
        "title": ep_title,
        "description": "",
        "uploader": series_name or "hongguoduanju.com",
        "duration": seo.get("durationSeconds"),
        "series": series_name,
        "episode_number": ep_num,
        "filename_prefix": prefix,
        "media": [("video", stream_url)],
    }


def _walk_json(obj, visit):
    if isinstance(obj, dict):
        visit(obj)
        for value in obj.values():
            _walk_json(value, visit)
    elif isinstance(obj, list):
        for value in obj:
            _walk_json(value, visit)


def _parse_sjs_blobs(html):
    blobs = []
    for raw in _SJS_RE.findall(html or ""):
        try:
            blobs.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blobs


def _ig_caption(node):
    caption = node.get("caption")
    if isinstance(caption, dict):
        return str(caption.get("text") or "").strip()
    if isinstance(caption, str):
        return caption.strip()
    edges = ((node.get("edge_media_to_caption") or {}).get("edges") or [])
    if edges and isinstance(edges[0], dict):
        return str(((edges[0].get("node") or {}).get("text")) or "").strip()
    return ""


def _ig_best_url(versions, key="url"):
    ranked = []
    for item in versions or []:
        if not isinstance(item, dict) or not item.get(key):
            continue
        ranked.append((int(item.get("width") or item.get("height") or 0), item[key]))
    if not ranked:
        return ""
    ranked.sort(reverse=True)
    return ranked[0][1]


def _ig_post_url(node, username=""):
    code = str(node.get("code") or node.get("shortcode") or "").strip()
    if not code:
        return ""
    product = str(node.get("product_type") or "").lower()
    kind = "reel" if product in ("clips", "clips_home", "igtv") or node.get("media_type") == 2 else "p"
    if node.get("is_video") is True and kind == "p" and product in ("", "feed"):
        kind = "reel" if product == "clips" else "p"
    if username and kind == "p" and product == "clips":
        kind = "reel"
    return f"https://www.instagram.com/{kind}/{code}/"


def _ig_connection_nodes(html, key):
    """Media nodes from one profile connection (timeline or the Reels tab)."""
    nodes = []
    seen = set()

    def visit(obj):
        conn = obj.get(key)
        if not isinstance(conn, dict):
            return
        for edge in conn.get("edges") or []:
            node = (edge or {}).get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict):
                continue
            code = str(node.get("code") or node.get("shortcode") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            nodes.append(node)

    for blob in _parse_sjs_blobs(html):
        _walk_json(blob, visit)
    return nodes


def _ig_timeline_nodes(html):
    return _ig_connection_nodes(html, "polaris_ordered_timeline_connection")


_IG_REELS_QUERY_NAME = "PolarisLoggedOutDesktopWWWProfileReelsTabContentQuery"
_IG_REELS_DOC_ID = "27838951732404191"
_IG_WEB_APP_ID = "936619743392459"
_IG_REELS_PAGE_CAP = 40


def _ig_lsd(html):
    match = re.search(r'"lsd"\s*:\s*"([^"]+)"', html or "")
    return match.group(1) if match else ""


def _ig_reels_doc_id(html):
    match = re.search(
        r'"queryID"\s*:\s*"(\d+)"\s*,\s*"variables"\s*:\s*\{[^}]*\}\s*,\s*"queryName"\s*:\s*"'
        + re.escape(_IG_REELS_QUERY_NAME) + '"',
        html or "",
    )
    if match:
        return match.group(1)
    match = re.search(
        r'"queryName"\s*:\s*"' + re.escape(_IG_REELS_QUERY_NAME) + r'"[^}]{0,200}"queryID"\s*:\s*"(\d+)"',
        html or "",
    )
    return match.group(1) if match else _IG_REELS_DOC_ID


def _ig_clips_page_info(html):
    found = {}

    def visit(obj):
        conn = obj.get("polaris_clips_connection")
        if isinstance(conn, dict) and isinstance(conn.get("page_info"), dict):
            found.update(conn["page_info"])

    for blob in _parse_sjs_blobs(html or ""):
        _walk_json(blob, visit)
    return found


def _ig_clips_connection(payload):
    found = {}

    def visit(obj):
        conn = obj.get("polaris_clips_connection")
        if isinstance(conn, dict) and conn.get("edges"):
            found["conn"] = conn

    _walk_json(payload, visit)
    return found.get("conn") or {}


def _ig_reels_query(session, username, cursor, lsd, doc_id, timeout=20):
    """Next page of a profile's Reels tab."""
    variables = json.dumps({
        "after": cursor,
        "first": 12,
        "username": username,
    }, separators=(",", ":"))
    csrf = ""
    jar = getattr(session, "cookies", None)
    if jar is not None:
        try:
            csrf = jar.get("csrftoken") or ""
        except Exception:
            csrf = ""
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-FB-LSD": lsd,
        "X-IG-App-ID": _IG_WEB_APP_ID,
        "X-FB-Friendly-Name": _IG_REELS_QUERY_NAME,
        "Referer": f"https://www.instagram.com/{username}/reels/",
    }
    if csrf:
        headers["X-CSRFToken"] = csrf
    try:
        response = session.post(
            "https://www.instagram.com/graphql/query",
            data={
                "lsd": lsd,
                "fb_api_req_friendly_name": _IG_REELS_QUERY_NAME,
                "variables": variables,
                "doc_id": doc_id,
            },
            headers=headers,
            impersonate="chrome",
            timeout=timeout,
        )
    except Exception:
        return {}
    if response.status_code >= 400 or not (response.text or "").startswith("{"):
        return {}
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _ig_append_clips(nodes, seen, conn):
    added = []
    for edge in (conn or {}).get("edges") or []:
        node = (edge or {}).get("node") if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            continue
        code = str(node.get("code") or node.get("shortcode") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        nodes.append(node)
        added.append(node)
    return added


def _ig_all_reels(username, html, nodes, *, timeout=20):
    """Follow the Reels tab cursor until Instagram says there is no next page."""
    info = _ig_clips_page_info(html)
    cursor = str(info.get("end_cursor") or "")
    if not info.get("has_next_page") or not cursor:
        return nodes
    lsd = _ig_lsd(html)
    doc_id = _ig_reels_doc_id(html)
    if not lsd or not doc_id:
        return nodes
    try:
        from curl_cffi import requests as curl_requests
        session = curl_requests.Session()
        warmed = session.get(
            f"https://www.instagram.com/{username}/reels/",
            impersonate="chrome",
            timeout=timeout,
        )
    except Exception:
        return nodes
    warmed_html = warmed.text or ""
    if warmed_html:
        html = warmed_html
        fresh = _ig_feed_nodes(html, videos_only=True)
        if fresh:
            nodes[:] = fresh
        info = _ig_clips_page_info(html)
        cursor = str(info.get("end_cursor") or "")
        lsd = _ig_lsd(html)
        doc_id = _ig_reels_doc_id(html)
        if not info.get("has_next_page") or not cursor or not lsd or not doc_id:
            return nodes
    seen = {
        str(node.get("code") or node.get("shortcode") or "")
        for node in nodes
    }
    seen.discard("")
    for _page in range(_IG_REELS_PAGE_CAP):
        payload = _ig_reels_query(session, username, cursor, lsd, doc_id, timeout=timeout)
        conn = _ig_clips_connection(payload)
        if not conn:
            break
        added = _ig_append_clips(nodes, seen, conn)
        page = conn.get("page_info") if isinstance(conn.get("page_info"), dict) else {}
        next_cursor = str(page.get("end_cursor") or "")
        if not added or not page.get("has_next_page") or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return nodes


def _ig_caption_for_code(html, code):
    """Caption that belongs to this shortcode, not a suggested reel beside it."""
    found = []

    def visit(obj):
        node_code = str(obj.get("code") or obj.get("shortcode") or "").strip()
        if node_code != code:
            return
        caption = _ig_caption(obj)
        if caption:
            found.append(caption)

    for blob in _parse_sjs_blobs(html or ""):
        _walk_json(blob, visit)
    return found[0] if found else ""


def instagram_caption(url, *, opener=None, timeout=20):
    """Caption text from a reel or post page."""
    from app.core.scrape import looks_like_view_count

    code = instagram_shortcode(url)
    if not code:
        return ""
    pages = [
        f"https://www.instagram.com/reel/{code}/",
        f"https://www.instagram.com/p/{code}/",
    ]
    for page_url in pages:
        try:
            html, _final = fetch_text(page_url, timeout=timeout, opener=opener)
        except Exception:
            continue
        caption = _ig_caption_for_code(html, code)
        if caption and caption != code and not looks_like_view_count(caption):
            return caption
    return ""


def fill_instagram_captions(entries, *, opener=None, timeout=20):
    """Replace missing titles and view-count labels with the post caption."""
    from app.core.scrape import looks_like_view_count

    pending = []
    for entry in entries or []:
        url = entry.get("url") or ""
        if "instagram.com" not in url or not instagram_shortcode(url):
            continue
        title = (entry.get("title") or "").strip()
        code = instagram_shortcode(url)
        if title and title != code and not looks_like_view_count(title):
            continue
        pending.append(entry)
    if not pending:
        return entries

    def fill(entry):
        caption = instagram_caption(entry.get("url") or "", opener=opener, timeout=timeout)
        if not caption:
            return
        entry["title"] = caption
        entry["description"] = caption

    workers = min(6, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fill, pending))
    return entries


def _ig_feed_nodes(html, *, videos_only=False):
    """Reels tab pages list clips in polaris_clips_connection, not the timeline."""
    if videos_only:
        clips = _ig_connection_nodes(html, "polaris_clips_connection")
        if clips:
            return clips
    return _ig_timeline_nodes(html)


def _ig_media_from_html(html):
    videos = []
    images = []
    title = ""
    uploader = ""
    duration = None

    def visit(obj):
        nonlocal title, uploader, duration
        versions = obj.get("video_versions")
        if versions:
            url = _ig_best_url(versions)
            if url:
                videos.append(url)
        if obj.get("video_url"):
            videos.append(str(obj["video_url"]))
        candidates = ((obj.get("image_versions2") or {}).get("candidates")) or []
        image = _ig_best_url(candidates) or obj.get("display_uri") or obj.get("display_url")
        if image:
            images.append(str(image))
        caption = _ig_caption(obj)
        if caption and not title:
            title = caption
        user = obj.get("user") if isinstance(obj.get("user"), dict) else {}
        if user.get("username") and not uploader:
            uploader = str(user["username"])
        raw_dur = obj.get("video_duration") or obj.get("duration")
        if duration is None and raw_dur not in (None, ""):
            try:
                duration = round(float(raw_dur), 2)
            except (TypeError, ValueError):
                pass
        for item in obj.get("carousel_media") or []:
            if isinstance(item, dict):
                visit(item)

    for blob in _parse_sjs_blobs(html):
        _walk_json(blob, visit)
    return videos, images, title, uploader, duration


def _ig_profile_nodes_from_api(username, *, opener=None, timeout=20):
    if not username:
        return [], ""
    try:
        body, _final = fetch_text(
            f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}",
            headers={
                "User-Agent": _IG_ANDROID_UA,
                "X-IG-App-ID": _IG_ANDROID_APP_ID,
                "Accept": "*/*",
            },
            timeout=timeout,
            opener=opener,
        )
        data = json.loads(body)
    except Exception:
        return [], ""
    user = ((data.get("data") or {}).get("user") or {})
    uploader = str(user.get("username") or username)
    nodes = []
    for edge in ((user.get("edge_owner_to_timeline_media") or {}).get("edges") or []):
        node = (edge or {}).get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict):
            nodes.append(node)
    return nodes, uploader


def _ig_entries_from_nodes(nodes, username, *, videos_only=False):
    entries = []
    seen = set()
    for node in nodes:
        url = _ig_post_url(node, username)
        if not url or url in seen:
            continue
        is_video = (
            node.get("is_video") is True
            or node.get("media_type") == 2
            or str(node.get("product_type") or "").lower() in ("clips", "clips_home", "igtv")
        )
        if videos_only and not is_video:
            continue
        seen.add(url)
        code = str(node.get("code") or node.get("shortcode") or "").strip()
        caption = _ig_caption(node)
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        uploader = str(user.get("username") or username or "")
        entries.append({
            "url": url,
            "id": code,
            "title": caption or code,
            "description": caption,
            "uploader": uploader,
            "platform": "instagram",
            "webpage_url_domain": "instagram.com",
        })
    return entries


def _instagram_feed_entries(url, *, opener=None, timeout=20):
    username = instagram_username(url)
    if not username:
        return []
    videos_only = "/reels/" in (urlparse(url).path or "").lower()
    nodes = []
    pages = [url, f"https://www.instagram.com/{username}/"]
    if videos_only:
        pages.insert(1, f"https://www.instagram.com/{username}/reels/")
    seen_html = set()
    html = ""
    for page_url in pages:
        if page_url in seen_html:
            continue
        seen_html.add(page_url)
        try:
            html, _final = fetch_text(page_url, timeout=timeout, opener=opener)
        except Exception:
            html = ""
            continue
        nodes.extend(_ig_feed_nodes(html, videos_only=videos_only))
        if nodes:
            break
    if videos_only and nodes and opener is None and html:
        nodes = _ig_all_reels(username, html, nodes, timeout=timeout)
    uploader = username
    if not nodes:
        api_nodes, api_name = _ig_profile_nodes_from_api(
            username, opener=opener, timeout=timeout,
        )
        nodes = api_nodes
        uploader = api_name or username
    entries = _ig_entries_from_nodes(nodes, uploader, videos_only=videos_only)
    if videos_only and entries:
        fill_instagram_captions(entries, opener=opener, timeout=timeout)
    return entries


def _instagram_media_info(url, *, opener=None, timeout=20):
    short = instagram_shortcode(url)
    if not short:
        return None
    pages = [
        url,
        f"https://www.instagram.com/p/{short}/",
        f"https://www.instagram.com/reel/{short}/",
    ]
    videos, images, title, uploader, duration = [], [], "", "", None
    seen = set()
    for page_url in pages:
        if page_url in seen:
            continue
        seen.add(page_url)
        try:
            html, _final = fetch_text(page_url, timeout=timeout, opener=opener)
        except Exception:
            continue
        videos, images, title, uploader, duration = _ig_media_from_html(html)
        matched = _ig_caption_for_code(html, short)
        if matched:
            title = matched
        if videos or images:
            break
    media = []
    used = set()
    for stream in videos:
        if stream in used:
            continue
        used.add(stream)
        media.append(("video", stream))
    if not media:
        for image in images:
            if image in used:
                continue
            used.add(image)
            media.append(("image", image))
    if not media:
        return None
    caption = title if title and title != short else ""
    return {
        "id": short,
        "title": title or short,
        "description": title,
        "uploader": uploader or "",
        "duration": duration,
        "filename_prefix": caption,
        "media": media,
    }


def extract_web_media(url, *, opener=None, timeout=20):
    """Inspect a URL using fallback HTTP libraries and return media streams + metadata."""
    platform = detect_platform(url)
    if is_scraped_media_url(url):
        kind = _media_kind_for_url(url)
        name = os.path.splitext(os.path.basename(urlparse(url).path))[0] or "media"
        return {
            "id": name[:64],
            "title": name,
            "description": "",
            "uploader": urlparse(url).netloc.removeprefix("www."),
            "media": [(kind, url)],
        }

    # Fast path for Hongguo / DramaBox episode URLs when series metadata is already cached
    if platform == "hongguo" and opener is None and not _urllib_is_mocked():
        hg_series_id, hg_ep_id = hongguo_play_ids(url)
        if hg_series_id and hg_ep_id:
            hg_fast = _hongguo_media_info(url, opener=opener, timeout=timeout)
            if hg_fast:
                return hg_fast
    if platform == "dramabox" and opener is None and not _urllib_is_mocked():
        db_book_id, db_chap_id = dramabox_play_ids(url)
        if db_book_id and db_chap_id and db_book_id in _DRAMABOX_SERIES_CACHE:
            db_fast = _dramabox_media_info(url, opener=opener, timeout=timeout)
            if db_fast:
                return db_fast
    if platform == "goodshort" and opener is None and not _urllib_is_mocked():
        gs_slug, gs_chap = goodshort_play_ids(url)
        gs_book_id = gs_slug.split("-")[-1] if gs_slug else ""
        if gs_book_id and gs_chap and gs_book_id in _GOODSHORT_SERIES_CACHE:
            gs_fast = _goodshort_media_info(url, opener=opener, timeout=timeout)
            if gs_fast:
                return gs_fast
    if platform == "flickreels" and opener is None and not _urllib_is_mocked():
        fr_playlet_id, fr_ep_slug = flickreels_play_ids(url)
        if fr_playlet_id and fr_ep_slug and fr_playlet_id in _FLICKREELS_SERIES_CACHE:
            fr_fast = _flickreels_media_info(url, final_url=url)
            if fr_fast:
                return fr_fast
    if platform == "instagram" and instagram_shortcode(url):
        ig = _instagram_media_info(url, opener=opener, timeout=timeout)
        if ig:
            return ig

    # Suno direct UUID can be resolved even before network if network is unreachable,
    # but try fetching the page first for the real song title and /s/ short-link redirect.
    page_html, final_url = "", url
    try:
        page_html, final_url = fetch_text(url, timeout=timeout, opener=opener)
    except Exception:
        if platform == "suno":
            suno = _suno_media_info(url)
            if suno:
                return suno
        return None

    if platform == "suno":
        suno = _suno_media_info(url, page_html, final_url)
        if suno:
            return suno

    if platform == "hongguo":
        hg = _hongguo_media_info(url, page_html, final_url, opener=opener, timeout=timeout)
        if hg:
            return hg
        # If this is a real Hongguo SSR page, never fall through to cover-image scraping.
        if "_ROUTER_DATA" in (page_html or ""):
            return None

    if platform == "dramabox":
        db = _dramabox_media_info(url, page_html, final_url, opener=opener, timeout=timeout)
        if db:
            return db
        if "__NEXT_DATA__" in (page_html or ""):
            return None

    if platform == "goodshort":
        gs = _goodshort_media_info(url, page_html, final_url, opener=opener, timeout=timeout)
        if gs:
            return gs
        if "window.__INITIAL_STATE__=" in (page_html or ""):
            return None

    if platform == "flickreels":
        fr = _flickreels_media_info(url, page_html, final_url)
        if fr:
            return fr
        if "ShallowReactive" in (page_html or ""):
            return None

    if platform == "instagram":
        ig = _instagram_media_info(url, opener=opener, timeout=timeout)
        if ig:
            return ig

    meta = _parse_meta_tags(page_html)
    title_match = _TITLE_TAG_RE.search(page_html or "")
    raw_title = (
        meta.get("og:title")
        or meta.get("twitter:title")
        or (_html.unescape(_TAG_STRIP_RE.sub("", title_match.group(1))).strip() if title_match else "")
    )
    description = meta.get("og:description") or meta.get("twitter:description") or meta.get("description") or ""
    uploader = meta.get("og:site_name") or urlparse(final_url).netloc.removeprefix("www.")

    streams = []
    images = []
    json_titles = []

    for key in ("og:video:secure_url", "og:video", "og:video:url", "twitter:player:stream", "og:audio"):
        if meta.get(key):
            streams.append(urljoin(final_url, _unescape_url(meta[key])))

    for key in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        if meta.get(key):
            images.append(urljoin(final_url, _unescape_url(meta[key])))

    for match in _VIDEO_SRC_RE.finditer(page_html or ""):
        candidate = urljoin(final_url, _unescape_url(match.group(1)))
        if candidate.startswith(("http://", "https://")):
            streams.append(candidate)

    for block in _SCRIPT_JSON_RE.findall(page_html or ""):
        text = block.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        _walk_json_media(parsed, final_url, streams, images, json_titles)

    for match in _STREAM_URL_RE.finditer(page_html or ""):
        candidate = _unescape_url(match.group(0))
        if candidate.startswith(("http://", "https://")):
            streams.append(candidate)

    if not images:
        for match in _IMAGE_URL_RE.finditer(page_html or ""):
            candidate = _unescape_url(match.group(0))
            if candidate.startswith(("http://", "https://")) and not any(
                skip in candidate.lower() for skip in ("avatar", "logo", "favicon", "icon", "sprite")
            ):
                images.append(candidate)

    if not raw_title and json_titles:
        raw_title = json_titles[0]

    media = []
    seen = set()
    # Prefer .mp4/.m3u8/.mp3 streams first, then images
    for stream_url in streams:
        if stream_url in seen:
            continue
        lower = stream_url.lower()
        if any(lower.endswith(ext) for ext in (".html", ".htm", ".js", ".css", ".json", ".xml")):
            continue
        seen.add(stream_url)
        media.append((_media_kind_for_url(stream_url), stream_url))

    for img_url in images:
        if img_url in seen:
            continue
        seen.add(img_url)
        media.append(("image", img_url))

    if not media and not raw_title:
        return None

    segments = [s for s in urlparse(final_url).path.split("/") if s]
    item_id = segments[-1] if segments else urlparse(final_url).netloc
    return {
        "id": item_id[:64],
        "title": raw_title or item_id,
        "description": description,
        "uploader": uploader,
        "media": media,
    }


def extract_web_feed(url, *, opener=None, timeout=20):
    """Extract episode / playlist URLs from a drama series or Suno playlist page."""
    platform = detect_platform(url)
    if platform == "instagram":
        return _instagram_feed_entries(url, opener=opener, timeout=timeout)
    try:
        page_html, final_url = fetch_text(url, timeout=timeout, opener=opener)
    except Exception:
        return []

    meta = _parse_meta_tags(page_html)
    title_match = _TITLE_TAG_RE.search(page_html or "")
    series_title = (
        meta.get("og:title")
        or meta.get("twitter:title")
        or (_html.unescape(_TAG_STRIP_RE.sub("", title_match.group(1))).strip() if title_match else "")
    )
    host = urlparse(final_url).netloc.lower().removeprefix("www.")

    if platform == "suno":
        seen = set()
        entries = []
        for match in _SUNO_UUID_RE.finditer(page_html or ""):
            uuid = match.group(1).lower()
            if uuid in seen or uuid in final_url.lower():
                continue
            seen.add(uuid)
            song_url = f"https://suno.com/song/{uuid}"
            entries.append({
                "url": song_url,
                "id": uuid,
                "title": f"{series_title or 'SUNO'} - {uuid[:8]}",
                "uploader": "SUNO",
                "platform": "suno",
                "webpage_url_domain": "suno.com",
            })
        return entries

    if platform == "hongguo":
        series_detail, _seo = _parse_hongguo_router_data(page_html)
        if series_detail:
            series_id = str(series_detail.get("series_id") or "").strip()
            series_name = str(series_detail.get("series_name") or "").strip() or series_title or series_id
            vids = [str(v) for v in (series_detail.get("vid_list") or ()) if v]
            if series_id and vids:
                series_url = f"https://hongguoduanju.com/detail?series_id={series_id}"
                return [
                    {
                        "url": f"https://hongguoduanju.com/player/{series_id}/{vid}",
                        "id": vid,
                        "title": f"{series_name} E{index}",
                        "description": "",
                        "uploader": series_name,
                        "platform": "hongguo",
                        "webpage_url_domain": "hongguoduanju.com",
                        "series": series_name,
                        "series_url": series_url,
                    }
                    for index, vid in enumerate(vids, start=1)
                ]

    if platform == "dramabox":
        book_info, chapters, _chap_id, _free_src = _parse_dramabox_next_data(page_html)
        if book_info and chapters:
            book_id = str(book_info.get("bookId") or "").strip()
            book_name = str(book_info.get("bookName") or "").strip() or series_title or book_id
            slug = str(book_info.get("bookNameLower") or "").strip()
            series_url = (
                f"https://www.dramaboxdb.com/movie/{book_id}/{slug}"
                if slug
                else f"https://www.dramaboxdb.com/movie/{book_id}"
            )
            entries = []
            for index, ch in enumerate(chapters, start=1):
                if not isinstance(ch, dict) or not ch.get("id"):
                    continue
                chap_id = str(ch["id"]).strip()
                raw_dur = ch.get("duration")
                dur = None
                if raw_dur not in (None, ""):
                    try:
                        val = float(raw_dur)
                        dur = round(val / 1000.0, 2) if val > 1000 else round(val, 2)
                    except (TypeError, ValueError):
                        dur = None
                ep_path = f"{book_id}_{slug}" if slug else book_id
                entries.append({
                    "url": f"https://www.dramaboxdb.com/ep/{ep_path}/{chap_id}_Episode-{index}",
                    "id": chap_id,
                    "title": f"{book_name} E{index}",
                    "description": "",
                    "uploader": book_name,
                    "duration": dur,
                    "platform": "dramabox",
                    "webpage_url_domain": "dramaboxdb.com",
                    "series": book_name,
                    "series_url": series_url,
                })
            if entries:
                return entries

    if platform == "goodshort":
        slug, _chap = goodshort_play_ids(final_url or url)
        book_info, chapters, _cur = _parse_goodshort_initial_state(page_html)
        if book_info and chapters:
            book_id = str(book_info.get("bookId") or "").strip()
            book_name = str(book_info.get("bookName") or "").strip() or series_title or slug
            series_slug = slug or book_id
            # If the /drama/ page only had the first 11 chapters, fetch the first episode page
            # which carries the full chapterList in BookRead.chapterList.
            if len(chapters) <= 15 and chapters[0].get("id") and opener is None and not _urllib_is_mocked():
                first_id = str(chapters[0]["id"])
                first_name = str(chapters[0].get("chapterName") or "001")
                try:
                    ep1_html, _ = fetch_text(
                        f"https://www.goodshort.com/episode/{series_slug}/{first_name}-{first_id}",
                        timeout=timeout,
                    )
                    _bi2, full_chapters, _c2 = _parse_goodshort_initial_state(ep1_html)
                    if len(full_chapters) > len(chapters):
                        chapters = full_chapters
                        if book_id:
                            _GOODSHORT_SERIES_CACHE[book_id] = (book_info, chapters)
                except Exception:
                    pass
            series_url = f"https://www.goodshort.com/drama/{series_slug}"
            unlocked = [
                ch for ch in chapters
                if isinstance(ch, dict) and ch.get("id") and ch.get("m3u8Path")
            ]
            active_chapters = unlocked if unlocked else chapters
            entries = []
            for index, ch in enumerate(active_chapters, start=1):
                if not isinstance(ch, dict) or not ch.get("id"):
                    continue
                chap_id = str(ch["id"]).strip()
                chap_name = str(ch.get("chapterName") or f"{index:03d}").strip()
                entries.append({
                    "url": f"https://www.goodshort.com/episode/{series_slug}/{chap_name}-{chap_id}",
                    "id": chap_id,
                    "title": f"{book_name} E{index}",
                    "description": "",
                    "uploader": book_name,
                    "platform": "goodshort",
                    "webpage_url_domain": "goodshort.com",
                    "series": book_name,
                    "series_url": series_url,
                })
            if entries:
                return entries

    if platform == "flickreels":
        series_info, chapters, _stream = _parse_flickreels_nuxt_data(page_html)
        if not chapters:
            pid_hint, _ = flickreels_play_ids(final_url or url)
            if pid_hint:
                series_info, chapters = _fetch_flickreels_chapter_list(pid_hint, timeout=timeout)
        if series_info and chapters:
            playlet_id = str(series_info.get("playlet_id") or "").strip()
            series_name = str(series_info.get("title") or "").strip() or series_title or playlet_id
            segs = [s for s in urlparse(final_url or url).path.split("/") if s]
            slug = (
                segs[1]
                if len(segs) >= 3 and segs[0].lower() == "playlist"
                else re.sub(r"[^a-z0-9]+", "-", series_name.lower()).strip("-")
            )
            series_url = f"https://www.flickreels.net/episodes-list/{slug}-{playlet_id}"
            if isinstance(series_info.get("collection"), str) and series_info["collection"].startswith("wbc"):
                series_info["collection"] = _decrypt_flickreels_wbc(series_info["collection"])
            entries = []
            coll = series_info.get("collection") if series_info.get("has_collection") else None
            if isinstance(coll, dict) and (coll.get("chapter_id") or coll.get("hls_url")):
                coll_dur = None
                if coll.get("duration") not in (None, ""):
                    try:
                        coll_dur = float(coll["duration"])
                    except (TypeError, ValueError):
                        coll_dur = None
                entries.append({
                    "url": f"https://www.flickreels.net/playlist/{slug}/{playlet_id}/full-movie",
                    "id": str(coll.get("chapter_id") or f"{playlet_id}-full-movie"),
                    "title": f"{series_name} (Full Movie)",
                    "description": "",
                    "uploader": series_name,
                    "duration": coll_dur,
                    "platform": "flickreels",
                    "webpage_url_domain": "flickreels.net",
                    "series": series_name,
                    "series_url": series_url,
                })
            for index, ch in enumerate(chapters, start=1):
                if not isinstance(ch, dict):
                    continue
                ep_num = int(ch.get("chapter_num") or index)
                chap_id = str(ch.get("chapter_id") or f"ep-{ep_num}").strip()
                dur = None
                if ch.get("duration") not in (None, ""):
                    try:
                        dur = float(ch["duration"])
                    except (TypeError, ValueError):
                        dur = None
                entries.append({
                    "url": f"https://www.flickreels.net/playlist/{slug}/{playlet_id}/episode-{ep_num}",
                    "id": chap_id,
                    "title": f"{series_name} E{ep_num}",
                    "description": "",
                    "uploader": series_name,
                    "duration": dur,
                    "platform": "flickreels",
                    "webpage_url_domain": "flickreels.net",
                    "series": series_name,
                    "series_url": series_url,
                })
            if entries:
                return entries

    entries = []
    seen_urls = set()
    for href, inner in _HREF_RE.findall(page_html or ""):
        full = urljoin(final_url, _unescape_url(href))
        parts = urlparse(full)
        link_host = parts.netloc.lower().removeprefix("www.")
        if link_host != host or full == final_url or full in seen_urls:
            continue
        if not _EPISODE_HREF_RE.search(full):
            continue
        seen_urls.add(full)
        label = _html.unescape(_TAG_STRIP_RE.sub(" ", inner)).strip()
        label = re.sub(r"\s+", " ", label)
        segs = [s for s in parts.path.split("/") if s]
        ep_id = segs[-1] if segs else str(len(entries) + 1)
        ep_title = label or f"{series_title} E{len(entries) + 1}".strip()
        if series_title and series_title.lower() not in ep_title.lower():
            ep_title = f"{series_title} {ep_title}".strip()
        entries.append({
            "url": full,
            "id": ep_id,
            "title": ep_title,
            "description": ep_title,
            "uploader": host,
            "platform": platform,
            "webpage_url_domain": host,
            "series": series_title,
            "series_url": final_url,
        })
    return entries


def _download_hls_with_ffmpeg(
    stream_url, dest_path, *, referer="", ffmpeg_location="", should_stop=None,
    gpu_accel="auto", workers=4,
):
    ffmpeg = resolve_ffmpeg(ffmpeg_location) or "ffmpeg"
    headers = f"User-Agent: {DEFAULT_UA}\r\n"
    if referer:
        headers += f"Referer: {referer}\r\n"
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel", "error",
        *ffmpeg_hwaccel_args(gpu_accel, workers=workers),
        "-headers", headers,
        "-i", stream_url,
        "-c", "copy",
        dest_path,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=_NO_WINDOW,
    )
    try:
        while proc.poll() is None:
            check_stop(should_stop)
            proc.stdout.readline()
        code = proc.wait()
    except StopRequested:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise
    finally:
        if proc.stdout:
            proc.stdout.close()
    return code == 0 and os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0


def apply_caption_filename(path, caption, item_id):
    """Rename an ``id.mp4`` save to ``Caption [id].mp4`` when a caption is known."""
    if not path or not os.path.isfile(path):
        return path or ""
    folder, name = os.path.split(path)
    base, ext = os.path.splitext(name)
    rid = re.sub(r'[\\/:*?"<>|]+', "_", str(item_id or "")).strip(" ._")
    stem = caption_file_stem(caption, item_id or rid)
    if not rid or stem == rid or base == stem:
        return path
    if base != rid and not base.endswith(f" [{rid}]"):
        return path
    dest = os.path.join(folder, stem + ext)
    if os.path.abspath(dest) == os.path.abspath(path) or os.path.exists(dest):
        return path
    os.replace(path, dest)
    return dest


def caption_file_stem(caption, item_id, limit=80):
    """``Caption [id]`` for a saved post, or just the id when there is no caption."""
    rid = re.sub(r'[\\/:*?"<>|]+', "_", str(item_id or "media")).strip(" ._") or "media"
    text = re.sub(r"\s+", " ", str(caption or "")).strip()
    text = re.sub(r'[\\/:*?"<>|]+', "_", text).strip(" ._")
    if text.lower() in ("", rid.lower(), "na", "none"):
        return rid
    if len(text) > limit:
        text = text[:limit].rstrip(" ._")
    if not text:
        return rid
    return f"{text} [{rid}]"


def download_with_fallback(
    url,
    output_dir,
    *,
    item_id="",
    archive_path="",
    ffmpeg_location="",
    log=None,
    on_progress=None,
    should_stop=None,
    media_kinds=None,
    opener=None,
    gpu_accel="auto",
    workers=4,
    caption="",
):
    """Download media for `url` using fallback libraries (curl_cffi / requests / urllib / ffmpeg)."""
    check_stop(should_stop)
    info = extract_web_media(url, opener=opener)
    if not info or not info.get("media"):
        return False

    kinds = set(media_kinds or ("video", "music", "image"))
    media = info["media"]
    has_video_or_music = any(kind in ("video", "music") for kind, _u in media)

    selected = []
    seen_kinds = set()
    for kind, media_url in media:
        if kind in seen_kinds:
            continue
        if kind == "video" and "video" in kinds:
            selected.append((kind, media_url))
            seen_kinds.add(kind)
        elif kind == "music" and ("music" in kinds or ("video" in kinds and not any(k == "video" for k, _ in media))):
            selected.append((kind, media_url))
            seen_kinds.add(kind)
        elif kind == "image" and ("image" in kinds or (not has_video_or_music and "video" in kinds)):
            if not has_video_or_music and selected:
                continue
            selected.append((kind, media_url))
            seen_kinds.add(kind)

    if not selected:
        return False

    os.makedirs(output_dir, exist_ok=True)
    rid = re.sub(r'[\\/:*?"<>|]+', "_", str(item_id or info.get("id") or "media")).strip(" ._") or "media"
    prefix_raw = caption or info.get("filename_prefix") or ""
    if not prefix_raw and detect_platform(url) == "instagram":
        candidate = info.get("description") or info.get("title") or ""
        if candidate and candidate not in (rid, info.get("id")):
            prefix_raw = candidate
    base_stem = caption_file_stem(prefix_raw, rid) if prefix_raw else rid
    saved = []

    for index, (kind, media_url) in enumerate(selected, start=1):
        check_stop(should_stop)
        ext = _ext_for_media_url(media_url, kind)
        suffix = "" if len(selected) == 1 else f"_{index}"
        dest = os.path.join(output_dir, f"{base_stem}{suffix}{ext}")
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            saved.append(dest)
            continue
        # Also skip if another file in output_dir already carries [rid].ext
        existing_match = next(
            (
                os.path.join(output_dir, name)
                for name in os.listdir(output_dir)
                if (f"[{rid}]{ext}" in name or name == f"{rid}{ext}")
                and os.path.isfile(os.path.join(output_dir, name))
                and os.path.getsize(os.path.join(output_dir, name)) > 0
            ),
            "",
        )
        if existing_match:
            saved.append(existing_match)
            continue

        lower_url = media_url.lower().split("?", 1)[0]
        if lower_url.endswith((".m3u8", ".mpd")):
            if _download_hls_with_ffmpeg(
                media_url,
                dest,
                referer=url,
                ffmpeg_location=ffmpeg_location,
                should_stop=should_stop,
                gpu_accel=gpu_accel,
                workers=workers,
            ):
                saved.append(dest)
                if on_progress:
                    on_progress(url, {"percent": 100.0, "filepath": dest})
            continue

        start_ts = time.monotonic()

        def _report_chunk(downloaded, total):
            if not on_progress:
                return
            elapsed = max(0.001, time.monotonic() - start_ts)
            speed = downloaded / elapsed
            eta = int(max(0.0, (total - downloaded) / speed)) if (total and speed > 0 and total > downloaded) else None
            pct = (downloaded * 100.0 / total) if total else None
            event = {
                "status": "downloading",
                "downloaded": downloaded,
                "total": total,
                "speed": speed,
                "eta": eta,
                "percent": pct,
            }
            if info.get("duration"):
                event["duration"] = info["duration"]
            on_progress(url, event)

        try:
            blob = fetch_bytes(media_url, referer=url, opener=opener, on_chunk=_report_chunk)
        except Exception:
            continue
        if not blob:
            continue
        head = blob.lstrip()[:64].lower()
        if head.startswith((b"<!doctype html", b"<html", b"<?xml")):
            continue
        with open(dest, "wb") as handle:
            handle.write(blob)
        saved.append(dest)
        if on_progress:
            dur, w, h = mp4_video_info(dest)
            dur = info.get("duration") or dur
            qual = resolution_label(w, h, dest)
            done_event = {
                "percent": 100.0,
                "total": len(blob),
                "filepath": dest,
            }
            if dur:
                done_event["duration"] = dur
                info["duration"] = dur
            if qual:
                done_event["quality"] = qual
                info["quality"] = qual
            on_progress(url, done_event)

    if not saved:
        return False

    platform = detect_platform(url)
    if log:
        log(f"[{rid}] saved {len(saved)} {platform} media file(s) via fallback library")
    if archive_path and rid:
        try:
            with open(archive_path, "a", encoding="utf-8") as handle:
                handle.write(f"{platform} {rid}\n")
        except OSError:
            pass
    if on_progress:
        first_file = saved[0]
        dur, w, h = mp4_video_info(first_file)
        final_dur = info.get("duration") or dur
        final_qual = info.get("quality") or resolution_label(w, h, first_file)
        try:
            final_size = os.path.getsize(first_file)
        except OSError:
            final_size = None
        summary = {
            "title": info.get("title") or rid,
            "description": info.get("description") or "",
            "uploader": info.get("uploader") or "",
            "filepath": first_file,
        }
        if final_size:
            summary["total"] = final_size
        if final_dur:
            summary["duration"] = final_dur
        if final_qual:
            summary["quality"] = final_qual
        on_progress(url, summary)
    return True
