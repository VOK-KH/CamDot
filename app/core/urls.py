"""URL cleaning, platform detection, and source classification."""
import os
import re
from urllib.parse import parse_qs, parse_qsl, unquote, urlparse, urlunparse

FACEBOOK_HOSTS = ("facebook.com", "fb.com", "fb.watch")
INSTAGRAM_HOSTS = ("instagram.com", "instagr.am")
TIKTOK_HOSTS = ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com")
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
TWITTER_HOSTS = ("x.com", "twitter.com", "t.co", "fxtwitter.com", "vxtwitter.com")
BILIBILI_HOSTS = ("bilibili.tv", "bilibili.com", "b23.tv")
BILITV_HOSTS = ("bilitv.com",)
BILIBILI_TRACKING = ("bstar_from", "spm_id_from", "from_spmid", "vd_source", "from")
INSTAGRAM_TRACKING = (
    "hl", "igsh", "igshid", "img_index", "e", "s",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid",
)
INSTAGRAM_SINGLE_KINDS = ("p", "reel", "tv")
INSTAGRAM_FEED_TABS = ("reels", "reposts", "tagged")
DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com", "v.douyin.com")
KWAI_HOSTS = ("kwai.com", "kwai-video.com", "kw.ai", "s.kw.ai")
SNACKVIDEO_HOSTS = ("snackvideo.com", "sck.io")
KUAISHOU_HOSTS = ("kuaishou.com", "gifshow.com", "v.kuaishou.com")
PINTEREST_HOSTS = ("pinterest.com", "pin.it")
XIAOHONGSHU_HOSTS = ("xiaohongshu.com", "xhslink.com")
MEDALTV_HOSTS = ("medal.tv",)
THREADS_HOSTS = ("threads.com", "threads.net")
SUNO_HOSTS = ("suno.com", "suno.ai")
REDDIT_HOSTS = ("reddit.com", "redd.it", "old.reddit.com", "v.redd.it", "i.redd.it")
DAILYMOTION_HOSTS = ("dailymotion.com", "dai.ly")
SNAPCHAT_HOSTS = ("snapchat.com",)
WEIBO_HOSTS = ("weibo.com", "weibo.cn")
TWITCH_HOSTS = ("twitch.tv",)

# Movie & Drama hosts
DRAMABOX_HOSTS = ("dramaboxdb.com", "dramabox.com", "dramaboxapp.com")
NETSHORT_HOSTS = ("netshort.com",)
FLICKREELS_HOSTS = ("flickreels.net", "flickreels.com")
STARDUSTTV_HOSTS = ("stardusttv.net",)
STARSHORT_HOSTS = ("starshort.tv",)
GOODSHORT_HOSTS = ("goodshort.com",)
DRAMAWAVE_HOSTS = ("mydramawave.com", "dramawave.com")
FREEREELS_HOSTS = ("free-reels.com", "freereels.com")
REELSHORT_HOSTS = ("reelshort.com",)
HONGGUO_HOSTS = ("hongguoduanju.com",)
IDRAMA_HOSTS = ("idrama.video",)
WETV_HOSTS = ("wetv.vip", "v.qq.com")
IQIYI_HOSTS = ("iq.com", "iqiyi.com")
DRAMABITE_HOSTS = ("dramabite.media",)
VIGLOO_HOSTS = ("vigloo.com",)
KISSKH_HOSTS = ("kisskh.org", "kisskh.ovh", "kisskh.co", "kisskh.do", "kisskh.la", "kisskh.id", "kisskh.me")
FLEXTV_HOSTS = ("flextv.cc",)
MELOLO_HOSTS = ("melolo.org", "melolo.com")
KOLABKHMER_HOSTS = ("kolabkhmer.com",)

MOVIE_DRAMA_PLATFORMS = frozenset({
    "dramabox",
    "netshort",
    "flickreels",
    "stardusttv",
    "starshort",
    "goodshort",
    "dramawave",
    "freereels",
    "reelshort",
    "hongguo",
    "idrama",
    "bilitv",
    "wetv",
    "iqiyi",
    "dramabite",
    "vigloo",
    "kisskh",
    "flextv",
    "melolo",
    "kolabkhmer",
})

