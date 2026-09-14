"""Download reels with yt-dlp.

Two levels of parallelism, both tunable from the UI:
- several reels at the same time (a pool of yt-dlp processes)
- each reel split into fragments fetched concurrently (yt-dlp -N)
"""
import csv
import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from app.core.jobs import StopRequested, check_stop
from app.core.runtime import default_output_root, resolve_ffmpeg

DEFAULT_WORKERS = 4
DEFAULT_FRAGMENTS = 8

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
    query_id = parse_qs(parts.query).get("v", [""])[0]
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
    for name in ("facebook", "instagram", "youtube", "tiktok", "twitter"):
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


def resolve_filename_template(template=""):
    """yt-dlp output name; empty falls back to caption, title, then id."""
    text = (template or "").strip()
    return text or OUTPUT_TEMPLATE


def _yt_dlp_args(
    url, output_dir, fragments, archive_path, ffmpeg_location="",
    cookies_browser="", filename_template="",
):
    ffmpeg_location = resolve_ffmpeg(ffmpeg_location)
    name = resolve_filename_template(filename_template)
    args = [
        sys.executable, "-m", "yt_dlp",
        "--newline",
        "--no-color",
        "--no-warnings",
        "-f", "best",
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
    filename_template="",
):
    check_stop(should_stop)
    on_progress(url, {"status": "downloading"})

    process = subprocess.Popen(
        _yt_dlp_args(
            url, output_dir, fragments, archive_path, ffmpeg_location,
            cookies_browser=cookies_browser,
            filename_template=filename_template,
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
):
    """Download every item URL, `workers` at a time. Returns the number of failures."""
    output_root = output_root or default_output_root()
    output_dir = os.path.join(output_root, channel)
    os.makedirs(output_dir, exist_ok=True)
    archive_path = os.path.join(output_dir, ".downloaded.txt")
    on_progress = on_progress or (lambda url, event: None)
    workers = max(1, int(workers))
    fragments = max(1, int(fragments))

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
                filename_template,
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
