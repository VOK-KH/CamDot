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

from app.core.jobs import StopRequested, check_stop
from app.core.runtime import (
    channel_state_dir,
    default_output_root,
    resolve_ffmpeg,
    yt_dlp_command_prefix,
)
from app.core.urls import detect_platform

DEFAULT_WORKERS = 4
DEFAULT_FRAGMENTS = 8

# Bilibili (and others) split video and audio; `best` is video-only there and fails.
FORMAT_SELECTOR = "bv*+ba/b"
# Twitter image tweets have no video+audio pair; keep merge first, then fall back.
TWITTER_FORMAT_SELECTOR = "bv*+ba/b/best"
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

ALL_MEDIA_KINDS = frozenset({"video", "music", "image"})
_WIN_ILLEGAL = re.compile(r'[\\/:*?"<>|]+')
_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}
_AUDIO_EXTS = {".m4a", ".mp3", ".opus", ".ogg", ".flac"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_STAGING_EXTS = {".part", ".ytdl"}

# Caption first, then the Facebook title, then the reel id. The id stays in
# brackets so a long caption can never collide with another file.
OUTPUT_TEMPLATE = "%(description,title,id).80B [%(id)s].%(ext)s"

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
    + "%(.{id,title,description,uploader,duration,extractor_key,webpage_url_domain})j"
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
    query_id = parse_qs(parts.query).get("v") or parse_qs(parts.query).get("modal_id") or [""]
    query_id = query_id[0]
    if query_id:
        return query_id
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
    """Views keys (video/music/image); empty or None means all three."""
    if not media_kinds:
        return ALL_MEDIA_KINDS
    return frozenset(media_kinds)


def source_folder_name(title="", description="", rid=""):
    """Windows-safe folder from caption, then title; else random hex (+ rid)."""
    text = collapse_text(description) or collapse_text(title)
    text = _WIN_ILLEGAL.sub(" ", text)
    text = collapse_text(text)
    text = text[:80].rstrip(" .")
    if text:
        return text
    token = secrets.token_hex(4)
    suffix = _WIN_ILLEGAL.sub("", collapse_text(rid)).strip(" .")
    return f"{token}-{suffix}" if suffix else token


def _kind_for_ext(ext):
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "music"
    if ext in _IMAGE_EXTS:
        return "image"
    return ""


_KIND_DIRS = {"video": "video", "music": "audio", "image": "image"}


def organize_media_into_kinds(source_dir, media_kinds=None):
    """Move finished files into video/, audio/, and image/ under the source folder."""
    kinds = normalize_media_kinds(media_kinds)
    if not source_dir or not os.path.isdir(source_dir):
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
        if not kind or kind not in kinds:
            continue
        dest_dir = os.path.join(source_dir, _KIND_DIRS[kind])
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
    return {
        "title": collapse_text(payload.get("title")),
        "description": collapse_text(payload.get("description")),
        "uploader": collapse_text(payload.get("uploader")),
        "duration": _number(payload.get("duration")),
        "extractor_key": collapse_text(payload.get("extractor_key")),
        "webpage_url_domain": collapse_text(payload.get("webpage_url_domain")),
        "platform": extra_platform_from_key(payload.get("extractor_key")),
    }


def extra_platform_from_key(key):
    key = (key or "").lower()
    if "bili" in key:
        return "bilibili"
    for name in ("facebook", "instagram", "youtube", "tiktok", "twitter", "douyin", "kuaishou", "pinterest"):
        if name in key:
            return name
    return ""


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
    limit_rate="", media_kinds=None,
):
    ffmpeg_location = resolve_ffmpeg(ffmpeg_location)
    name = resolve_filename_template(filename_template)
    platform = detect_platform(url)
    if platform in ("twitter", "pinterest"):
        fmt = TWITTER_FORMAT_SELECTOR
    else:
        fmt = FORMAT_SELECTOR
    cookies_browser = (cookies_browser or "").strip()
    cookies_file = (cookies_file or "").strip()
    kinds = normalize_media_kinds(media_kinds)
    want_video = "video" in kinds
    want_music = "music" in kinds
    want_image = "image" in kinds
    if platform in ("douyin", "kuaishou") and not cookies_browser and not cookies_file:
        cookies_browser = "chrome"
    args = [
        *yt_dlp_command_prefix(),
        "--newline",
        "--no-color",
        "--no-warnings",
        "-f", fmt,
        "-i",                                   # skip broken/removed reels
        "-N", str(fragments),                   # fragments of ONE reel, in parallel
        "--retries", "5",
        "--fragment-retries", "5",
        "--socket-timeout", "20",
        "--no-overwrites",
        "--continue",
        "--progress",                           # keep bars even though --print is set
        "--download-archive", archive_path,     # finished reels are skipped instantly
        "--progress-template", f"download:{PROGRESS_TEMPLATE}",
        "--print", f"video:{INFO_TEMPLATE}",
        "--print", f"after_move:{FILE_TEMPLATE}",
        "--trim-filenames", "180",
        "--output", os.path.join(output_dir, name),
    ]
    if sys.platform == "win32":
        args.append("--windows-filenames")
    if ffmpeg_location:
        args.extend(("--ffmpeg-location", ffmpeg_location))
    if cookies_browser:
        args.extend(("--cookies-from-browser", cookies_browser))
    if cookies_file:
        args.extend(("--cookies", cookies_file))
    if platform == "twitter":
        args.extend(("--extractor-args", TWITTER_EXTRACTOR_ARGS))
    if platform in ("douyin", "kuaishou"):
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
    if want_image and not want_video and not want_music:
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


