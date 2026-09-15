"""URL cleaning, platform detection, and source classification."""
import re
from urllib.parse import parse_qs, parse_qsl, unquote, urlparse, urlunparse

FACEBOOK_HOSTS = ("facebook.com", "fb.com")
INSTAGRAM_HOSTS = ("instagram.com",)
TIKTOK_HOSTS = ("tiktok.com",)
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
TWITTER_HOSTS = ("x.com", "twitter.com", "t.co")
BILIBILI_HOSTS = ("bilibili.tv", "bilibili.com", "b23.tv")
BILIBILI_TRACKING = ("bstar_from", "spm_id_from", "from_spmid", "vd_source", "from")
INSTAGRAM_TRACKING = (
    "hl", "igsh", "igshid", "img_index", "e", "s",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid",
)
INSTAGRAM_SINGLE_KINDS = ("p", "reel", "tv")
INSTAGRAM_FEED_TABS = ("reels", "reposts", "tagged")
DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com")
KUAISHOU_HOSTS = ("kuaishou.com", "gifshow.com", "kwai.com")
PINTEREST_HOSTS = ("pinterest.com", "pin.it")
PINTEREST_RESERVED = frozenset({
    "pin", "ideas", "search", "today", "news", "settings", "resource",
})
DOUYIN_USER_PREFIX = "douyinuser:"

REELS_SEGMENTS = {"reel", "reels", "videos"}

# TikTok profile pages are often blocked, but yt-dlp can list a creator from the
# secondary user id ("sec_uid") that every one of their videos carries.
TIKTOK_USER_PREFIX = "tiktokuser:"
TIKTOK_SEC_UID_PREFIX = "MS4wLjAB"

SINGLE = "single"
FEED = "feed"
FACEBOOK_REELS_FEED = "facebook_reels_feed"
UNSUPPORTED_FEED = "unsupported_feed"

UNSUPPORTED_FEED_MESSAGES = {
    "douyin": "Douyin feeds are not supported. Paste a video URL, a jingxuan link with modal_id, or a profile / sec_user_id.",
}

URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>'\"\]\[{}]+", re.IGNORECASE)


def extract_supported_urls(text):
    """Extract unique supported social URLs from clipboard/plain text."""
    found = []
    seen = set()
    for match in URL_IN_TEXT_RE.findall(text or ""):
        candidate = match.rstrip(".,;:!?)]}")
        if detect_platform(candidate) == "unknown":
            continue
        try:
            candidate = normalize_source_url(candidate)
        except ValueError:
            continue
        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    return found


def clean_url(url):
    """Strip whitespace and any quote characters the shell left in the string."""
    return url.strip().replace('"', "").replace("'", "").strip()


def _with_scheme(url):
    url = clean_url(url)
    if not url:
        raise ValueError("No URL given.")
    if "://" not in url:
        url = "https://" + url
    return url


def _host(url):
    host = urlparse(_with_scheme(url) if "://" not in clean_url(url) else clean_url(url) or url).netloc.lower()
    return host.split(":")[0].removeprefix("www.").removeprefix("m.").removeprefix("music.")


def _matches_host(host, suffixes):
    return any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)


def _segments(path):
    return [part for part in path.split("/") if part]


def is_tiktok_user_feed(url):
    return clean_url(url).lower().startswith(TIKTOK_USER_PREFIX)


def tiktok_user_feed(sec_uid):
    """Build the yt-dlp input that lists every video of a TikTok creator."""
    return f"{TIKTOK_USER_PREFIX}{clean_url(sec_uid)}"


def tiktok_username(url):
    """Return the @name of a TikTok profile or video URL, without the @."""
    if detect_platform(url) != "tiktok" or is_tiktok_user_feed(url):
        return ""
    segments = _segments(urlparse(_with_scheme(url)).path)
    if segments and segments[0].startswith("@"):
        name = segments[0][1:]
        return "" if name.startswith(TIKTOK_SEC_UID_PREFIX) else name
    return ""


