"""Download reels with yt-dlp.

Two levels of parallelism, both tunable from the UI:
- several reels at the same time (a pool of yt-dlp processes)
- each reel split into fragments fetched concurrently (yt-dlp -N)
"""
import csv
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, timedelta
from urllib.parse import urlencode, urlparse

from app.core.cookies import readable_browser_cookie_spec
from app.core.jobs import StopRequested, check_stop
from app.core.platform_icons import platform_from_extractor
from app.core.runtime import (
    channel_state_dir,
    default_output_root,
    download_artifacts_dir,
    resolve_ffmpeg,
    yt_dlp_command_prefix,
)
from app.core.sysinfo import (
    DEFAULT_GPU_ACCEL,
    GPU_ACCEL_MODES,
    ffmpeg_postprocessor_arg,
    ffmpeg_threads_per_worker,
    recommended_concurrency,
    resolve_gpu_backend,
)
from app.core.urls import (
    MOVIE_DRAMA_PLATFORMS,
    WEB_FALLBACK_ONLY_PLATFORMS,
    bilibili_play_ids,
    detect_platform,
    dramabox_play_ids,
    goodshort_play_ids,
    is_bilibili_episode_url,
    is_bilibili_season_url,
    wetv_play_ids,
)
from app.core.web_media import download_with_fallback, resolution_label

DEFAULT_WORKERS, DEFAULT_FRAGMENTS = recommended_concurrency()

# Bilibili (and others) split video and audio; `best` is video-only there and fails.
# Bilibili and others may lack a merge pair; `/best` is the last resort.
FORMAT_SELECTOR = "bv*+ba/b/best"
# Twitter image tweets have no video+audio pair; keep merge first, then fall back.
TWITTER_FORMAT_SELECTOR = FORMAT_SELECTOR
PINTEREST_FORMAT_SELECTOR = TWITTER_FORMAT_SELECTOR
TWITTER_EXTRACTOR_ARGS = "twitter:api=syndication"
_TWITTER_STATUS_RE = re.compile(r"(?:^|/)status(?:es)?/(\d+)", re.I)
_PINTEREST_PIN_RE = re.compile(r"/pin/(?:[\w.-]+--)?(\d+)", re.I)
_PINTEREST_PWS = "www/[username].js"
_TWITTER_MEDIA_APIS = (
    "https://api.fxtwitter.com/status/{id}",
    "https://api.vxtwitter.com/Twitter/status/{id}",
)
_HTTP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