# Platforms without a native yt-dlp extractor: go straight to web_media.py.
WEB_FALLBACK_ONLY_PLATFORMS = (
    (MOVIE_DRAMA_PLATFORMS - {"wetv", "iqiyi", "bilitv"})
    | {"suno", "scraped"}
)

SCRAPED_MEDIA_EXTS = frozenset({
    ".mp4", ".m3u8", ".mpd", ".webm", ".mkv", ".mov", ".ts", ".flv", ".m4v",
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus",
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
})

PINTEREST_RESERVED = frozenset({
    "pin", "ideas", "search", "today", "news", "settings", "resource",
})
PINTEREST_RELATED_TAILS = frozenset({"related", "visual-search", "more-ideas"})
DOUYIN_USER_PREFIX = "douyinuser:"

REELS_SEGMENTS = {"reel", "reels", "videos"}
FACEBOOK_SINGLE_ROOTS = {
    "photo", "photo.php", "photos", "watch", "permalink.php", "posts", "share", "story.php",
}

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
    "tiktok": "Paste a TikTok video link or a creator profile (@name), not the site homepage.",
}

URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>'\"\]\[{}]+", re.IGNORECASE)


def _strip_trailing_url_punct(candidate):
    """Strip sentence punctuation after a URL while keeping balanced ``(...)``."""
    while candidate:
        last = candidate[-1]
        if last in ",;:!?]}":
            candidate = candidate[:-1]
            continue
        if last == ")":
            if candidate.count(")") > candidate.count("("):
                candidate = candidate[:-1]
                continue
            break
        if last == ".":
            candidate = candidate[:-1]
            continue
        break
    return candidate


def extract_supported_urls(text):
    """Extract unique supported social/drama/media URLs from clipboard/plain text."""
    found = []
    seen = set()
    for match in URL_IN_TEXT_RE.findall(text or ""):
        candidate = _strip_trailing_url_punct(match)
        if not is_supported_source(candidate):
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
    raw = clean_url(url)
    if "://" in raw and not raw.lower().startswith(("http://", "https://")):
        return ""
    host = urlparse(_with_scheme(raw) if "://" not in raw else raw or url).netloc.lower()
    return host.split(":")[0].removeprefix("www.").removeprefix("m.").removeprefix("music.")


def _matches_host(host, suffixes):
    return any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)


def _segments(path):
    return [part for part in path.split("/") if part]


def is_scraped_media_url(url):
    """True for direct media / manifest links captured by browser extensions."""
    raw = clean_url(url)
    if not raw:
        return False
    if "://" in raw and not raw.lower().startswith(("http://", "https://")):
        return False
    try:
        parts = urlparse(_with_scheme(raw))
    except ValueError:
        return False
    if "." not in parts.netloc:
        return False
    ext = os.path.splitext(unquote(parts.path or ""))[1].lower()
    if ext in SCRAPED_MEDIA_EXTS:
        return True
    query = parse_qs(parts.query)
    for key in ("mime", "content_type", "type"):
        for val in query.get(key) or ():
            lowered = val.lower()
            if lowered.startswith(("video/", "audio/", "image/", "application/vnd.apple.mpegurl", "application/dash+xml")):
                return True
    return False


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