def tiktok_sec_uid(url):
    """Return the sec_uid carried by a tiktokuser: input or an @MS4… URL."""
    url = clean_url(url)
    if is_tiktok_user_feed(url):
        return url[len(TIKTOK_USER_PREFIX):].strip()
    if detect_platform(url) != "tiktok":
        return ""
    segments = _segments(urlparse(_with_scheme(url)).path)
    if segments and segments[0].startswith("@" + TIKTOK_SEC_UID_PREFIX):
        return segments[0][1:]
    return ""


def is_douyin_user_feed(url):
    text = clean_url(url)
    return text.lower().startswith(DOUYIN_USER_PREFIX)


def douyin_user_feed(sec_uid):
    sec_uid = clean_url(sec_uid).removeprefix(DOUYIN_USER_PREFIX)
    return f"https://www.douyin.com/user/{sec_uid}"


def detect_platform(url):
    """Return a named site, generic for other http hosts, or unknown."""
    if is_tiktok_user_feed(url):
        return "tiktok"
    if is_douyin_user_feed(url):
        return "douyin"
    raw = clean_url(url)
    if raw.isdigit():
        return "facebook"
    try:
        host = _host(url)
    except ValueError:
        return "unknown"
    if _matches_host(host, FACEBOOK_HOSTS):
        return "facebook"
    if _matches_host(host, INSTAGRAM_HOSTS):
        return "instagram"
    if _matches_host(host, TIKTOK_HOSTS) or host.startswith("vm.tiktok.") or host.startswith("vt.tiktok."):
        return "tiktok"
    if _matches_host(host, YOUTUBE_HOSTS):
        return "youtube"
    if _matches_host(host, TWITTER_HOSTS):
        return "twitter"
    if _matches_host(host, BILIBILI_HOSTS):
        return "bilibili"
    if _matches_host(host, DOUYIN_HOSTS):
        return "douyin"
    if _matches_host(host, KUAISHOU_HOSTS) or host.startswith("v.kuaishou."):
        return "kuaishou"
    if _matches_host(host, PINTEREST_HOSTS):
        return "pinterest"
    if "." in host:
        return "generic"
    return "unknown"


def _classify_facebook(parts):
    segments = _segments(parts.path)
    lowered = [s.lower() for s in segments]
    query = {k.lower(): v for k, v in parse_qsl(parts.query)}
    if "reel" in lowered:
        index = lowered.index("reel")
        if index + 1 < len(lowered):
            return SINGLE
    if "videos" in lowered:
        index = lowered.index("videos")
        if index + 1 < len(lowered) and lowered[index + 1].isdigit():
            return SINGLE
    if lowered and lowered[0] == "watch" and query.get("v"):
        return SINGLE
    if lowered and lowered[0] in ("posts", "permalink.php", "photo.php", "share"):
        return SINGLE
    if "groups" in lowered:
        return FEED
    if "photo" in lowered or "photos" in lowered:
        return SINGLE
    if "reels" in lowered or query.get("sk") == "reels_tab":
        return FACEBOOK_REELS_FEED
    if query.get("sk") and query.get("sk") != "reels_tab":
        return FACEBOOK_REELS_FEED
    if lowered and lowered[0] in ("profile.php", "people"):
        return FACEBOOK_REELS_FEED
    if len(lowered) <= 1:
        return FACEBOOK_REELS_FEED
    return FACEBOOK_REELS_FEED


def _classify_instagram(parts):
    segments = [s.lower() for s in _segments(parts.path)]
    if not segments:
        return FEED
    if segments[0] == "stories":
        return SINGLE
    if segments[0] in INSTAGRAM_SINGLE_KINDS:
        return SINGLE
    # /reels/CODE is a share URL; /username/reels is a profile tab (FEED).
    if segments[0] == "reels" and len(segments) >= 2:
        return SINGLE
    if len(segments) >= 3 and segments[1] in INSTAGRAM_SINGLE_KINDS:
        return SINGLE
    return FEED


def _classify_tiktok(parts):
    host = parts.netloc.lower().split(":")[0]
    if host.startswith("vm.tiktok.") or host.startswith("vt.tiktok.") or host == "vm.tiktok.com":
        return SINGLE
    segments = [s.lower() for s in _segments(parts.path)]
    if "video" in segments or "photo" in segments:
        return SINGLE
    if segments and segments[0] in ("tag", "music", "effect"):
        return UNSUPPORTED_FEED
    if segments and segments[0].startswith("@"):
        return FEED
    return SINGLE


