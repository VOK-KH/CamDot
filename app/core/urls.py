"""URL cleaning, platform detection, and source classification."""
import re
from urllib.parse import parse_qs, parse_qsl, urlparse, urlunparse

FACEBOOK_HOSTS = ("facebook.com", "fb.com")
INSTAGRAM_HOSTS = ("instagram.com",)
TIKTOK_HOSTS = ("tiktok.com",)
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
TWITTER_HOSTS = ("x.com", "twitter.com", "t.co")

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
    "instagram": "Instagram profile feeds are not supported. Paste a post, reel, or TV URL instead.",
    "twitter": "X/Twitter timelines are not supported. Paste a post (status) URL instead.",
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


def detect_platform(url):
    """Return facebook, instagram, youtube, tiktok, twitter, or unknown."""
    if is_tiktok_user_feed(url):
        return "tiktok"
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
    if segments and segments[0] in ("p", "reel", "reels", "tv", "stories"):
        return SINGLE
    if len(segments) >= 2 and segments[1] in ("p", "reel", "reels", "tv"):
        return SINGLE
    return UNSUPPORTED_FEED


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
        return UNSUPPORTED_FEED
    return SINGLE


def classify_source(url):
    """Return single, feed, facebook_reels_feed, or unsupported_feed."""
    if is_tiktok_user_feed(url):
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
    return SINGLE


def collection_strategy(url):
    """selenium for Facebook reels feeds, ytdlp for everything else Collect can run."""
    kind = classify_source(url)
    if kind == FACEBOOK_REELS_FEED:
        return "selenium"
    if kind == UNSUPPORTED_FEED:
        return "unsupported"
    return "ytdlp"


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
    url = _with_scheme(url)
    platform = detect_platform(url)
    if platform == "unknown":
        raise ValueError(
            "Unsupported site. Paste a Facebook, Instagram, TikTok, YouTube, or X URL."
        )
    if platform == "facebook":
        url = normalize_channel_url(url)
    elif platform == "youtube":
        url = _rewrite_youtube_channel(url)
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
