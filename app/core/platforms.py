"""First-class and coming-soon host catalog (no widgets)."""

ACTIVE = "active"
COMING_SOON = "coming_soon"

PLATFORM_CATALOG = [
    # --- Social Network Sites ---
    {
        "id": "facebook",
        "name": "Facebook",
        "hosts": ("facebook.com", "fb.com", "fb.watch"),
        "status": ACTIVE,
        "icon": "platform-facebook",
        "features": [
            "Videos, Reels, and Photos (single posts and galleries)",
            "Page /reels and profiles: fast listing first, then Chrome login if needed",
            "Views: video, extract audio, and photo/thumbnail fallback",
            "Cookies from browser",
        ],
        "limits": [],
    },
    {
        "id": "instagram",
        "name": "Instagram",
        "hosts": ("instagram.com", "instagr.am"),
        "status": ACTIVE,
        "icon": "platform-instagram",
        "features": [
            "Reels, Photos, TV, and stories URLs",
            "Profile, /username/reels, and /username/reposts as feeds",
            "Reposts open Chrome when fast listing is not enough",
            "Photo post fallback when video stream is absent",
        ],
        "limits": [],
    },
    {
        "id": "pinterest",
        "name": "Pinterest",
        "hosts": ("pinterest.com", "pin.it"),
        "status": ACTIVE,
        "icon": "platform-pinterest",
        "features": [
            "Pins, Profile, Boards, Search (/search/pins/?q=…), and Related (/pin/<id>/related)",
            "Orig image when the pin has no video",
            "Video pins download as video",
        ],
        "limits": [],
    },
    {
        "id": "youtube",
        "name": "YouTube",
        "hosts": ("youtube.com", "youtu.be"),
        "status": ACTIVE,
        "icon": "platform-youtube",
        "features": [
            "Videos, Shorts, channels, playlists, and mixes",
            "A watch+list link asks for this video or the whole playlist",
            "Link Grabber takes the single video",
        ],
        "limits": [],
    },
    {
        "id": "tiktok",
        "name": "TikTok",
        "hosts": ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com"),
        "status": ACTIVE,
        "icon": "platform-tiktok",
        "features": [
            "Videos, photos, and creator profiles",
            "tiktokuser:<sec_uid> when a profile extract fails",
            "Optional age filter in Settings",
        ],
        "limits": [],
    },
    {
        "id": "douyin",
        "name": "Douyin",
        "hosts": ("douyin.com", "iesdouyin.com", "v.douyin.com"),
        "status": ACTIVE,
        "icon": "platform-douyin",
        "features": [
            "Videos, jingxuan links with modal_id, and profiles / douyinuser:",
            "Auto Chrome cookies and TLS impersonation",
        ],
        "limits": [
            "Feeds without a video id are not supported",
        ],
    },
    {
        "id": "kwai",
        "name": "Kwai",
        "hosts": ("kwai.com", "kwai-video.com", "kw.ai", "s.kw.ai"),
        "status": ACTIVE,
        "icon": "platform-kuaishou",
        "features": [
            "Short videos and share links",
            "yt-dlp + Chrome TLS fallback",
        ],
        "limits": [],
    },
    {
        "id": "snackvideo",
        "name": "SnackVideo",
        "hosts": ("snackvideo.com", "sck.io"),
        "status": ACTIVE,
        "icon": "platform-snackvideo",
        "features": [
            "Short videos and share links",
            "yt-dlp + web media fallback",
        ],
        "limits": [],
    },
    {
        "id": "kuaishou",
        "name": "Kuaishou",
        "hosts": ("kuaishou.com", "gifshow.com", "v.kuaishou.com"),
        "status": ACTIVE,
        "icon": "platform-kuaishou",
        "features": [
            "Videos and creator profiles",
            "Paste Cookie or cURL in Settings → Tools",
        ],
        "limits": [],
    },
    {
        "id": "xiaohongshu",
        "name": "Xiaohongshu (rednote)",
        "hosts": ("xiaohongshu.com", "xhslink.com"),
        "status": ACTIVE,
        "icon": "platform-xiaohongshu",
        "features": [
            "Explore notes, discovery items, and xhslink short URLs",
            "yt-dlp + embedded video/image state fallback",
        ],
        "limits": [],
    },
    {
        "id": "medaltv",
        "name": "Medal.tv",
        "hosts": ("medal.tv",),
        "status": ACTIVE,
        "icon": "platform-medaltv",
        "features": [
            "Game clips and shared video links",
            "yt-dlp + clip stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "threads",
        "name": "Threads",
        "hosts": ("threads.com", "threads.net"),
        "status": ACTIVE,
        "icon": "platform-threads",
        "features": [
            "Post video and photo URLs on threads.com and threads.net",
            "yt-dlp + OpenGraph / embedded media fallback",
        ],
        "limits": [],
    },
    {
        "id": "suno",
        "name": "SUNO",
        "hosts": ("suno.com", "suno.ai"),
        "status": ACTIVE,
        "icon": "platform-suno",
        "features": [
            "AI song tracks (/song/<id>, /s/<id>) and playlists (/playlist/<id>)",
            "Direct CDN audio/video/cover fallback",
        ],
        "limits": [],
    },
    {
        "id": "twitter",
        "name": "X / Twitter",
        "hosts": ("x.com", "twitter.com", "t.co"),
        "status": ACTIVE,
        "icon": "platform-x",
        "features": [
            "Posts and profile timelines",
            "Video tweets download directly",
            "Photo tweets download images (fxtwitter fallback)",
            "Views: Video / Image",
        ],
        "limits": [],
    },
    {
        "id": "reddit",
        "name": "Reddit",
        "hosts": ("reddit.com", "redd.it", "old.reddit.com", "v.redd.it", "i.redd.it"),
        "status": ACTIVE,
        "icon": "platform-reddit",
        "features": [
            "Posts, galleries, and hosted video/image links",
            "Branded host detection and favicon",
        ],
        "limits": [],
    },
    {
        "id": "dailymotion",
        "name": "DailyMotion",
        "hosts": ("dailymotion.com", "dai.ly"),
        "status": ACTIVE,
        "icon": "platform-dailymotion",
        "features": [
            "Videos, short dai.ly links, playlists, and channels",
            "yt-dlp native extractor + web stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "bilibili",
        "name": "Bilibili",
        "hosts": ("bilibili.tv", "bilibili.com", "b23.tv"),
        "status": ACTIVE,
        "icon": "platform-bilibili",
        "features": [
            "Videos on bilibili.tv, bilibili.com, and b23.tv",
            "bilibili.tv /play/{season} lists every episode",
            "A /play/{season}/{episode} link stays one episode",
        ],
        "limits": [],
    },
    {
        "id": "snapchat",
        "name": "Snapchat",
        "hosts": ("snapchat.com",),
        "status": ACTIVE,
        "icon": "platform-snapchat",
        "features": [
            "Public story and spotlight URLs when the engine supports them",
            "Branded host detection and favicon",
        ],
        "limits": [
            "Login-only content may fail",
        ],
    },
    {
        "id": "weibo",
        "name": "Weibo",
        "hosts": ("weibo.com", "weibo.cn"),
        "status": ACTIVE,
        "icon": "platform-weibo",
        "features": [
            "Status and media URLs when supported by the engine",
            "Branded host detection and favicon",
        ],
        "limits": [
            "Profile feeds are not collected yet",
        ],
    },
    {
        "id": "twitch",
        "name": "Twitch",
        "hosts": ("twitch.tv",),
        "status": ACTIVE,
        "icon": "platform-twitch",
        "features": [
            "Clips and VOD URLs when supported by the engine",
            "Branded host detection and favicon",
        ],
        "limits": [
            "Live streams are not supported",
        ],
    },
    {
        "id": "scraped",
        "name": "Other Scraped Links (Extension)",
        "hosts": ("*.mp4", "*.m3u8", "*.mpd", "*.mp3", "*.m4a", "*.jpg", "*.png", "*.webp"),
        "status": ACTIVE,
        "icon": "platform-scraped",
        "features": [
            "Direct media & HLS/DASH links captured by browser extensions",
            "Downloads via yt-dlp, FFmpeg, curl_cffi, or HTTP stream",
        ],
        "limits": [],
    },
    # --- Movie & Drama Sites ---
    {
        "id": "dramabox",
        "name": "DramaBox",
        "hosts": ("dramaboxdb.com", "dramabox.com", "dramaboxapp.com"),
        "status": ACTIVE,
        "icon": "dramabox",
        "features": [
            "Short drama series and episode pages",
            "yt-dlp + curl_cffi / Next.js / HLS stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "netshort",
        "name": "NetShort",
        "hosts": ("netshort.com",),
        "status": ACTIVE,
        "icon": "netshort",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "flickreels",
        "name": "Flickreels",
        "hosts": ("flickreels.net", "flickreels.com"),
        "status": ACTIVE,
        "icon": "flickreels",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "stardusttv",
        "name": "Stardusttv",
        "hosts": ("stardusttv.net",),
        "status": ACTIVE,
        "icon": "stardusttv",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "starshort",
        "name": "StarShort",
        "hosts": ("starshort.tv",),
        "status": ACTIVE,
        "icon": "starshort",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "goodshort",
        "name": "Goodshort",
        "hosts": ("goodshort.com",),
        "status": ACTIVE,
        "icon": "goodshort",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "dramawave",
        "name": "DramaWave",
        "hosts": ("mydramawave.com", "dramawave.com"),
        "status": ACTIVE,
        "icon": "dramawave",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "freereels",
        "name": "FreeReels",
        "hosts": ("free-reels.com", "freereels.com"),
        "status": ACTIVE,
        "icon": "freereels",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "reelshort",
        "name": "ReelShort",
        "hosts": ("reelshort.com",),
        "status": ACTIVE,
        "icon": "reelshort",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / Next.js stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "hongguo",
        "name": "Hongguo",
        "hosts": ("hongguoduanju.com",),
        "status": ACTIVE,
        "icon": "hongguo",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "idrama",
        "name": "iDrama",
        "hosts": ("idrama.video",),
        "status": ACTIVE,
        "icon": "idrama",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "bilitv",
        "name": "BiliTv.com",
        "hosts": ("bilitv.com",),
        "status": ACTIVE,
        "icon": "bilitv",
        "features": [
            "Drama and video pages on bilitv.com",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "wetv",
        "name": "WeTV",
        "hosts": ("wetv.vip", "v.qq.com"),
        "status": ACTIVE,
        "icon": "wetv",
        "features": [
            "Episodes and series on wetv.vip",
            "yt-dlp WeTV extractor + web stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "iqiyi",
        "name": "iQIYI",
        "hosts": ("iq.com", "iqiyi.com"),
        "status": ACTIVE,
        "icon": "iqiyi",
        "features": [
            "Episodes and albums on iq.com and iqiyi.com",
            "yt-dlp iQIYI extractor + web stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "dramabite",
        "name": "DramaBite",
        "hosts": ("dramabite.media",),
        "status": ACTIVE,
        "icon": "dramabite",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "vigloo",
        "name": "VigLoo",
        "hosts": ("vigloo.com",),
        "status": ACTIVE,
        "icon": "vigloo",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "kisskh",
        "name": "KiSSKH",
        "hosts": ("kisskh.org", "kisskh.ovh", "kisskh.co", "kisskh.do", "kisskh.la", "kisskh.id", "kisskh.me"),
        "status": ACTIVE,
        "icon": "kisskh",
        "features": [
            "Drama & movie episodes on kisskh.org, kisskh.ovh, kisskh.co, kisskh.do",
            "yt-dlp + curl_cffi / HLS stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "flextv",
        "name": "FlexTv",
        "hosts": ("flextv.cc",),
        "status": ACTIVE,
        "icon": "flextv",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "melolo",
        "name": "Melolo",
        "hosts": ("melolo.org", "melolo.com"),
        "status": ACTIVE,
        "icon": "melolo",
        "features": [
            "Short drama episodes and series pages",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    {
        "id": "kolabkhmer",
        "name": "Kolabkhmer",
        "hosts": ("kolabkhmer.com",),
        "status": ACTIVE,
        "icon": "kolabkhmer",
        "features": [
            "Khmer drama and movie episodes",
            "yt-dlp + curl_cffi / embedded stream fallback",
        ],
        "limits": [],
    },
    # --- Placeholder for unknown non-media hosts ---
    {
        "id": "generic",
        "name": "Other HTTPS",
        "hosts": ("any other http(s) host",),
        "status": COMING_SOON,
        "icon": "platform-generic",
        "features": [
            "Unknown hosts are listed here only",
        ],
        "limits": [
            "Not extracted or downloaded until the site is supported",
        ],
    },
]


def active_platforms():
    return [entry for entry in PLATFORM_CATALOG if entry["status"] == ACTIVE]


def coming_soon_platforms():
    return [entry for entry in PLATFORM_CATALOG if entry["status"] == COMING_SOON]


def platform_by_id(platform_id):
    for entry in PLATFORM_CATALOG:
        if entry["id"] == platform_id:
            return entry
    return None