_HOST_DETECTION_TABLE = (
    (FACEBOOK_HOSTS, "facebook"),
    (INSTAGRAM_HOSTS, "instagram"),
    (YOUTUBE_HOSTS, "youtube"),
    (TWITTER_HOSTS, "twitter"),
    (BILITV_HOSTS, "bilitv"),
    (BILIBILI_HOSTS, "bilibili"),
    (DOUYIN_HOSTS, "douyin"),
    (KWAI_HOSTS, "kwai"),
    (SNACKVIDEO_HOSTS, "snackvideo"),
    (KUAISHOU_HOSTS, "kuaishou"),
    (PINTEREST_HOSTS, "pinterest"),
    (XIAOHONGSHU_HOSTS, "xiaohongshu"),
    (MEDALTV_HOSTS, "medaltv"),
    (THREADS_HOSTS, "threads"),
    (SUNO_HOSTS, "suno"),
    (REDDIT_HOSTS, "reddit"),
    (DAILYMOTION_HOSTS, "dailymotion"),
    (SNAPCHAT_HOSTS, "snapchat"),
    (WEIBO_HOSTS, "weibo"),
    (TWITCH_HOSTS, "twitch"),
    (DRAMABOX_HOSTS, "dramabox"),
    (NETSHORT_HOSTS, "netshort"),
    (FLICKREELS_HOSTS, "flickreels"),
    (STARDUSTTV_HOSTS, "stardusttv"),
    (STARSHORT_HOSTS, "starshort"),
    (GOODSHORT_HOSTS, "goodshort"),
    (DRAMAWAVE_HOSTS, "dramawave"),
    (FREEREELS_HOSTS, "freereels"),
    (REELSHORT_HOSTS, "reelshort"),
    (HONGGUO_HOSTS, "hongguo"),
    (IDRAMA_HOSTS, "idrama"),
    (WETV_HOSTS, "wetv"),
    (IQIYI_HOSTS, "iqiyi"),
    (DRAMABITE_HOSTS, "dramabite"),
    (VIGLOO_HOSTS, "vigloo"),
    (KISSKH_HOSTS, "kisskh"),
    (FLEXTV_HOSTS, "flextv"),
    (MELOLO_HOSTS, "melolo"),
    (KOLABKHMER_HOSTS, "kolabkhmer"),
)


def detect_platform(url):
    """Return a named site, scraped for direct media links, generic for other http hosts, or unknown."""
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
    if not host:
        return "unknown"
    if _matches_host(host, TIKTOK_HOSTS) or host.startswith("vm.tiktok.") or host.startswith("vt.tiktok."):
        return "tiktok"
    if _matches_host(host, KUAISHOU_HOSTS) or host.startswith("v.kuaishou."):
        return "kuaishou"
    for suffixes, platform in _HOST_DETECTION_TABLE:
        if _matches_host(host, suffixes):
            return platform
    if is_scraped_media_url(url):
        return "scraped"
    if "." in host:
        return "generic"
    return "unknown"


def is_supported_source(url):
    """True when CamDot should extract or download this URL.

    Named hosts (Facebook, YouTube, DramaBox, …) and direct scraped media links
    are processed. Random non-media HTTPS hosts (`generic`) and non-URLs
    (`unknown`) are not queued.
    """
    return detect_platform(url) not in ("unknown", "generic")


