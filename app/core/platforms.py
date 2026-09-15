"""First-class and coming-soon host catalog (no widgets)."""

ACTIVE = "active"
COMING_SOON = "coming_soon"

PLATFORM_CATALOG = [
    {
        "id": "facebook",
        "name": "Facebook",
        "hosts": ("facebook.com", "fb.com"),
        "status": ACTIVE,
        "icon": "platform-facebook",
        "features": [
            "Single posts, reels, videos, and photos",
            "Page /reels and profiles: fast listing first, then Chrome login if needed",
            "Views: video, extract audio, and thumbnail",
            "Cookies from browser",
        ],
        "limits": [],
    },
    {
        "id": "instagram",
        "name": "Instagram",
        "hosts": ("instagram.com",),
        "status": ACTIVE,
        "icon": "platform-instagram",
        "features": [
            "Posts, reels, TV, and stories URLs",
            "Profile, /username/reels, and /username/reposts as feeds",
            "Reposts open Chrome when fast listing is not enough",
            "Cookies recommended",
        ],
        "limits": [],
    },
    {
        "id": "tiktok",
        "name": "TikTok",
        "hosts": ("tiktok.com",),
        "status": ACTIVE,
        "icon": "platform-tiktok",
        "features": [
            "Videos and creator profiles",
            "tiktokuser:<sec_uid> when a profile extract fails",
            "Optional age filter in Settings",
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
        "id": "twitter",
        "name": "X / Twitter",
        "hosts": ("x.com", "twitter.com"),
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
        "id": "bilibili",
        "name": "Bilibili",
        "hosts": ("bilibili.tv", "bilibili.com", "b23.tv"),
        "status": ACTIVE,
        "icon": "platform-bilibili",
        "features": [
            "Videos on bilibili.tv, bilibili.com, and b23.tv",
        ],
        "limits": [],
    },
    {
        "id": "douyin",
        "name": "Douyin",
        "hosts": ("douyin.com", "iesdouyin.com"),
        "status": ACTIVE,
        "icon": "platform-douyin",
        "features": [
            "Videos, jingxuan links with modal_id, and profiles / douyinuser:",
            "Auto Chrome cookies",
        ],
        "limits": [
            "Feeds without a video id are not supported",
        ],
    },
    {
        "id": "kuaishou",
        "name": "Kuaishou",
        "hosts": ("kuaishou.com", "gifshow.com", "kwai.com"),
        "status": ACTIVE,
        "icon": "platform-kuaishou",
        "features": [
            "Videos",
            "Paste Cookie or cURL in Settings → Tools",
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
            "Pins, boards, and profiles/sections",
            "Orig image when the pin has no video",
            "Video pins download as video",
        ],
        "limits": [],
    },
    {
        "id": "generic",
        "name": "Other HTTPS",
        "hosts": ("any other http(s) host",),
        "status": ACTIVE,
        "icon": "platform-generic",
        "features": [
            "Any other http(s) link CamDot can recognize",
            "Success depends on the host",
        ],
        "limits": [
            "No dedicated host polish",
        ],
    },
    {
        "id": "threads",
        "name": "Threads",
        "hosts": ("threads.net",),
        "status": ACTIVE,
        "icon": "platform-generic",
        "features": [
            "Post and media URLs",
            "Branded host detection and favicon",
        ],
        "limits": [
            "No dedicated profile collect yet",
        ],
    },
    {
        "id": "reddit",
        "name": "Reddit",
        "hosts": ("reddit.com", "redd.it", "old.reddit.com"),
        "status": ACTIVE,
        "icon": "platform-generic",
        "features": [
            "Posts, galleries, and hosted video links",
            "Branded host detection and favicon",
        ],
        "limits": [
            "Subreddit feeds are not collected yet",
        ],
    },
    {
        "id": "snapchat",
        "name": "Snapchat",
        "hosts": ("snapchat.com",),
        "status": ACTIVE,
        "icon": "platform-generic",
        "features": [
            "Public story and spotlight URLs when the engine supports them",
            "Branded host detection and favicon",
        ],
        "limits": [
            "Login-only content may fail",
        ],
    },
    {
        "id": "xiaohongshu",
        "name": "Xiaohongshu (RED)",
        "hosts": ("xiaohongshu.com", "xhslink.com"),
        "status": ACTIVE,
        "icon": "platform-generic",
        "features": [
            "Note and short-link URLs when supported by the engine",
            "Branded host detection and favicon",
        ],
        "limits": [
            "Regional or login-only pages may fail",
        ],
    },
    {
        "id": "weibo",
        "name": "Weibo",
        "hosts": ("weibo.com", "weibo.cn"),
        "status": ACTIVE,
        "icon": "platform-generic",
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
        "icon": "platform-generic",
        "features": [
            "Clips and VOD URLs when supported by the engine",
            "Branded host detection and favicon",
        ],
        "limits": [
            "Live streams are not supported",
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