def youtube_watch_with_list(url):
    """Return (video_url, list_url) when a YouTube link holds a video and a list.

    A mix (list=RD…) is only viewable through its seed video, so the list URL
    keeps ?v= in that case; ordinary playlists open on their own page.
    """
    if detect_platform(url) != "youtube":
        return ()
    parts = urlparse(_with_scheme(url))
    query = parse_qs(parts.query)
    list_id = (query.get("list") or [""])[0].strip()
    video_id = (query.get("v") or [""])[0].strip()
    host = parts.netloc.lower().split(":")[0].removeprefix("www.").removeprefix("m.")
    segments = _segments(parts.path)
    if host == "youtu.be" and segments:
        video_id = video_id or segments[0]
    elif segments and segments[0].lower() in ("shorts", "live", "embed") and len(segments) > 1:
        video_id = video_id or segments[1]
    if not list_id or not video_id:
        return ()
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    if list_id.upper().startswith("RD"):
        list_url = f"{video_url}&list={list_id}"
    else:
        list_url = f"https://www.youtube.com/playlist?list={list_id}"
    return (video_url, list_url)


def _classify_youtube(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return SINGLE
    segments = [s.lower() for s in _segments(parts.path)]
    query = parse_qs(parts.query)
    if segments and segments[0] in ("watch", "shorts", "embed", "live"):
        return SINGLE
    if query.get("v"):
        return SINGLE
    if query.get("list") or (segments and segments[0] == "playlist"):
        return FEED
    if segments and (segments[0] in ("channel", "c", "user", "feeds") or segments[0].startswith("@")):
        return FEED
    return FEED


def _drop_bilibili_tracking(url):
    """Keep the video id; drop homepage/recommend tracking on bilibili.tv."""
    parts = urlparse(url)
    kept = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in BILIBILI_TRACKING
    ]
    query = "&".join(f"{key}={value}" if value else key for key, value in kept)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, query, ""))


def _classify_bilibili(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "b23.tv" or host.endswith(".b23.tv"):
        return SINGLE
    if host.startswith("space."):
        return FEED
    segments = [s.lower() for s in _segments(parts.path)]
    if segments and segments[0].isalpha() and len(segments[0]) <= 3 and len(segments) > 1:
        segments = segments[1:]
    if segments and segments[0] in ("video", "play", "bangumi", "festival"):
        return SINGLE
    if "video" in segments or "play" in segments:
        return SINGLE
    if segments and segments[0] in ("space", "medialist", "list"):
        return FEED
    return SINGLE


def _rewrite_douyin_url(url):
    """Turn overlay / query profile links into canonical Douyin video or user URLs."""
    if is_douyin_user_feed(url):
        return douyin_user_feed(url[len(DOUYIN_USER_PREFIX):])
    parts = urlparse(url)
    query = parse_qs(parts.query)
    modal = (query.get("modal_id") or [""])[0].strip()
    if modal:
        return f"https://www.douyin.com/video/{modal}"
    sec = (query.get("sec_user_id") or query.get("sec_uid") or [""])[0].strip()
    if sec:
        return douyin_user_feed(sec)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, "", ""))


