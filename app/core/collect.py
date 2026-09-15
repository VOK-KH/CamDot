"""Collect post URLs and metadata: yt-dlp first for Facebook feeds, then Selenium."""
import csv
import json
import os
import time
from urllib.parse import unquote, urlparse

from app.core.download import (
    _pinterest_pin_duration,
    collapse_text,
    pinterest_resource,
    read_urls,
    reel_id,
)
from app.core.jobs import StopRequested, check_stop
from app.core.runtime import collect_csv_path, default_output_root, state_dir
from app.core.scrape import scrape_reel_urls
from app.core.urls import (
    FEED,
    PINTEREST_RESERVED,
    SINGLE,
    TIKTOK_SEC_UID_PREFIX,
    UNSUPPORTED_FEED,
    UNSUPPORTED_FEED_MESSAGES,
    classify_source,
    collection_strategy,
    detect_platform,
    instagram_ytdlp_list_url,
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
    if "bili" in key:
        return "bilibili"
    for name in ("facebook", "instagram", "youtube", "tiktok", "twitter", "douyin", "kuaishou", "pinterest"):
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


def _ydl_opts(cookies_browser="", quiet=True, cookies_file="", dateafter=""):
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
    if cookies_file:
        opts["cookiefile"] = cookies_file
    if dateafter:
        try:
            from yt_dlp.utils import DateRange
            opts["daterange"] = DateRange(dateafter, "99991231")
        except Exception:
            pass
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
    cache_path=None, feed=None, on_entries=None, cookies_file="", dateafter="",
):
    kind = classify_source(url) if feed is None else (FEED if feed else SINGLE)
    after = dateafter if detect_platform(url) == "tiktok" else ""
    opts = _ydl_opts(cookies_browser, cookies_file=cookies_file, dateafter=after)
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
        full_opts = _ydl_opts(cookies_browser, cookies_file=cookies_file, dateafter=after)
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


def _pinterest_path_segments(url):
    return [unquote(part) for part in urlparse(url).path.split("/") if part]


def _entry_from_pinterest_pin(item):
    pin_id = str(item.get("id") or "").strip()
    if not pin_id:
        return None
    title = collapse_text(item.get("grid_title") or item.get("title"))
    description = collapse_text(
        item.get("description") or item.get("seo_description") or title
    )
    return entry_from_url(
        f"https://www.pinterest.com/pin/{pin_id}/",
        id=pin_id,
        title=title,
        description=description,
        duration=_pinterest_pin_duration(item),
        platform="pinterest",
        extractor_key="Pinterest",
        webpage_url_domain="pinterest.com",
    )


def _collect_pinterest_page(resource, options, bookmark, should_stop):
    check_stop(should_stop)
    query = dict(options)
    if bookmark:
        query["bookmarks"] = [bookmark]
    page = pinterest_resource(resource, query)
    items = page.get("data")
    if not isinstance(items, list):
        items = []
    return items, page.get("bookmark")


def _collect_pinterest_feed(url, *, log, should_stop, on_entries=None):
    """Paginate BoardFeed or UserPins; keep image-only pins."""
    segments = _pinterest_path_segments(url)
    if not segments or segments[0].lower() in PINTEREST_RESERVED:
        raise ValueError("Not a Pinterest board or profile URL.")
    username = segments[0]
    if len(segments) >= 2:
        slug = segments[1]
        log("Listing Pinterest board…")
        board = pinterest_resource("Board", {"slug": slug, "username": username})
        data = board.get("data") if isinstance(board, dict) else None
        board_id = (data or {}).get("id") if isinstance(data, dict) else None
        if not board_id:
            raise ValueError("Pinterest board was not found.")
        resource = "BoardFeed"
        options = {"board_id": board_id, "page_size": 250}
    else:
        log("Listing Pinterest profile pins…")
        resource = "UserPins"
        options = {"username": username, "page_size": 250}

    bookmark = None
    entries = []
    while True:
        items, bookmark = _collect_pinterest_page(resource, options, bookmark, should_stop)
        batch = []
        for item in items:
            if not isinstance(item, dict) or item.get("type") != "pin":
                continue
            entry = _entry_from_pinterest_pin(item)
            if entry:
                batch.append(entry)
        if batch:
            entries.extend(batch)
            _push_entries(on_entries, batch)
        if not bookmark:
            break
    if not entries:
        raise ValueError("No pins found at that Pinterest URL.")
    log(f"Found {len(entries)} pin(s).")
    return _unique_entries(entries)


def _unique_entries(entries):
    found, index = [], {}
    for entry in entries:
        url = entry.get("url")
        if not url:
            continue
        if url in index:
            current = found[index[url]]
            for key in ("title", "description", "uploader", "duration"):
                if entry.get(key) and not current.get(key):
                    current[key] = entry[key]
            continue
        index[url] = len(found)
        found.append(entry)
    return found