def _classify_facebook(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "fb.watch" or host.endswith(".fb.watch"):
        return SINGLE
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
    if lowered and lowered[0] in ("posts", "permalink.php", "photo.php", "photo", "share", "story.php"):
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
    if not segments:
        return UNSUPPORTED_FEED
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


def _bilibili_play_segments(url):
    """Path segments after optional lang code for bilibili play/bangumi URLs."""
    if not clean_url(url):
        return []
    if detect_platform(url) not in ("bilibili", "bilitv"):
        return []
    parts = urlparse(_with_scheme(url))
    segments = [s for s in _segments(parts.path)]
    if segments and segments[0].isalpha() and len(segments[0]) <= 3 and len(segments) > 1:
        segments = segments[1:]
    return [s.lower() for s in segments]


def bilibili_play_ids(url):
    """Return ``(season_id, episode_id_or_None)`` for /play/ season pages."""
    segments = _bilibili_play_segments(url)
    if not segments:
        return "", ""
    if segments[0] == "play" and len(segments) >= 2 and segments[1].isdigit():
        season = segments[1]
        episode = segments[2] if len(segments) >= 3 and segments[2].isdigit() else ""
        return season, episode
    if segments[0] == "bangumi":
        rest = [s for s in segments[1:] if s != "play"]
        if rest and rest[0].startswith("ss") and rest[0][2:].isdigit():
            return rest[0][2:], ""
        if rest and rest[0].startswith("ep") and rest[0][2:].isdigit():
            return "", rest[0][2:]
    return "", ""


def is_bilibili_season_url(url):
    """True for bilibili.tv, wetv.vip, or hongguoduanju.com season/series URLs (not one episode)."""
    season, episode = bilibili_play_ids(url)
    if season and not episode:
        return True
    w_series, w_ep = wetv_play_ids(url)
    if w_series and not w_ep:
        return True
    h_series, h_ep = hongguo_play_ids(url)
    if h_series and not h_ep:
        return True
    d_book, d_chap = dramabox_play_ids(url)
    if d_book and not d_chap:
        return True
    g_book, g_chap = goodshort_play_ids(url)
    if g_book and not g_chap:
        return True
    return False


def is_bilibili_episode_url(url):
    """True for bilibili.tv ``/play/{season}/{episode}``."""
    season, episode = bilibili_play_ids(url)
    return bool(season and episode)


def wetv_play_ids(url):
    """Return ``(series_id, episode_id_or_empty)`` for wetv.vip ``/play/`` URLs."""
    if not clean_url(url) or detect_platform(url) != "wetv":
        return "", ""
    parts = urlparse(_with_scheme(url))
    segments = [s for s in _segments(parts.path)]
    if "play" not in [s.lower() for s in segments]:
        return "", ""
    idx = [s.lower() for s in segments].index("play")
    tail = segments[idx + 1:]
    if not tail:
        return "", ""
    series_id = tail[0].split("-", 1)[0].strip()
    episode_id = tail[1].split("-", 1)[0].strip() if len(tail) >= 2 else ""
    return series_id, episode_id


def hongguo_play_ids(url):
    """Return ``(series_id, episode_id_or_empty)`` for hongguoduanju.com URLs."""
    if not clean_url(url) or detect_platform(url) != "hongguo":
        return "", ""
    parts = urlparse(_with_scheme(url))
    query = parse_qs(parts.query)
    segments = [s for s in _segments(parts.path)]
    if segments and segments[0].lower() == "detail":
        series_id = (query.get("series_id") or [""])[0].strip()
        return series_id, ""
    if segments and segments[0].lower() == "player" and len(segments) >= 2:
        series_id = segments[1].strip()
        episode_id = segments[2].strip() if len(segments) >= 3 else ""
        return series_id, episode_id
    return "", ""


def dramabox_play_ids(url):
    """Return ``(book_id, chapter_id_or_empty)`` for dramaboxdb.com URLs."""
    if not clean_url(url) or detect_platform(url) != "dramabox":
        return "", ""
    parts = urlparse(_with_scheme(url))
    segments = [s for s in _segments(parts.path)]
    if len(segments) >= 2 and segments[0].lower() in ("movie", "drama", "book"):
        book_id = segments[1].split("_", 1)[0].split("-", 1)[0].strip()
        return book_id, ""
    if len(segments) >= 3 and segments[0].lower() == "ep":
        book_id = segments[1].split("_", 1)[0].strip()
        chapter_id = segments[2].split("_", 1)[0].strip()
        return book_id, chapter_id
    return "", ""


def goodshort_play_ids(url):
    """Return ``(book_slug_id, chapter_id_or_empty)`` for goodshort.com URLs."""
    if not clean_url(url) or detect_platform(url) != "goodshort":
        return "", ""
    parts = urlparse(_with_scheme(url))
    segments = [s for s in _segments(parts.path)]
    if len(segments) >= 2 and segments[0].lower() in ("drama", "episodes", "book"):
        return segments[1].strip(), ""
    if len(segments) >= 3 and segments[0].lower() == "episode":
        slug = segments[1].strip()
        chap = segments[2].split("-")[-1].strip()
        return slug, chap
    return "", ""


def flickreels_play_ids(url):
    """Return ``(playlet_id, episode_slug_or_empty)`` for flickreels.net URLs."""
    if not clean_url(url) or detect_platform(url) != "flickreels":
        return "", ""
    parts = urlparse(_with_scheme(url))
    segments = [s for s in _segments(parts.path)]
    if len(segments) >= 3 and segments[0].lower() == "playlist":
        playlet_id = segments[2].strip()
        ep_slug = segments[3].strip() if len(segments) >= 4 else ""
        return playlet_id, ep_slug
    if len(segments) >= 2 and segments[0].lower() in ("drama", "episodes-list"):
        playlet_id = segments[1].split("-")[-1].strip()
        return playlet_id, ""
    return "", ""


def _classify_bilibili(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "b23.tv" or host.endswith(".b23.tv"):
        return SINGLE
    if host.startswith("space."):
        return FEED
    segments = [s.lower() for s in _segments(parts.path)]
    if segments and segments[0].isalpha() and len(segments[0]) <= 3 and len(segments) > 1:
        segments = segments[1:]
    if not segments:
        return SINGLE
    head = segments[0]
    if head == "video" or head == "festival":
        return SINGLE
    if head == "play":
        # /play/{seasonId} is the series; /play/{seasonId}/{episodeId} is one ep.
        return FEED if len(segments) == 2 else SINGLE
    if head == "bangumi":
        rest = [s for s in segments[1:] if s != "play"]
        if rest and rest[0].startswith("ss"):
            return FEED
        if rest and rest[0].startswith("ep"):
            return SINGLE
        return SINGLE
    if "video" in segments:
        return SINGLE
    if "play" in segments:
        idx = segments.index("play")
        return FEED if len(segments) == idx + 2 else SINGLE
    if head in ("space", "medialist", "list"):
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
    if host.startswith("v.kuaishou.") or host.startswith("s.kw.ai") or host == "kw.ai" or host == "sck.io":
        return SINGLE
    segments = [s.lower() for s in _segments(parts.path)]
    if any(name in segments for name in ("short-video", "shortvideo", "photo", "f", "video", "p")):
        return SINGLE
    if segments and (segments[0] in ("profile", "user") or segments[0].startswith("@")):
        return FEED
    return SINGLE


def is_pinterest_search_url(url):
    """True for pinterest.com/search/... with a non-empty ?q= query."""
    if detect_platform(url) != "pinterest":
        return False
    parts = urlparse(_with_scheme(url))
    segments = [unquote(s).lower() for s in _segments(parts.path)]
    query = parse_qs(parts.query)
    q = (query.get("q") or query.get("query") or [""])[0].strip()
    return bool(segments and segments[0] == "search" and q)


def is_pinterest_related_url(url):
    """True for pinterest.com/pin/<id>/related (or ?related=1)."""
    if detect_platform(url) != "pinterest":
        return False
    parts = urlparse(_with_scheme(url))
    segments = [unquote(s).lower() for s in _segments(parts.path)]
    query = parse_qs(parts.query)
    if segments and segments[0] == "pin" and len(segments) >= 2:
        if len(segments) >= 3 and segments[2] in PINTEREST_RELATED_TAILS:
            return True
        if (query.get("related") or [""])[0].strip().lower() in ("1", "true", "yes"):
            return True
    return False


def _classify_pinterest(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "pin.it" or host.endswith(".pin.it"):
        return SINGLE
    segments = [unquote(s).lower() for s in _segments(parts.path)]
    query = parse_qs(parts.query)
    if segments and segments[0] == "search":
        q = (query.get("q") or query.get("query") or [""])[0].strip()
        return FEED if q else SINGLE
    if segments and segments[0] == "pin" and len(segments) >= 2:
        if len(segments) >= 3 and segments[2] in PINTEREST_RELATED_TAILS:
            return FEED
        if (query.get("related") or [""])[0].strip().lower() in ("1", "true", "yes"):
            return FEED
        return SINGLE
    if not segments or segments[0] in PINTEREST_RESERVED:
        return SINGLE
    return FEED


def _classify_suno(parts):
    segments = [s.lower() for s in _segments(parts.path)]
    if segments and (segments[0] == "playlist" or segments[0].startswith("@")):
        return FEED
    return SINGLE


def _classify_dailymotion(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "dai.ly" or host.endswith(".dai.ly"):
        return SINGLE
    segments = [s.lower() for s in _segments(parts.path)]
    if segments and segments[0] in ("video", "embed"):
        return SINGLE
    if segments and segments[0] == "playlist":
        return FEED
    return SINGLE


def _classify_threads(parts):
    segments = [s.lower() for s in _segments(parts.path)]
    if "post" in segments or "t" in segments:
        return SINGLE
    if segments and segments[0].startswith("@") and len(segments) == 1:
        return FEED
    return SINGLE


def _classify_xiaohongshu(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host == "xhslink.com" or host.endswith(".xhslink.com"):
        return SINGLE
    segments = [s.lower() for s in _segments(parts.path)]
    if "profile" in segments and "explore" not in segments and "discovery" not in segments:
        return FEED
    return SINGLE


_DRAMA_EPISODE_SEGMENTS = frozenset({
    "episode", "episodes", "ep", "chapter", "watch", "player", "video",
})
_DRAMA_SERIES_SEGMENTS = frozenset({
    "drama", "movie", "series", "book", "detail", "album", "show", "title", "tv", "program",
})
_DRAMA_EP_SLUG_RE = re.compile(r"(?:^|[-_/])(?:ep|episode|chapter)[-_]?\d+", re.I)


def _classify_movie_drama(parts):
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    segments = [s.lower() for s in _segments(parts.path)]
    query = {k.lower(): v for k, v in parse_qsl(parts.query)}
    if host == "wetv.vip" or host.endswith(".wetv.vip"):
        if "play" in segments:
            idx = segments.index("play")
            tail = segments[idx + 1:]
            return FEED if len(tail) == 1 else SINGLE
    if host == "hongguoduanju.com" or host.endswith(".hongguoduanju.com"):
        if segments and segments[0] == "detail" and query.get("series_id"):
            return FEED
        if segments and segments[0] == "player":
            return FEED if len(segments) == 2 else SINGLE
    if host == "goodshort.com" or host.endswith(".goodshort.com"):
        if segments and segments[0] in ("drama", "episodes"):
            return FEED
        if segments and segments[0] == "episode":
            return SINGLE
    if any(k in query for k in ("ep", "episode", "chapter", "episode_id", "chapter_id", "vid")):
        return SINGLE
    if _DRAMA_EP_SLUG_RE.search(parts.path or ""):
        return SINGLE
    if any(seg in _DRAMA_EPISODE_SEGMENTS for seg in segments):
        return SINGLE
    if "play" in segments:
        return SINGLE
    if any(seg in _DRAMA_SERIES_SEGMENTS for seg in segments):
        return FEED
    return SINGLE


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
    if platform in ("bilibili", "bilitv"):
        return _classify_bilibili(parts)
    if platform == "douyin":
        return _classify_douyin(parts)
    if platform in ("kuaishou", "kwai", "snackvideo"):
        return _classify_kuaishou(parts)
    if platform == "pinterest":
        return _classify_pinterest(parts)
    if platform == "suno":
        return _classify_suno(parts)
    if platform == "dailymotion":
        return _classify_dailymotion(parts)
    if platform == "threads":
        return _classify_threads(parts)
    if platform == "xiaohongshu":
        return _classify_xiaohongshu(parts)
    if platform in MOVIE_DRAMA_PLATFORMS:
        return _classify_movie_drama(parts)
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
    if platform in ("unknown", "generic"):
        raise ValueError(
            "Unsupported site. Paste a video, reel, board, drama, or media URL."
        )
    if platform == "facebook":
        url = normalize_channel_url(url)
    elif platform == "youtube":
        url = _rewrite_youtube_channel(url)
    elif platform == "instagram":
        url = _drop_instagram_tracking(url)
    elif platform in ("bilibili", "bilitv"):
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
    """Return a URL pointing at the channel's reels tab (or preserve single posts/photos).

    Repairs the two things that go wrong in practice: stray quotes from shell
    escaping, and a profile URL whose "&sk=reels_tab" was eaten by the shell.
    Raises ValueError if the string is not a Facebook URL.
    """
    url = _with_scheme(url)
    parts = urlparse(url)
    host = parts.netloc.lower().split(":")[0]
    if not any(host == h or host.endswith("." + h) for h in FACEBOOK_HOSTS):
        raise ValueError(f"Not a Facebook URL: {url}")
    if host == "fb.watch" or host.endswith(".fb.watch"):
        return urlunparse(parts)

    path, query = parts.path, parts.query
    segments = [s for s in path.split("/") if s]
    lowered = {s.lower() for s in segments}

    # Already a reels URL, a single photo/post/watch URL, or the user picked a tab on purpose.
    if (
        lowered & REELS_SEGMENTS
        or lowered & FACEBOOK_SINGLE_ROOTS
        or "sk" in {k.lower() for k, _ in parse_qsl(query)}
    ):
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