ALL_MEDIA_KINDS = frozenset({"video", "music", "image", "document"})
_WIN_ILLEGAL = re.compile(r'[\\/:*?"<>|]+')
_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}
_AUDIO_EXTS = {".m4a", ".mp3", ".opus", ".ogg", ".flac"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_DOCUMENT_EXTS = {".txt", ".json", ".srt", ".vtt", ".nfo", ".xml", ".description"}
_STAGING_EXTS = {".part", ".ytdl"}
_SIDECAR_NAMES = (".description", ".image", ".nfo", ".xml", ".ytdl")

# Built-in file name patterns (Settings → Download). Preset 2 is the default.
FILENAME_PRESETS = (
    ("title_id", "Title + ID", "%(title)s [%(id)s].%(ext)s"),
    ("caption", "Caption or title", "%(description,title,id).80B [%(id)s].%(ext)s"),
    ("id", "ID only", "%(id)s.%(ext)s"),
)
DEFAULT_FILENAME_PRESET = "caption"
OUTPUT_TEMPLATE = FILENAME_PRESETS[1][2]

DEFAULT_VIDEO_QUALITY = "best"
VIDEO_QUALITY_CHOICES = (
    ("best", "Best Quality (Auto High)"),
    ("1080p", "1080p (Full HD)"),
    ("720p", "720p (HD)"),
    ("480p", "480p (SD)"),
    ("360p", "360p (Data Saver)"),
)
_VIDEO_QUALITY_HEIGHTS = {
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}


def format_selector_for_quality(video_quality="", platform=""):
    """Return the yt-dlp -f selector for the chosen quality preset."""
    height = _VIDEO_QUALITY_HEIGHTS.get((video_quality or "").strip().lower())
    if height:
        return (
            f"bv*[height<={height}]+ba/b[height<={height}]/"
            f"{TWITTER_FORMAT_SELECTOR if platform in ('twitter', 'pinterest') else FORMAT_SELECTOR}"
        )
    if platform in ("twitter", "pinterest"):
        return TWITTER_FORMAT_SELECTOR
    return FORMAT_SELECTOR

# Machine-readable progress, so the UI never has to parse yt-dlp's console output.
PROGRESS_PREFIX = "@@P"
INFO_PREFIX = "@@I"
FILE_PREFIX = "@@F"
PROGRESS_TEMPLATE = "|".join(
    (
        PROGRESS_PREFIX,
        "%(progress.downloaded_bytes)s",
        "%(progress.total_bytes,progress.total_bytes_estimate)s",
        "%(progress.speed)s",
        "%(progress.eta)s",
    )
)
INFO_TEMPLATE = (
    INFO_PREFIX
    + "%(.{id,title,description,uploader,duration,width,height,ext,extractor_key,webpage_url_domain})j"
)
FILE_TEMPLATE = FILE_PREFIX + "%(filepath)j"

# A yt-dlp process per reel would flash a console window on Windows without this.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def read_urls(csv_path):
    """Return the reel URLs listed in csv_path, in order, without duplicates."""
    urls, seen = [], set()
    with open(csv_path, newline="") as f:
        for row in csv.reader(f):
            for cell in row:
                url = cell.strip()
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


def reel_id(url):
    """Short id used as the row label and as a unique suffix on the file name."""
    from urllib.parse import parse_qs, urlparse
    parts = urlparse(url)
    q = parse_qs(parts.query)
    query_id = (
        q.get("v")
        or q.get("modal_id")
        or q.get("series_id")
        or q.get("item_id")
        or [""]
    )[0]
    if query_id:
        return query_id
    db_book, db_chap = dramabox_play_ids(url)
    if db_chap or db_book:
        return db_chap or db_book
    gs_slug, gs_chap = goodshort_play_ids(url)
    if gs_chap or gs_slug:
        return gs_chap or gs_slug.split("-")[-1]
    segments = [s for s in parts.path.split("/") if s]
    if segments:
        return segments[-1]
    return url


def collapse_text(text):
    """Turn a caption into one line, dropping empty / NA placeholders."""
    if text in (None, "", "NA", "None", "none"):
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def post_label(title="", description="", rid=""):
    """Prefer the caption; fall back to the post title, then the reel id."""
    return collapse_text(description) or collapse_text(title) or rid or ""


def normalize_media_kinds(media_kinds=None):
    """Views keys (video/music/image/document); empty or None means all of them."""
    if not media_kinds:
        return ALL_MEDIA_KINDS
    return frozenset(media_kinds)


_PLACEHOLDER_FOLDER_NAMES = frozenset(
    {"", "default", "video", "untitled", "na", "none"}
)
_EPISODE_TITLE_RE = re.compile(
    r"^(?P<series>.+?)\s+(?P<ep>(?:E|EP|Episode|#)\s*\d+)\s*$",
    re.I,
)
_PREFIX_EPISODE_TITLE_RE = re.compile(
    r"^(?P<ep>(?:E|EP|Episode)\s*\d+)\s*[:\-–—]\s*(?P<series>.+?)\s*$",
    re.I,
)
_EPISODE_ONLY_RE = re.compile(r"^(?:E|EP|Episode|#)\s*\d+$", re.I)
_BILI_PLAY_EP_RE = re.compile(r"/play/(\d+)/(\d+)", re.I)


def _match_episode_title(title):
    text = collapse_text(title)
    if not text:
        return None
    return _EPISODE_TITLE_RE.match(text) or _PREFIX_EPISODE_TITLE_RE.match(text)


def source_folder_name(title="", description="", rid=""):
    """Windows-safe folder from caption, then title; else random hex (+ rid)."""
    text = collapse_text(description) or collapse_text(title)
    text = _WIN_ILLEGAL.sub(" ", text)
    text = collapse_text(text)
    text = text[:80].rstrip(" .")
    if text.lower() in _PLACEHOLDER_FOLDER_NAMES:
        text = ""
    if text:
        return text
    token = secrets.token_hex(4)
    suffix = _WIN_ILLEGAL.sub("", collapse_text(rid)).strip(" .")
    return f"{token}-{suffix}" if suffix else token


def _item_field(item, name):
    if isinstance(item, dict):
        return item.get(name) or ""
    return getattr(item, name, "") or ""


def series_folder_for_items(items):
    """Movie/series folder when items are episodes of one title; else empty.

    Prefers an explicit ``series`` field, a shared ``Series E1`` / ``EP01: Series``
    title, then a shared uploader for bilibili.tv / wetv.vip ``/play/{season}/{episode}``
    links, then the season page title.
    """
    rows = [item for item in (items or []) if item is not None]
    if not rows:
        return ""
    explicit_series = {
        collapse_text(_item_field(item, "series"))
        for item in rows
        if collapse_text(_item_field(item, "series"))
    }
    if len(explicit_series) == 1 and (len(rows) > 1 or _item_field(rows[0], "series_url")):
        return source_folder_name(next(iter(explicit_series)))
    titles = [collapse_text(_item_field(item, "title")) for item in rows]
    titled = [title for title in titles if title]
    uploaders = {
        collapse_text(_item_field(item, "uploader"))
        for item in rows
        if collapse_text(_item_field(item, "uploader"))
    }
    matches = [_match_episode_title(title) for title in titled]
    if titled and matches and all(matches):
        series_names = {match.group("series").strip() for match in matches}
        if len(series_names) == 1:
            return source_folder_name(next(iter(series_names)))
    if titled and all(_EPISODE_ONLY_RE.match(title) for title in titled) and len(uploaders) == 1:
        return source_folder_name(next(iter(uploaders)))
    seasons = set()
    season_pages = 0
    for item in rows:
        url = str(_item_field(item, "url") or "")
        if is_bilibili_season_url(url):
            season_pages += 1
        match = _BILI_PLAY_EP_RE.search(url)
        if match:
            seasons.add(match.group(1))
        elif is_bilibili_episode_url(url):
            season, _ep = bilibili_play_ids(url)
            if season:
                seasons.add(season)
        else:
            w_series, w_ep = wetv_play_ids(url)
            if w_series and w_ep:
                seasons.add(w_series)
            elif w_series and not w_ep:
                season_pages += 1
                seasons.add(w_series)
    if len(rows) == 1 and season_pages == 1:
        name = titled[0] if titled else (next(iter(uploaders)) if uploaders else "")
        return source_folder_name(name) if name else ""
    if len(seasons) != 1:
        return ""
    if len(uploaders) == 1:
        return source_folder_name(next(iter(uploaders)))
    if titled and len(set(titled)) == 1 and not _EPISODE_ONLY_RE.match(titled[0]):
        return source_folder_name(titled[0])
    return ""


def episode_leaf_name(title="", description="", rid="", series=""):
    """Per-episode folder under a series folder; prefer ``E1`` over full title."""
    series = collapse_text(series)
    if series:
        for candidate in (collapse_text(title), collapse_text(description)):
            if not candidate:
                continue
            match = _match_episode_title(candidate)
            if match and match.group("series").strip().lower() == series.lower():
                return source_folder_name(match.group("ep"))
            prefix = f"{series} "
            if candidate.lower().startswith(prefix.lower()) and len(candidate) > len(prefix):
                return source_folder_name(candidate[len(prefix):])
    text = collapse_text(title) if series else (collapse_text(description) or collapse_text(title))
    return source_folder_name(text, "", rid)


def is_series_package(item):
    """True for the parent movie/series row (not an episode)."""
    return collapse_text(_item_field(item, "package_kind")).lower() == "series"


def group_series_entries(entries, *, existing_urls=None):
    """Prepend a movie package row and tag episode rows for tree grouping.

    Used for bilibili.tv / WeTV / drama season extracts so Grabber shows
    ``Back as Immortal Lord`` → E1, E2, … instead of a flat list.
    """
    rows = [dict(item) if isinstance(item, dict) else {"url": item} for item in (entries or [])]
    rows = [row for row in rows if row.get("url")]
    if not rows:
        return rows
    episodes = [row for row in rows if not is_series_package(row)]
    if not episodes:
        return rows
    known = set(existing_urls or [])
    if len(episodes) < 2:
        ep = episodes[0]
        if not (ep.get("series") and ep.get("series_url")):
            url = str(ep.get("url") or "")
            season, episode = bilibili_play_ids(url)
            if not (season and episode):
                season, episode = wetv_play_ids(url)
            if season and episode:
                host = urlparse(url).netloc or "www.bilibili.tv"
                candidate_url = f"https://{host}/en/play/{season}"
                if candidate_url in known:
                    movie = series_folder_for_items(episodes)
                    if movie:
                        ep = dict(ep)
                        ep["series"] = movie
                        ep["series_url"] = candidate_url
                        return [ep]
            return rows
    movie = series_folder_for_items(episodes)
    if not movie:
        return rows
    explicit_urls = [
        collapse_text(row.get("series_url"))
        for row in episodes
        if collapse_text(row.get("series_url"))
    ]
    seasons = set()
    host = ""
    for row in episodes:
        url = str(row.get("url") or "")
        season, episode = bilibili_play_ids(url)
        if not (season and episode):
            season, episode = wetv_play_ids(url)
        if season and episode:
            seasons.add(season)
            if not host:
                host = urlparse(url).netloc or "www.bilibili.tv"
    if explicit_urls and len(set(explicit_urls)) == 1:
        season_url = explicit_urls[0]
        season_id = next(iter(seasons)) if len(seasons) == 1 else reel_id(season_url) or movie
    elif len(seasons) != 1:
        # Non-bili shared title prefix still groups under a synthetic series URL.
        season_url = f"series:{movie}"
        season_id = movie
    else:
        season_id = next(iter(seasons))
        host = host or "www.bilibili.tv"
        season_url = f"https://{host}/en/play/{season_id}"
    known = set(existing_urls or [])
    out = []
    if season_url not in known and not any(
        is_series_package(row) and (row.get("series_url") or row.get("url")) == season_url
        for row in rows
    ):
        platform = detect_platform(season_url) if "://" in season_url else (
            detect_platform(episodes[0].get("url") or "") or "bilibili"
        )
        out.append({
            "url": season_url,
            "id": season_id,
            "title": movie,
            "uploader": movie,
            "series": movie,
            "series_url": season_url,
            "package_kind": "series",
            "platform": platform,
            "status": "queued",
            "expanded": False,
        })
    for row in episodes:
        item = dict(row)
        item["series"] = movie
        item["series_url"] = season_url
        item.pop("package_kind", None)
        out.append(item)
    return out


def _is_absolute_path(path):
    """True for platform abs paths and Windows drive paths like ``D:\\pins``."""
    if os.path.isabs(path):
        return True
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        return True
    return False


def resolve_item_dir(output_dir, source_folder=""):
    """Join a relative caption folder, or keep an absolute Set-download-directory path."""
    if not source_folder:
        return output_dir
    if _is_absolute_path(source_folder):
        return source_folder
    return os.path.join(output_dir, source_folder)


def _kind_for_ext(ext):
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "music"
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _DOCUMENT_EXTS:
        return "document"
    return ""


def _kind_for_name(name):
    lowered = name.lower()
    if lowered.endswith(".info.json"):
        return "document"
    return _kind_for_ext(os.path.splitext(name)[1].lower())


def _is_system_sidecar(name):
    lowered = name.lower()
    if lowered.endswith(".info.json"):
        return True
    return lowered.endswith(_SIDECAR_NAMES)


def _unique_artifact_path(dest):
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(dest)
    for index in range(1, 1000):
        candidate = f"{base}-{index}{ext}"
        if not os.path.exists(candidate):
            return candidate
    return dest


def _move_to_artifacts(path, channel, item_id=""):
    if not channel:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    dest_dir = download_artifacts_dir(channel, item_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest = _unique_artifact_path(os.path.join(dest_dir, os.path.basename(path)))
    try:
        os.replace(path, dest)
    except OSError:
        try:
            os.remove(path)
        except OSError:
            pass


def relocate_sidecars(source_dir, media_kinds=None, channel="", item_id=""):
    """Keep only requested media in the user folder; move the rest to AppData."""
    if not source_dir or not os.path.isdir(source_dir):
        return
    kinds = normalize_media_kinds(media_kinds)
    keep_video = "video" in kinds
    keep_music = "music" in kinds
    keep_image = "image" in kinds

    for path in list(_iter_media_files(source_dir)):
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        if ext in _STAGING_EXTS:
            continue
        kind = _kind_for_name(name)
        if _is_system_sidecar(name) or kind == "document":
            _move_to_artifacts(path, channel, item_id)
            continue
        if kind == "video" and keep_video:
            continue
        if kind == "music":
            if keep_music:
                continue
            _move_to_artifacts(path, channel, item_id)
            continue
        if kind == "image":
            if keep_image:
                continue
            _move_to_artifacts(path, channel, item_id)
            continue
        if kind == "video":
            if keep_video:
                continue
            _move_to_artifacts(path, channel, item_id)
            continue
        _move_to_artifacts(path, channel, item_id)


_KIND_DIRS = {"video": "video", "music": "audio", "image": "image"}


def organize_media_into_kinds(source_dir, media_kinds=None, kind_folders=None):
    """Flatten leftover type folders, then move files into Views save folders."""
    if not source_dir or not os.path.isdir(source_dir):
        return
    for name in _KIND_DIRS.values():
        folder = os.path.join(source_dir, name)
        if not os.path.isdir(folder):
            continue
        try:
            entries = list(os.listdir(folder))
        except OSError:
            continue
        for filename in entries:
            src = os.path.join(folder, filename)
            if not os.path.isfile(src):
                continue
            dest = os.path.join(source_dir, filename)
            if os.path.exists(dest):
                continue
            try:
                os.replace(src, dest)
            except OSError:
                continue
        try:
            os.rmdir(folder)
        except OSError:
            pass
    targets = {
        key: os.path.normpath(path)
        for key, path in (kind_folders or {}).items()
        if str(path or "").strip()
    }
    if not targets:
        return
    try:
        names = list(os.listdir(source_dir))
    except OSError:
        return
    for name in names:
        path = os.path.join(source_dir, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in _STAGING_EXTS:
            continue
        kind = _kind_for_ext(ext)
        dest_dir = targets.get(kind)
        if not dest_dir:
            continue
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        if os.path.abspath(path) == os.path.abspath(dest):
            continue
        try:
            os.replace(path, dest)
        except OSError:
            continue


def _iter_media_files(source_dir):
    if not source_dir or not os.path.isdir(source_dir):
        return
    try:
        names = os.listdir(source_dir)
    except OSError:
        return
    for name in names:
        path = os.path.join(source_dir, name)
        if os.path.isfile(path):
            yield path
            continue
        if not os.path.isdir(path):
            continue
        try:
            for sub in os.listdir(path):
                subpath = os.path.join(path, sub)
                if os.path.isfile(subpath):
                    yield subpath
        except OSError:
            continue


def relocate_artifacts(source_dir, media_kinds=None):
    """List finished media in the source folder and kind subfolders."""
    kinds = normalize_media_kinds(media_kinds)
    found = []
    for path in _iter_media_files(source_dir):
        ext = os.path.splitext(path)[1].lower()
        if ext in _STAGING_EXTS:
            continue
        kind = _kind_for_ext(ext)
        if kind and kind in kinds:
            found.append(path)
    return found


def _number(value):
    if value in (None, "", "NA", "None", "none"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_progress_line(line):
    """Turn one yt-dlp progress line into a dict, or return None for normal output."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    fields = line.split("|")[1:]
    fields += [""] * (4 - len(fields))
    downloaded, total, speed, eta = (_number(f.strip()) for f in fields[:4])
    percent = None
    if downloaded is not None and total:
        percent = max(0.0, min(100.0, downloaded / total * 100.0))
    return {
        "status": "downloading",
        "downloaded": downloaded,
        "total": total,
        "speed": speed,
        "eta": eta,
        "percent": percent,
    }


def parse_info_line(line):
    """Turn a @@I JSON dump of the Facebook post into a progress-style event."""
    if not line.startswith(INFO_PREFIX):
        return None
    try:
        payload = json.loads(line[len(INFO_PREFIX):])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    ext = collapse_text(payload.get("ext"))
    qual = resolution_label(
        payload.get("width"),
        payload.get("height"),
        f"video.{ext}" if ext else "",
    )
    info = {
        "title": collapse_text(payload.get("title")),
        "description": collapse_text(payload.get("description")),
        "uploader": collapse_text(payload.get("uploader")),
        "duration": _number(payload.get("duration")),
        "extractor_key": collapse_text(payload.get("extractor_key")),
        "webpage_url_domain": collapse_text(payload.get("webpage_url_domain")),
        "platform": extra_platform_from_key(
            payload.get("extractor_key"),
            payload.get("webpage_url_domain"),
        ),
    }
    if qual:
        info["quality"] = qual
    return info


def extra_platform_from_key(key, domain=""):
    return platform_from_extractor(key or "", domain or "")


def parse_file_line(line):
    """Turn a @@F JSON path into a filepath event."""
    if not line.startswith(FILE_PREFIX):
        return None
    try:
        path = json.loads(line[len(FILE_PREFIX):])
    except json.JSONDecodeError:
        return None
    if not path:
        return None
    return {"filepath": path}


def tiktok_dateafter(days=""):
    """yt-dlp --dateafter YYYYMMDD for 'videos newer than N days', or ''."""
    try:
        n = int(days or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return (date.today() - timedelta(days=n)).strftime("%Y%m%d")


def resolve_filename_template(template=""):
    """yt-dlp output name; empty falls back to caption, title, then id."""
    text = (template or "").strip()
    return text or OUTPUT_TEMPLATE


def filename_preset_for_template(template=""):
    """Map a saved template back to a preset key, or ``custom``."""
    text = resolve_filename_template(template)
    for key, _label, fmt in FILENAME_PRESETS:
        if text == fmt:
            return key
    return "custom"


def filename_template_for_preset(key):
    """Return the yt-dlp template for a preset key, or '' when unknown."""
    for preset_key, _label, fmt in FILENAME_PRESETS:
        if preset_key == key:
            return fmt
    return ""


def twitter_status_id(url):
    """Numeric status id from an x.com / twitter.com URL, or ''."""
    match = _TWITTER_STATUS_RE.search(url or "")
    return match.group(1) if match else ""


def pinterest_pin_id(url):
    """Numeric pin id from a pinterest.com /pin/ URL, or ''."""
    match = _PINTEREST_PIN_RE.search(url or "")
    return match.group(1) if match else ""


def _http_open(url, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": _HTTP_UA})
    return urllib.request.urlopen(request, timeout=timeout)


def pinterest_resource(resource, options, timeout=20):
    """GET Pinterest resource/{Name}Resource/get/ JSON (yt-dlp-compatible)."""
    payload = json.dumps({"options": options})
    api_url = (
        f"https://www.pinterest.com/resource/{resource}Resource/get/"
        f"?{urlencode({'data': payload})}"
    )
    request = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": _HTTP_UA,
            "X-Pinterest-PWS-Handler": _PINTEREST_PWS,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not isinstance(body, dict):
        raise ValueError("Invalid Pinterest response.")
    response = body.get("resource_response")
    return response if isinstance(response, dict) else {}


def _twitter_media_from_payload(payload):
    """Collect (kind, url) pairs from fxtwitter / vxtwitter JSON."""
    found = []
    if not isinstance(payload, dict):
        return found
    tweet = payload.get("tweet") if isinstance(payload.get("tweet"), dict) else payload
    if not isinstance(tweet, dict):
        tweet = payload

    def add(kind, media_url):
        media_url = (media_url or "").strip()
        if media_url:
            found.append((kind, media_url))

    media = tweet.get("media")
    if isinstance(media, dict):
        for photo in media.get("photos") or []:
            if isinstance(photo, dict):
                add("photo", photo.get("url"))
            elif isinstance(photo, str):
                add("photo", photo)
        for video in media.get("videos") or []:
            if isinstance(video, dict):
                add("video", video.get("url"))
            elif isinstance(video, str):
                add("video", video)
    for item in tweet.get("media_extended") or payload.get("media_extended") or []:
        if not isinstance(item, dict):
            continue
        media_url = item.get("url") or ""
        kind = (item.get("type") or "").lower()
        if kind in ("image", "photo"):
            add("photo", media_url)
        elif kind == "video" or ".mp4" in media_url.lower():
            add("video", media_url)
    for media_url in tweet.get("mediaURLs") or payload.get("mediaURLs") or []:
        if not isinstance(media_url, str):
            continue
        path = media_url.split("?", 1)[0].lower()
        if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
            add("photo", media_url)
        elif ".mp4" in path:
            add("video", media_url)

    seen = set()
    unique = []
    for kind, media_url in found:
        if media_url in seen:
            continue
        if kind == "video" and ".mp4" not in media_url.lower():
            continue
        seen.add(media_url)
        unique.append((kind, media_url))
    return unique


def _url_filename_ext(media_url, kind):
    path = urlparse(media_url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".mp4", ".mov", ".webm"}:
        return ext
    return ".mp4" if kind == "video" else ".jpg"


def _append_download_archive(archive_path, extractor, item_id):
    if not archive_path or not item_id:
        return
    try:
        with open(archive_path, "a", encoding="utf-8") as f:
            f.write(f"{extractor} {item_id}\n")
    except OSError:
        pass


def _twitter_media_fallback(
    url, output_dir, archive_path="", log=None, on_progress=None, should_stop=None,
    media_kinds=None,
):
    """Download tweet photos (and mp4s) from a public syndication JSON. No yt-dlp."""
    status_id = twitter_status_id(url)
    if not status_id:
        return False
    kinds = normalize_media_kinds(media_kinds)
    os.makedirs(output_dir, exist_ok=True)
    media = []
    for template in _TWITTER_MEDIA_APIS:
        check_stop(should_stop)
        try:
            with _http_open(template.format(id=status_id)) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
            continue
        media = _twitter_media_from_payload(payload)
        if media:
            break
    if not media:
        return False

    saved = []
    for index, (kind, media_url) in enumerate(media, start=1):
        check_stop(should_stop)
        if kind == "photo" and "image" not in kinds:
            continue
        if kind == "video" and "video" not in kinds:
            continue
        ext = _url_filename_ext(media_url, kind)
        suffix = "" if len(media) == 1 else f"_{index}"
        dest = os.path.join(output_dir, f"{status_id}{suffix}{ext}")
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            saved.append(dest)
            continue
        try:
            with _http_open(media_url, timeout=60) as resp:
                data = resp.read()
        except (OSError, urllib.error.URLError, TimeoutError):
            continue
        if not data:
            continue
        with open(dest, "wb") as f:
            f.write(data)
        saved.append(dest)
        if on_progress:
            on_progress(url, {"filepath": dest})

    if not saved:
        return False
    if log:
        log(f"[{status_id}] saved {len(saved)} Twitter media file(s)")
    _append_download_archive(archive_path, "twitter", status_id)
    if on_progress:
        first = saved[0]
        info = {"title": status_id, "filepath": first}
        on_progress(url, info)
    return True


def _pinterest_video_list(data):
    if not isinstance(data, dict):
        return {}
    videos = data.get("videos")
    if isinstance(videos, dict) and isinstance(videos.get("video_list"), dict):
        return videos["video_list"]
    story = data.get("story_pin_data")
    if not isinstance(story, dict):
        return {}
    for page in story.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for block in page.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            video = block.get("video")
            if isinstance(video, dict) and isinstance(video.get("video_list"), dict):
                return video["video_list"]
    return {}


def _pinterest_best_video_url(data):
    best, area = "", -1
    for spec in _pinterest_video_list(data).values():
        if not isinstance(spec, dict):
            continue
        media_url = (spec.get("url") or "").strip()
        if not media_url or "m3u8" in media_url.lower():
            continue
        size = (spec.get("width") or 0) * (spec.get("height") or 0)
        if size > area or (size == area and ".mp4" in media_url.lower()):
            best, area = media_url, size
    return best


def _pinterest_best_image_url(data):
    if not isinstance(data, dict):
        return ""
    images = data.get("images")
    if isinstance(images, dict):
        orig = images.get("orig")
        if isinstance(orig, dict) and orig.get("url"):
            return orig["url"].strip()
        if isinstance(orig, str) and orig.strip():
            return orig.strip()
        best, area = "", -1
        for spec in images.values():
            if not isinstance(spec, dict) or not spec.get("url"):
                continue
            size = (spec.get("width") or 0) * (spec.get("height") or 0)
            if size >= area:
                best, area = spec["url"].strip(), size
        if best:
            return best
    orig_url = data.get("orig")
    if isinstance(orig_url, str):
        return orig_url.strip()
    return ""


def _pinterest_pin_duration(data):
    for spec in _pinterest_video_list(data).values():
        if not isinstance(spec, dict):
            continue
        raw = spec.get("duration")
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        return value / 1000.0 if value > 100 else value
    return None


def _has_downloaded_media(dest_dir):
    if not dest_dir or not os.path.isdir(dest_dir):
        return False
    for root, _dirs, files in os.walk(dest_dir):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in _STAGING_EXTS:
                continue
            if ext in _VIDEO_EXTS or ext in _AUDIO_EXTS or ext in _IMAGE_EXTS:
                return True
    return False


def _pinterest_media_fallback(
    url, output_dir, archive_path="", log=None, on_progress=None, should_stop=None,
    media_kinds=None,
):
    """Download a pin's mp4 or largest image from PinResource JSON."""
    pin_id = pinterest_pin_id(url)
    if not pin_id:
        return False
    kinds = normalize_media_kinds(media_kinds)
    check_stop(should_stop)
    try:
        response = pinterest_resource(
            "Pin",
            {"field_set_key": "unauth_react_main_pin", "id": pin_id},
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return False
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False

    video_url = _pinterest_best_video_url(data)
    image_url = "" if video_url else _pinterest_best_image_url(data)
    jobs = []
    if video_url and "video" in kinds:
        jobs.append(("video", video_url))
    elif image_url and "image" in kinds:
        jobs.append(("photo", image_url))
    if not jobs:
        return False

    os.makedirs(output_dir, exist_ok=True)
    saved = []
    for index, (kind, media_url) in enumerate(jobs, start=1):
        check_stop(should_stop)
        ext = _url_filename_ext(media_url, "video" if kind == "video" else "photo")
        suffix = "" if len(jobs) == 1 else f"_{index}"
        dest = os.path.join(output_dir, f"{pin_id}{suffix}{ext}")
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            saved.append(dest)
            continue
        try:
            with _http_open(media_url, timeout=60) as resp:
                blob = resp.read()
        except (OSError, urllib.error.URLError, TimeoutError):
            continue
        if not blob:
            continue
        with open(dest, "wb") as f:
            f.write(blob)
        saved.append(dest)
        if on_progress:
            on_progress(url, {"filepath": dest})

    if not saved:
        return False
    if log:
        log(f"[{pin_id}] saved {len(saved)} Pinterest media file(s)")
    _append_download_archive(archive_path, "pinterest", pin_id)
    if on_progress:
        on_progress(url, {"title": pin_id, "filepath": saved[0]})
    return True


def _yt_dlp_args(
    url, output_dir, fragments, archive_path, ffmpeg_location="",
    cookies_browser="", filename_template="", cookies_file="", dateafter="",
    limit_rate="", media_kinds=None, video_quality="", gpu_accel="", workers=DEFAULT_WORKERS,
):
    ffmpeg_location = resolve_ffmpeg(ffmpeg_location)
    name = resolve_filename_template(filename_template)
    platform = detect_platform(url)
    if platform == "wetv" and name == OUTPUT_TEMPLATE:
        name = "EP%(episode_number)02d_ %(series,title).60B [%(id)s].%(ext)s"
    elif (platform in MOVIE_DRAMA_PLATFORMS or platform in ("bilibili", "bilitv")) and name == OUTPUT_TEMPLATE:
        name = "%(title,id).80B [%(id)s].%(ext)s"
    fmt = format_selector_for_quality(video_quality, platform)
    cookies_browser = (cookies_browser or "").strip()
    cookies_file = (cookies_file or "").strip()
    kinds = normalize_media_kinds(media_kinds)
    want_video = "video" in kinds
    want_music = "music" in kinds
    want_image = "image" in kinds
    if platform in ("douyin", "kuaishou", "kwai") and not cookies_browser and not cookies_file:
        cookies_browser = "chrome"
    args = [
        *yt_dlp_command_prefix(),
        "--newline",
        "--no-color",
        "--no-warnings",
        "-f", fmt,
        "-i",                                   # skip broken/removed reels
        "-N", str(fragments),                   # fragments of ONE reel, in parallel
        "--retries", "10",
        "--fragment-retries", "10",
        "--file-access-retries", "10",
        "--socket-timeout", "20",
        "--no-overwrites",
        "--continue",
        "--progress",                           # keep bars even though --print is set
        "--download-archive", archive_path,     # finished reels are skipped instantly
        "--progress-template", f"download:{PROGRESS_TEMPLATE}",
        "--print", f"video:{INFO_TEMPLATE}",
        "--print", f"after_move:{FILE_TEMPLATE}",
        "--trim-filenames", "120",
        "--output", os.path.join(output_dir, name),
    ]
    if sys.platform == "win32":
        args.append("--windows-filenames")
    if ffmpeg_location:
        args.extend(("--ffmpeg-location", ffmpeg_location))
    if gpu_accel:
        args.extend(("--postprocessor-args", ffmpeg_postprocessor_arg(gpu_accel, workers=workers)))
    if cookies_browser:
        cookies_browser = readable_browser_cookie_spec(cookies_browser) or cookies_browser
        args.extend(("--cookies-from-browser", cookies_browser))
    if cookies_file:
        args.extend(("--cookies", cookies_file))
    if platform == "twitter":
        args.extend(("--extractor-args", TWITTER_EXTRACTOR_ARGS))
    if platform in ("douyin", "kuaishou", "kwai", "snackvideo", "xiaohongshu") or platform in MOVIE_DRAMA_PLATFORMS:
        args.extend(("--impersonate", "chrome"))
    if dateafter and platform == "tiktok":
        args.extend(("--dateafter", dateafter))
    limit_rate = (limit_rate or "").strip()
    if limit_rate:
        args.extend(("--limit-rate", limit_rate))
    if want_music:
        args.extend(("--extract-audio", "--audio-format", "m4a"))
        if want_video:
            args.append("--keep-video")
    if want_image:
        args.extend(("--write-thumbnail", "--convert-thumbnails", "jpg"))
    else:
        args.append("--no-write-thumbnail")
    want_document = "document" in kinds
    if want_document:
        args.extend(("--write-description", "--write-info-json"))
    else:
        args.extend(("--no-write-description", "--no-write-info-json"))
    if (want_image or want_document) and not want_video and not want_music:
        args.append("--skip-download")
    args.append(url)
    return args


class _ProcessGroup:
    """Keeps track of running yt-dlp processes so a cancel can kill all of them."""

    def __init__(self):
        self._lock = threading.Lock()
        self._processes = set()

    def add(self, process):
        with self._lock:
            self._processes.add(process)

    def discard(self, process):
        with self._lock:
            self._processes.discard(process)

    def terminate_all(self):
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _rename_instagram_file(dest_dir, url, caption):
    """Name an Instagram save from its caption when yt-dlp used the shortcode."""
    from app.core.web_media import _instagram_media_info, apply_caption_filename

    rid = reel_id(url)
    cap = collapse_text(caption)
    if not cap or cap == rid:
        try:
            info = _instagram_media_info(url) or {}
        except Exception:
            info = {}
        cap = collapse_text(info.get("filename_prefix") or info.get("title") or "")
    if not cap or cap == rid or not os.path.isdir(dest_dir):
        return "", cap
    renamed = ""
    for dirpath, _, names in os.walk(dest_dir):
        for name in names:
            if name.endswith((".part", ".ytdl", ".json", ".description", ".jpg", ".webp")):
                continue
            path = os.path.join(dirpath, name)
            new = apply_caption_filename(path, cap, rid)
            if new and os.path.abspath(new) != os.path.abspath(path):
                renamed = new
    return renamed, cap


def browser_cookie_hint(line):
    """Explain a Chrome cookie failure in the download log."""
    text = line or ""
    if "Failed to decrypt with DPAPI" in text:
        return (
            "Chrome's saved login cannot be read. "
            "In Settings → Cookies, paste a Cookie / cURL from a logged-in TikTok page, or choose Firefox."
        )
    if "Could not copy Chrome cookie database" in text:
        return "Chrome's cookie file is still locked. Restart CamDot and download again."
    if "could not find firefox cookies database" in text.lower():
        return (
            "Firefox is not installed, so there is no TikTok login to use. "
            "Install Firefox, log in to TikTok, and leave Settings → Cookies on Firefox."
        )
    return ""


def tiktok_missing_file_hint(line, *, cookies_browser="", cookies_file=""):
    """Why a TikTok extract had metadata and no media file."""
    if "No video formats found" not in (line or ""):
        return ""
    if (cookies_browser or "").strip() or (cookies_file or "").strip():
        return (
            "TikTok returned this episode without a video file. "
            "Use a TikTok login that can open this drama under Settings → Cookies."
        )
    return (
        "TikTok returned this episode without a video file. "
        "Short dramas play in a logged-in account. "
        "Set Settings → Cookies to Chrome, close Chrome, and download again."
    )


def _download_one(
    url, output_dir, fragments, archive_path, ffmpeg_location,
    log, on_progress, should_stop, group, cookies_browser="",
    filename_template="", cookies_file="", dateafter="",
    limit_rate="", media_kinds=None, source_folder="", kind_folders=None,
    channel="", video_quality="", gpu_accel="", workers=DEFAULT_WORKERS,
    caption="",
):
    check_stop(should_stop)
    kinds = normalize_media_kinds(media_kinds)
    dest_dir = resolve_item_dir(output_dir, source_folder)
    os.makedirs(dest_dir, exist_ok=True)
    on_progress(url, {"status": "downloading"})
    platform = detect_platform(url)

    if platform in WEB_FALLBACK_ONLY_PLATFORMS:
        try:
            if download_with_fallback(
                url,
                dest_dir,
                item_id=reel_id(url),
                archive_path=archive_path,
                ffmpeg_location=ffmpeg_location,
                log=log,
                on_progress=on_progress,
                should_stop=should_stop,
                media_kinds=kinds,
                gpu_accel=gpu_accel or "auto",
                workers=workers,
                caption=caption,
            ):
                organize_media_into_kinds(dest_dir, kinds, kind_folders)
                relocate_sidecars(dest_dir, kinds, channel, reel_id(url))
                relocated = relocate_artifacts(dest_dir, kinds)
                if relocated:
                    on_progress(url, {"filepath": relocated[0]})
                on_progress(url, {"status": "done", "code": 0})
                return 0
        except StopRequested:
            on_progress(url, {"status": "cancelled"})
            raise
        on_progress(url, {"status": "failed", "code": 1})
        return 1

    fetch_url = url
    if platform == "tiktok":
        from app.core.collect import tiktok_drama_watch_url
        watch_url = tiktok_drama_watch_url(url)
        if watch_url:
            fetch_url = watch_url
    process = subprocess.Popen(
        _yt_dlp_args(
            fetch_url, dest_dir, fragments, archive_path, ffmpeg_location,
            cookies_browser=cookies_browser,
            filename_template=filename_template,
            cookies_file=cookies_file,
            dateafter=dateafter,
            limit_rate=limit_rate,
            media_kinds=kinds,
            video_quality=video_quality,
            gpu_accel=gpu_accel,
            workers=workers,
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,          # one pipe, so a full stderr can never deadlock
        creationflags=_NO_WINDOW,
    )
    group.add(process)
    hinted = False
    try:
        for raw in iter(process.stdout.readline, b""):
            check_stop(should_stop)
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            progress = parse_progress_line(line)
            if progress:
                on_progress(url, progress)
                continue
            info = parse_info_line(line)
            if info:
                on_progress(url, info)
                continue
            saved = parse_file_line(line)
            if saved:
                on_progress(url, saved)
                continue
            log(f"[{reel_id(url)}] {line}")
            if hinted:
                continue
            hint = browser_cookie_hint(line)
            if not hint and platform == "tiktok":
                hint = tiktok_missing_file_hint(
                    line, cookies_browser=cookies_browser, cookies_file=cookies_file,
                )
            if hint:
                hinted = True
                log(f"[{reel_id(url)}] {hint}")
        code = process.wait()
    except StopRequested:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        on_progress(url, {"status": "cancelled"})
        raise
    finally:
        group.discard(process)
        process.stdout.close()

    platform = detect_platform(url)
    if platform == "instagram":
        renamed, shown = _rename_instagram_file(dest_dir, url, caption)
        if renamed:
            event = {"filepath": renamed}
            if shown and shown != reel_id(url):
                event["title"] = shown
                event["description"] = shown
            on_progress(url, event)
    if code != 0 and platform == "twitter":
        try:
            if _twitter_media_fallback(
                url, dest_dir, archive_path, log=log,
                on_progress=on_progress, should_stop=should_stop,
                media_kinds=kinds,
            ):
                organize_media_into_kinds(dest_dir, kinds, kind_folders)
                relocate_sidecars(dest_dir, kinds, channel, reel_id(url))
                relocated = relocate_artifacts(dest_dir, kinds)
                if relocated:
                    on_progress(url, {"filepath": relocated[0]})
                on_progress(url, {"status": "done", "code": 0})
                return 0
        except StopRequested:
            on_progress(url, {"status": "cancelled"})
            raise
    organize_media_into_kinds(dest_dir, kinds, kind_folders)
    relocate_sidecars(dest_dir, kinds, channel, reel_id(url))
    relocated = relocate_artifacts(dest_dir, kinds)
    if platform == "pinterest" and (code != 0 or not _has_downloaded_media(dest_dir)):
        try:
            if _pinterest_media_fallback(
                url, dest_dir, archive_path, log=log,
                on_progress=on_progress, should_stop=should_stop,
                media_kinds=kinds,
            ):
                organize_media_into_kinds(dest_dir, kinds, kind_folders)
                relocate_sidecars(dest_dir, kinds, channel, reel_id(url))
                relocated = relocate_artifacts(dest_dir, kinds)
                if relocated:
                    on_progress(url, {"filepath": relocated[0]})
                on_progress(url, {"status": "done", "code": 0})
                return 0
        except StopRequested:
            on_progress(url, {"status": "cancelled"})
            raise
    _NATIVE_YTDLP_VIDEO_PLATFORMS = {
        "youtube", "bilibili", "bilitv", "wetv", "iqiyi", "tiktok", "douyin",
    }
    if (code != 0 or not _has_downloaded_media(dest_dir)) and platform not in _NATIVE_YTDLP_VIDEO_PLATFORMS:
        try:
            if download_with_fallback(
                url,
                dest_dir,
                item_id=reel_id(url),
                archive_path=archive_path,
                ffmpeg_location=ffmpeg_location,
                log=log,
                on_progress=on_progress,
                should_stop=should_stop,
                media_kinds=kinds,
                gpu_accel=gpu_accel or "auto",
                workers=workers,
                caption=caption,
            ):
                organize_media_into_kinds(dest_dir, kinds, kind_folders)
                relocate_sidecars(dest_dir, kinds, channel, reel_id(url))
                relocated = relocate_artifacts(dest_dir, kinds)
                if relocated:
                    on_progress(url, {"filepath": relocated[0]})
                on_progress(url, {"status": "done", "code": 0})
                return 0
        except StopRequested:
            on_progress(url, {"status": "cancelled"})
            raise
    if relocated:
        on_progress(url, {"filepath": relocated[0]})
    on_progress(url, {"status": "done" if code == 0 else "failed", "code": code})
    return code


def _expand_bilibili_season_downloads(
    urls,
    folders,
    *,
    log,
    should_stop=None,
    on_progress=None,
    cookies_browser="",
    cookies_file="",
):
    """Replace bilibili.tv season page URLs with episode URLs and movie folders."""
    on_progress = on_progress or (lambda url, event: None)
    folders = dict(folders or {})
    expanded = []
    for url in urls or []:
        if not is_bilibili_season_url(url):
            expanded.append(url)
            continue
        log(f"Expanding series into episodes: {url}")
        from app.core.collect import list_bilibili_season_entries
        try:
            entries = list_bilibili_season_entries(
                url,
                log=log,
                should_stop=should_stop,
                cookies_browser=cookies_browser,
                cookies_file=cookies_file,
            )
        except Exception as exc:
            log(f"Could not expand series: {exc}")
            expanded.append(url)
            continue
        if not entries:
            expanded.append(url)
            continue
        movie = series_folder_for_items(entries)
        prior = (folders.get(url) or "").strip()
        for entry in entries:
            ep_url = entry.get("url") or ""
            if not ep_url:
                continue
            expanded.append(ep_url)
            if movie:
                if prior and movie.lower() in os.path.normpath(prior).lower().split(os.sep):
                    folders[ep_url] = prior
                elif prior:
                    folders[ep_url] = os.path.join(prior, movie)
                else:
                    folders[ep_url] = movie
            on_progress(ep_url, {
                "title": entry.get("title"),
                "id": entry.get("id"),
                "uploader": entry.get("uploader"),
                "status": "queued",
            })
        on_progress(url, {"status": "done"})
        folders.pop(url, None)
    return expanded, folders


def download_urls(
    channel,
    urls,
    *,
    log=print,
    should_stop=None,
    on_progress=None,
    workers=DEFAULT_WORKERS,
    fragments=DEFAULT_FRAGMENTS,
    output_root=None,
    ffmpeg_location="",
    cookies_browser="",
    filename_template="",
    cookies_file="",
    dateafter="",
    limit_rate="",
    media_kinds=None,
    source_folders=None,
    group_by_source=True,
    url_media_kinds=None,
    kind_folders=None,
    video_quality="",
    gpu_accel="",
    url_titles=None,
):
    """Download every item URL, `workers` at a time. Returns the number of failures."""
    output_root = output_root or default_output_root()
    output_dir = os.path.join(output_root, channel)
    os.makedirs(output_dir, exist_ok=True)
    archive_path = os.path.join(channel_state_dir(channel), ".downloaded.txt")
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    on_progress = on_progress or (lambda url, event: None)
    workers = max(1, int(workers))
    fragments = max(1, int(fragments))
    kinds = normalize_media_kinds(media_kinds)
    folders = dict(source_folders or {})

    if not urls:
        log("Nothing to download.")
        return 0

    urls, folders = _expand_bilibili_season_downloads(
        urls,
        folders,
        log=log,
        should_stop=should_stop,
        on_progress=on_progress,
        cookies_browser=cookies_browser,
        cookies_file=cookies_file,
    )
    if not urls:
        log("Nothing to download.")
        return 0

    log(f"Downloading {len(urls)} item(s) into {output_dir}")
    active_workers = min(workers, max(1, len(urls)))
    threads_per_worker = ffmpeg_threads_per_worker(active_workers)
    backend = resolve_gpu_backend(gpu_accel or "auto")
    log(
        f"{active_workers} item(s) at a time, {fragments} fragment(s) per item "
        f"(GPU: {backend.upper()}, {threads_per_worker} thread(s)/worker)."
    )

    group = _ProcessGroup()
    failures = 0
    extra_kw = {}
    if video_quality:
        extra_kw["video_quality"] = video_quality
    if gpu_accel:
        extra_kw["gpu_accel"] = gpu_accel
        extra_kw["workers"] = active_workers
    with ThreadPoolExecutor(max_workers=active_workers) as pool:
        futures = {
            pool.submit(
                _download_one,
                url, output_dir, fragments, archive_path, ffmpeg_location,
                log, on_progress, should_stop, group, cookies_browser,
                filename_template, cookies_file, dateafter, limit_rate,
                normalize_media_kinds((url_media_kinds or {}).get(url) or kinds),
                folders.get(url)
                if url in folders
                else (source_folder_name("", "", reel_id(url)) if group_by_source else ""),
                kind_folders,
                channel,
                caption=(url_titles or {}).get(url, ""),
                **extra_kw,
            ): url
            for url in urls
        }
        pending = set(futures)
        try:
            while pending:
                done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for future in done:
                    if future.exception() is not None:
                        raise future.exception()
                    if future.result() != 0:
                        failures += 1
                check_stop(should_stop)
        except StopRequested:
            for future in futures:
                future.cancel()
            group.terminate_all()
            raise

    log(f"Finished: {len(urls) - failures} ok, {failures} failed.")
    return failures


def download_from_csv(channel, csv_path, **kwargs):
    """Download every reel URL listed in csv_path. Returns a process-style exit code."""
    urls = read_urls(csv_path)
    return 1 if download_urls(channel, urls, **kwargs) else 0
