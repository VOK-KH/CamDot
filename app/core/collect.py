"""Collect post URLs and metadata: Selenium for Facebook reels feeds, yt-dlp otherwise."""
import csv
import json
import os
import time
from urllib.parse import urlparse

from app.core.download import collapse_text, read_urls, reel_id
from app.core.jobs import StopRequested, check_stop
from app.core.runtime import default_output_root, state_dir
from app.core.scrape import scrape_reel_urls
from app.core.urls import (
    FEED,
    SINGLE,
    TIKTOK_SEC_UID_PREFIX,
    UNSUPPORTED_FEED,
    UNSUPPORTED_FEED_MESSAGES,
    classify_source,
    collection_strategy,
    detect_platform,
    is_tiktok_user_feed,
    normalize_source_url,
    tiktok_sec_uid,
    tiktok_user_feed,
    tiktok_username,
)

TIKTOK_PROFILE_HELP = (
    "TikTok is blocking this profile page. Collect any single video from "
    "@{name} first — the app remembers the creator and the profile works "
    "afterwards. You can also paste tiktokuser:<sec_uid> directly."
)


def cookies_from_browser_value(browser="", profile=""):
    """Return the yt-dlp --cookies-from-browser argument, or empty if unused."""
    browser = (browser or "").strip().lower()
    if not browser or browser in ("none", "off", "-"):
        return ""
    profile = (profile or "").strip()
    return f"{browser}:{profile}" if profile else browser


def webpage_domain(url):
    host = urlparse(url).netloc.lower().split(":")[0]
    return host.removeprefix("www.")


def entry_from_url(url, **extra):
    """Minimal table row from a URL, used after the Facebook scraper."""
    platform = extra.get("platform") or detect_platform(url)
    item = {
        "url": url,
        "id": extra.get("id") or reel_id(url),
        "title": collapse_text(extra.get("title")),
        "description": collapse_text(extra.get("description")),
        "uploader": collapse_text(extra.get("uploader") or extra.get("channel")),
        "duration": extra.get("duration"),
        "platform": platform,
        "extractor_key": extra.get("extractor_key") or extra.get("ie_key") or "",
        "webpage_url_domain": extra.get("webpage_url_domain") or webpage_domain(url),
    }
    if extra.get("duration") in ("", "NA", "None", "none"):
        item["duration"] = None
    return item


def entry_from_info(info, fallback_url=""):
    url = info.get("webpage_url") or info.get("url") or fallback_url
    if url and not str(url).startswith("http"):
        url = fallback_url or url
    return entry_from_url(
        url,
        id=info.get("id"),
        title=info.get("title"),
        description=info.get("description"),
        uploader=info.get("uploader") or info.get("channel"),
        duration=info.get("duration"),
        platform=detect_platform(url) if url else extra_platform(info),
        extractor_key=info.get("extractor_key") or info.get("ie_key") or info.get("extractor"),
        webpage_url_domain=info.get("webpage_url_domain"),
    )


def extra_platform(info):
    key = (info.get("extractor_key") or info.get("extractor") or "").lower()
    for name in ("facebook", "instagram", "youtube", "tiktok", "twitter"):
        if name in key:
            return name
    return "unknown"


def tiktok_cache_path():
    return os.path.join(state_dir(), "tiktok-users.json")


def _read_tiktok_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def cached_tiktok_sec_uid(username, path=None):
    """Return a remembered sec_uid for @username, or empty."""
    if not username:
        return ""
    return _read_tiktok_cache(path or tiktok_cache_path()).get(username.lower(), "")


def tiktok_username_for_sec_uid(sec_uid, path=None):
    """Reverse lookup, so a tiktokuser: source still gets a readable folder."""
    if not sec_uid:
        return ""
    for name, value in _read_tiktok_cache(path or tiktok_cache_path()).items():
        if value == sec_uid:
            return name
    return ""


def remember_tiktok_user(username, sec_uid, path=None):
    """Store @username -> sec_uid so blocked profile pages can be listed later."""
    if not username or not str(sec_uid).startswith(TIKTOK_SEC_UID_PREFIX):
        return False
    path = path or tiktok_cache_path()
    data = _read_tiktok_cache(path)
    if data.get(username.lower()) == sec_uid:
        return False
    data[username.lower()] = sec_uid
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(temp, path)
    except OSError:
        return False
    return True