def _classify_douyin(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host.startswith("v.douyin.") or host.endswith("iesdouyin.com"):
        return SINGLE
    if parse_qs(parts.query).get("modal_id"):
        return SINGLE
    query = parse_qs(parts.query)
    if query.get("sec_user_id") or query.get("sec_uid"):
        return FEED
    segments = [s.lower() for s in _segments(parts.path)]
    if segments and segments[0] in ("video", "note", "share"):
        return SINGLE
    if segments and segments[0] == "user":
        return FEED
    if segments and segments[0] in ("jingxuan", "recommend", "discover", "hashtag", "search", "channel"):
        return UNSUPPORTED_FEED
    return SINGLE


def _classify_twitter(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "t.co":
        return SINGLE
    segments = [s.lower() for s in _segments(parts.path)]
    if "status" in segments:
        return SINGLE
    if "i" in segments and "broadcasts" in segments:
        return SINGLE
    if segments:
        return FEED
    return SINGLE


def _classify_kuaishou(parts):
    host = parts.netloc.lower().split(":")[0]
    if host.startswith("v.kuaishou."):
        return SINGLE
    segments = [s.lower() for s in _segments(parts.path)]
    if any(name in segments for name in ("short-video", "shortvideo", "photo", "f")):
        return SINGLE
    if segments and segments[0] in ("profile", "user"):
        return FEED
    return SINGLE


def _classify_pinterest(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "pin.it" or host.endswith(".pin.it"):
        return SINGLE
    segments = [unquote(s).lower() for s in _segments(parts.path)]
    if not segments or segments[0] in PINTEREST_RESERVED:
        return SINGLE
    return FEED


def classify_source(url):
    """Return single, feed, facebook_reels_feed, or unsupported_feed."""
    if is_tiktok_user_feed(url):
        return FEED
    if is_douyin_user_feed(url):
        return FEED
    url = _with_scheme(url)
    platform = detect_platform(url)
    parts = urlparse(url)
    if platform == "facebook":
        return _classify_facebook(parts)
    if platform == "instagram":
        return _classify_instagram(parts)
    if platform == "tiktok":
        return _classify_tiktok(parts)
    if platform == "youtube":
        return _classify_youtube(parts)
    if platform == "twitter":
        return _classify_twitter(parts)
    if platform == "bilibili":
        return _classify_bilibili(parts)
    if platform == "douyin":
        return _classify_douyin(parts)
    if platform == "kuaishou":
        return _classify_kuaishou(parts)
    if platform == "pinterest":
        return _classify_pinterest(parts)
    return SINGLE


def collection_strategy(url):
    """selenium for Facebook/Instagram feeds (yt-dlp first, Chrome if that fails)."""
    kind = classify_source(url)
    if kind == FACEBOOK_REELS_FEED:
        return "selenium"
    if kind == FEED and detect_platform(url) == "instagram":
        return "selenium"
    if kind == UNSUPPORTED_FEED:
        return "unsupported"
    return "ytdlp"


def instagram_ytdlp_list_url(url):
    """URL InstagramUserIE can list, or None when yt-dlp must be skipped.

    Bare /username/ is passed through. /username/reels is rewritten to the
    profile (yt-dlp has no reels-tab extractor). /username/reposts and
    /username/tagged stay off yt-dlp so a profile listing is never treated
    as that tab's content.
    """
    if detect_platform(url) != "instagram":
        return url
    parts = urlparse(_with_scheme(url))
    segments = _segments(parts.path)
    if len(segments) >= 2 and segments[1].lower() in INSTAGRAM_FEED_TABS:
        if segments[1].lower() == "reels":
            path = f"/{segments[0]}/"
            return urlunparse((parts.scheme, parts.netloc, path, "", "", ""))
        return None
    return url


def _drop_instagram_tracking(url):
    """Keep profile/tab paths; drop locale and share-tracking query keys."""
    parts = urlparse(url)
    kept = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in INSTAGRAM_TRACKING
    ]
    query = "&".join(f"{key}={value}" if value else key for key, value in kept)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, query, ""))


def _rewrite_youtube_channel(url):
    parts = urlparse(url)
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "youtu.be":
        return url
    segments = _segments(parts.path)
    if parse_qs(parts.query).get("list") or (segments and segments[0].lower() == "playlist"):
        return url
    if segments and segments[0].lower() in ("watch", "shorts", "embed", "live"):
        return url
    if not segments:
        return url
    head = segments[0]
    if head.startswith("@") or head.lower() in ("channel", "c", "user"):
        tabs = {"videos", "shorts", "streams", "playlists", "releases"}
        if len(segments) == 1 or (len(segments) >= 2 and segments[-1].lower() not in tabs):
            if head.startswith("@") and len(segments) == 1:
                path = f"/{head}/videos"
                return urlunparse((parts.scheme, parts.netloc, path, parts.params, parts.query, parts.fragment))
            if head.lower() in ("channel", "c", "user") and len(segments) == 2:
                path = f"/{segments[0]}/{segments[1]}/videos"
                return urlunparse((parts.scheme, parts.netloc, path, parts.params, parts.query, parts.fragment))
    return url