def _download_one(
    url, output_dir, fragments, archive_path, ffmpeg_location,
    log, on_progress, should_stop, group, cookies_browser="",
    filename_template="", cookies_file="", dateafter="",
    limit_rate="", media_kinds=None, source_folder="",
):
    check_stop(should_stop)
    kinds = normalize_media_kinds(media_kinds)
    dest_dir = os.path.join(output_dir, source_folder) if source_folder else output_dir
    os.makedirs(dest_dir, exist_ok=True)
    on_progress(url, {"status": "downloading"})

    process = subprocess.Popen(
        _yt_dlp_args(
            url, dest_dir, fragments, archive_path, ffmpeg_location,
            cookies_browser=cookies_browser,
            filename_template=filename_template,
            cookies_file=cookies_file,
            dateafter=dateafter,
            limit_rate=limit_rate,
            media_kinds=kinds,
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,          # one pipe, so a full stderr can never deadlock
        creationflags=_NO_WINDOW,
    )
    group.add(process)
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
    if code != 0 and platform == "twitter":
        try:
            if _twitter_media_fallback(
                url, dest_dir, archive_path, log=log,
                on_progress=on_progress, should_stop=should_stop,
                media_kinds=kinds,
            ):
                organize_media_into_kinds(dest_dir, kinds)
                relocated = relocate_artifacts(dest_dir, kinds)
                if relocated:
                    on_progress(url, {"filepath": relocated[0]})
                on_progress(url, {"status": "done", "code": 0})
                return 0
        except StopRequested:
            on_progress(url, {"status": "cancelled"})
            raise
    organize_media_into_kinds(dest_dir, kinds)
    relocated = relocate_artifacts(dest_dir, kinds)
    if platform == "pinterest" and (code != 0 or not _has_downloaded_media(dest_dir)):
        try:
            if _pinterest_media_fallback(
                url, dest_dir, archive_path, log=log,
                on_progress=on_progress, should_stop=should_stop,
                media_kinds=kinds,
            ):
                organize_media_into_kinds(dest_dir, kinds)
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
    folders = source_folders or {}

    if not urls:
        log("Nothing to download.")
        return 0

    log(f"Downloading {len(urls)} item(s) into {output_dir}")
    log(f"{workers} item(s) at a time, {fragments} fragment(s) per item.")

    group = _ProcessGroup()
    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _download_one,
                url, output_dir, fragments, archive_path, ffmpeg_location,
                log, on_progress, should_stop, group, cookies_browser,
                filename_template, cookies_file, dateafter, limit_rate,
                kinds,
                folders.get(url)
                if url in folders
                else (source_folder_name("", "", reel_id(url)) if group_by_source else ""),
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