def _enrich_facebook_captions(
    entries, *, log, should_stop, cookies_browser="", cookies_file="",
    ydl_cls=None, sleep=time.sleep, on_entries=None,
):
    """Fill empty Facebook titles with yt-dlp captions after the Chrome scrape."""
    pending = [
        entry for entry in entries
        if not collapse_text(entry.get("title")) and not collapse_text(entry.get("description"))
    ]
    if not pending:
        return entries
    log(f"Fetching captions for {len(pending)} Facebook reel(s)…")
    opts = _ydl_opts(cookies_browser, cookies_file=cookies_file)
    opts["noplaylist"] = True
    done = 0
    for entry in pending:
        check_stop(should_stop)
        detail = _extract_detail(ydl_cls, entry["url"], opts, should_stop, sleep=sleep)
        done += 1
        if detail:
            filled = entry_from_info(detail, entry["url"])
            for key in ("title", "description", "uploader", "duration"):
                if filled.get(key) and not entry.get(key):
                    entry[key] = filled[key]
            _push_entries(on_entries, [entry])
        if done == 1 or done % 10 == 0 or done == len(pending):
            log(f"Captions {done}/{len(pending)}")
    return entries


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
    cookies_file="",
    dateafter="",
):
    """Collect entries and write AppData collect/<channel>.csv. Returns (csv_path, entries).

    `feed` overrides the URL-based guess: True lists a playlist, False keeps a
    single post even when the link also names a list. `on_entries` receives
    each batch as soon as it is known so the GUI can sync the Grabber table.

    Facebook and Instagram feeds keep strategy ``selenium`` (Chrome may still
    open) but try yt-dlp first and only fall back to scrape_reel_urls when
    listing fails. Instagram /reposts is not listed by yt-dlp.
    """
    output_root = output_root or default_output_root()
    url = normalize_source_url(url)
    strategy = collection_strategy(url)
    if strategy == "unsupported":
        platform = detect_platform(url)
        raise ValueError(UNSUPPORTED_FEED_MESSAGES.get(platform, "This feed URL is not supported."))
    if strategy == "selenium":
        platform = detect_platform(url)
        site = "Instagram" if platform == "instagram" else "Facebook"
        ytdlp_feed = True if feed is None else feed
        list_url = instagram_ytdlp_list_url(url) if platform == "instagram" else url
        entries = None
        if list_url is None:
            log(f"yt-dlp cannot list that {site} tab; opening Chrome.")
        else:
            try:
                entries = _collect_ytdlp(
                    list_url, log=log, should_stop=should_stop,
                    cookies_browser=cookies_browser, ydl_cls=ydl_cls, sleep=sleep,
                    cache_path=cache_path, feed=ytdlp_feed, on_entries=on_entries,
                    cookies_file=cookies_file, dateafter=dateafter,
                )
            except StopRequested:
                raise
            except Exception as exc:
                detail = str(exc).strip()
                log(
                    f"yt-dlp found no {site} items; opening Chrome."
                    + (f" ({detail})" if detail else "")
                )
                entries = None
            else:
                if entries:
                    csv_path = collect_csv_path(channel)
                    write_entries_csv(csv_path, entries)
                    log(f"Collected {len(entries)} item(s) via yt-dlp; skipped Chrome.")
                    entries = _enrich_facebook_captions(
                        entries, log=log, should_stop=should_stop,
                        cookies_browser=cookies_browser, cookies_file=cookies_file,
                        ydl_cls=ydl_cls, sleep=sleep, on_entries=on_entries,
                    )
                    return csv_path, entries
                log(f"yt-dlp found no {site} items; opening Chrome.")

        streamed = []

        def push_urls(items):
            batch = []
            for item in items:
                if isinstance(item, str):
                    batch.append(entry_from_url(item))
                else:
                    batch.append(entry_from_url(
                        item.get("url"),
                        title=item.get("title"),
                        description=item.get("description") or item.get("title"),
                    ))
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
        entries = _enrich_facebook_captions(
            entries, log=log, should_stop=should_stop,
            cookies_browser=cookies_browser, cookies_file=cookies_file,
            ydl_cls=ydl_cls, sleep=sleep, on_entries=on_entries,
        )
        if on_entries and not streamed and entries:
            on_entries(entries)
        return csv_path, entries

    kind = classify_source(url) if feed is None else (FEED if feed else SINGLE)
    if detect_platform(url) == "pinterest" and kind == FEED:
        try:
            entries = _collect_pinterest_feed(
                url, log=log, should_stop=should_stop, on_entries=on_entries,
            )
        except StopRequested:
            raise
        except Exception as exc:
            detail = str(exc).strip()
            log(
                "Pinterest API failed; using yt-dlp."
                + (f" ({detail})" if detail else "")
            )
        else:
            csv_path = collect_csv_path(channel)
            write_entries_csv(csv_path, entries)
            log(f"Collected {len(entries)} item(s).")
            return csv_path, entries

    entries = _collect_ytdlp(
        url, log=log, should_stop=should_stop,
        cookies_browser=cookies_browser, ydl_cls=ydl_cls, sleep=sleep,
        cache_path=cache_path, feed=feed, on_entries=on_entries,
        cookies_file=cookies_file, dateafter=dateafter,
    )
    csv_path = collect_csv_path(channel)
    write_entries_csv(csv_path, entries)
    log(f"Collected {len(entries)} item(s).")
    return csv_path, entries