def _remember_from_info(info, cache_path=None):
    if not isinstance(info, dict):
        return
    name = info.get("uploader") or info.get("channel") or ""
    sec_uid = info.get("channel_id") or ""
    if name and sec_uid:
        remember_tiktok_user(str(name).lstrip("@"), str(sec_uid), cache_path)


def write_entries_csv(path, entries):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for entry in entries:
            writer.writerow([entry["url"]])
    return path


def _ydl_opts(cookies_browser="", quiet=True):
    opts = {
        "quiet": quiet,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": False,
        "extract_flat": False,
    }
    spec = cookies_browser or ""
    if spec:
        browser, _, profile = spec.partition(":")
        opts["cookiesfrombrowser"] = (browser, profile or None, None, None)
    return opts


def _extract(ydl_cls, url, opts, should_stop):
    check_stop(should_stop)
    ydl_cls = ydl_cls or _youtube_dl()
    with ydl_cls(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _youtube_dl():
    from yt_dlp import YoutubeDL
    return YoutubeDL


# Reading a whole feed means one request per item; TikTok in particular answers
# a burst with a page that has no video data ("universal data for rehydration").
METADATA_ATTEMPTS = 3
RETRY_PAUSE = 1.5


def _extract_detail(ydl_cls, url, opts, should_stop, *, sleep=time.sleep):
    """Extract one item, retrying with a pause when the site throttles us."""
    for attempt in range(1, METADATA_ATTEMPTS + 1):
        check_stop(should_stop)
        try:
            detail = _extract(ydl_cls, url, opts, should_stop)
        except StopRequested:
            raise
        except Exception:
            detail = None
        if detail:
            return detail
        if attempt < METADATA_ATTEMPTS:
            sleep(RETRY_PAUSE * attempt)
    return None


def _has_metadata(item):
    """True when a flat listing entry is already good enough for the table."""
    title = collapse_text(item.get("title"))
    return bool(title and (item.get("uploader") or item.get("channel")))


def _flatten_entries(info, source_url):
    if not info:
        return []
    if info.get("_type") == "playlist":
        found = []
        for item in info.get("entries") or []:
            if not item:
                continue
            found.append(item)
        return found
    return [info]


def _tiktok_feed_url(url, log, cache_path=None):
    """Swap a TikTok profile URL for tiktokuser:<sec_uid> once we know the creator."""
    name = tiktok_username(url)
    if not name:
        return url
    sec_uid = cached_tiktok_sec_uid(name, cache_path)
    if not sec_uid:
        return url
    log(f"Listing @{name} by creator id.")
    return tiktok_user_feed(sec_uid)


def _feed_error(url, exc=None):
    name = tiktok_username(url)
    if name:
        return ValueError(TIKTOK_PROFILE_HELP.format(name=name))
    detail = str(exc).strip() if exc else ""
    return ValueError(detail or "No videos found at that URL.")


def _push_entries(on_entries, entries):
    if on_entries and entries:
        on_entries(list(entries))


def _collect_ytdlp(
    url, *, log, should_stop, cookies_browser="", ydl_cls=None, sleep=time.sleep,
    cache_path=None, feed=None, on_entries=None,
):
    kind = classify_source(url) if feed is None else (FEED if feed else SINGLE)
    opts = _ydl_opts(cookies_browser)
    if kind == FEED:
        url = _tiktok_feed_url(url, log, cache_path)
        opts["extract_flat"] = "in_playlist"
        log("Listing videos…")
        try:
            info = _extract(ydl_cls, url, opts, should_stop)
        except StopRequested:
            raise
        except Exception as exc:
            raise _feed_error(url, exc) from exc
        raw = _flatten_entries(info, url)
        if not raw:
            raise _feed_error(url)
        for item in raw:
            _remember_from_info(item, cache_path)
        pending = sum(1 for item in raw if not _has_metadata(item))
        log(
            f"Found {len(raw)} item(s). Fetching titles for {pending}…"
            if pending else f"Found {len(raw)} item(s)."
        )
        entries = []
        full_opts = _ydl_opts(cookies_browser)
        full_opts["extract_flat"] = False
        full_opts["noplaylist"] = True
        done = 0
        for index, item in enumerate(raw, start=1):
            check_stop(should_stop)
            item_url = item.get("webpage_url") or item.get("url") or ""
            extractor = (item.get("ie_key") or item.get("extractor_key") or "").lower()
            if (not item_url or not str(item_url).startswith("http")) and "youtube" in extractor and item.get("id"):
                item_url = f"https://www.youtube.com/watch?v={item['id']}"
            if not item_url or not str(item_url).startswith("http"):
                continue
            # TikTok and YouTube listings already carry title/uploader; asking for
            # each video again only earns a rate limit.
            if _has_metadata(item):
                entry = entry_from_info(item, item_url)
                entries.append(entry)
                _push_entries(on_entries, [entry])
                continue
            detail = _extract_detail(
                ydl_cls, item_url, full_opts, should_stop, sleep=sleep,
            )
            done += 1
            if detail:
                _remember_from_info(detail, cache_path)
                entry = entry_from_info(detail, item_url)
            else:
                log(f"[{index}/{len(raw)}] no metadata (throttled); keeping the link.")
                entry = entry_from_info(item, item_url)
            entries.append(entry)
            _push_entries(on_entries, [entry])
            if done == 1 or done % 10 == 0 or done == pending:
                log(f"Metadata {done}/{pending}")
        return _unique_entries(entries)

    log("Reading post info…")
    # A watch URL can carry a playlist; collecting one post must stay one post.
    opts["noplaylist"] = True
    info = _extract(ydl_cls, url, opts, should_stop)
    items = _flatten_entries(info, url)
    for item in items:
        _remember_from_info(item, cache_path)
    entries = [entry_from_info(item, url) for item in items if item]
    entries = _unique_entries(entries)
    _push_entries(on_entries, entries)
    return entries


def _unique_entries(entries):
    found, seen = [], set()
    for entry in entries:
        url = entry.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        found.append(entry)
    return found


def collect_entries(
    channel,
    url,
    *,
    log=print,
    wait_for_login=None,
    should_stop=None,
    output_root=None,
    chrome_binary="",
    cookies_browser="",
    ydl_cls=None,
    sleep=time.sleep,
    cache_path=None,
    feed=None,
    on_entries=None,
):
    """Collect entries and write <output_root>/<channel>.csv. Returns (csv_path, entries).

    `feed` overrides the URL-based guess: True lists a playlist, False keeps a
    single post even when the link also names a list. `on_entries` receives
    each batch as soon as it is known so the GUI can sync the Grabber table.
    """
    output_root = output_root or default_output_root()
    url = normalize_source_url(url)
    strategy = collection_strategy(url)
    if strategy == "unsupported":
        platform = detect_platform(url)
        raise ValueError(UNSUPPORTED_FEED_MESSAGES.get(platform, "This feed URL is not supported."))
    if strategy == "selenium":
        streamed = []

        def push_urls(urls):
            batch = [entry_from_url(item) for item in urls]
            streamed.extend(batch)
            _push_entries(on_entries, batch)

        csv_path = scrape_reel_urls(
            channel,
            url,
            log=log,
            wait_for_login=wait_for_login,
            should_stop=should_stop,
            output_root=output_root,
            chrome_binary=chrome_binary,
            on_urls=push_urls,
        )
        entries = _unique_entries(streamed) or [
            entry_from_url(item) for item in read_urls(csv_path)
        ]
        if on_entries and not streamed and entries:
            on_entries(entries)
        return csv_path, entries

    entries = _collect_ytdlp(
        url, log=log, should_stop=should_stop,
        cookies_browser=cookies_browser, ydl_cls=ydl_cls, sleep=sleep,
        cache_path=cache_path, feed=feed, on_entries=on_entries,
    )
    csv_path = os.path.join(output_root, f"{channel}.csv")
    write_entries_csv(csv_path, entries)
    log(f"Collected {len(entries)} item(s).")
    return csv_path, entries