def normalize_source_url(url):
    """Clean a pasted URL and apply platform-specific repairs. Raises ValueError."""
    if is_tiktok_user_feed(url):
        sec_uid = tiktok_sec_uid(url)
        if not sec_uid:
            raise ValueError("Add the creator's sec_uid after tiktokuser:.")
        return tiktok_user_feed(sec_uid)
    if is_douyin_user_feed(url):
        sec_uid = clean_url(url)[len(DOUYIN_USER_PREFIX):].strip()
        if not sec_uid:
            raise ValueError("Add the creator's sec_user_id after douyinuser:.")
        return douyin_user_feed(sec_uid)
    raw = clean_url(url)
    if raw.isdigit():
        url = f"https://www.facebook.com/profile.php?id={raw}"
    url = _with_scheme(url)
    platform = detect_platform(url)
    if platform == "unknown":
        raise ValueError(
            "Unsupported site. Paste a video, reel, board, or page URL."
        )
    if platform == "facebook":
        url = normalize_channel_url(url)
    elif platform == "youtube":
        url = _rewrite_youtube_channel(url)
    elif platform == "instagram":
        url = _drop_instagram_tracking(url)
    elif platform == "bilibili":
        url = _drop_bilibili_tracking(url)
    elif platform == "douyin":
        url = _rewrite_douyin_url(url)
    elif platform == "pinterest":
        url = _normalize_pinterest_url(url)
    kind = classify_source(url)
    if kind == UNSUPPORTED_FEED:
        raise ValueError(UNSUPPORTED_FEED_MESSAGES.get(platform, "This feed URL is not supported."))
    return url


def normalize_channel_url(url):
    """Return a URL pointing at the channel's reels tab.

    Repairs the two things that go wrong in practice: stray quotes from shell
    escaping, and a profile URL whose "&sk=reels_tab" was eaten by the shell.
    Raises ValueError if the string is not a Facebook URL.
    """
    url = _with_scheme(url)
    parts = urlparse(url)
    host = parts.netloc.lower().split(":")[0]
    if not any(host == h or host.endswith("." + h) for h in FACEBOOK_HOSTS):
        raise ValueError(f"Not a Facebook URL: {url}")

    path, query = parts.path, parts.query
    segments = [s for s in path.split("/") if s]
    lowered = {s.lower() for s in segments}

    # Already a reels URL, or the user picked a tab on purpose - leave it alone.
    if lowered & REELS_SEGMENTS or "sk" in {k.lower() for k, _ in parse_qsl(query)}:
        return urlunparse(parts)

    if segments and segments[0].lower() in ("profile.php", "people"):
        query = f"{query}&sk=reels_tab" if query else "sk=reels_tab"
    elif len(segments) == 1:
        path = f"/{segments[0]}/reels"

    return urlunparse((parts.scheme, parts.netloc, path, parts.params, query, parts.fragment))


def _normalize_pinterest_url(url):
    """Unquote path segments and drop an empty query so board slugs stay real."""
    parts = urlparse(url)
    raw = [part for part in parts.path.split("/") if part]
    segments = [unquote(part) for part in raw]
    path = "/" + "/".join(segments)
    if parts.path.endswith("/") and segments:
        path += "/"
    elif not segments:
        path = parts.path or "/"
    query = parts.query if parts.query else ""
    return urlunparse((parts.scheme, parts.netloc, path, "", query, ""))


def looks_shell_truncated(url):
    """True if the URL looks like a Facebook profile link that lost its "&..." to the shell."""
    url = clean_url(url)
    if "://" not in url:
        url = "https://" + url
    parts = urlparse(url)
    if not parts.query:
        return False
    keys = [k.lower() for k, _ in parse_qsl(parts.query)]
    return parts.path.lower().endswith("/profile.php") and keys == ["id"]
