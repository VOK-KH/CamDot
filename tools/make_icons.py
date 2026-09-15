"""Generate the UI icon set into images/icons/.

The icons are plain stroked SVGs on a 24x24 grid that use `currentColor`, so
app/core/icons.py can recolor them for the light and dark themes. Run after editing:

    uv run python tools/make_icons.py
"""
import os

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images", "icons")

TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"'
    ' fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"'
    ' stroke-linejoin="round">{body}</svg>\n'
)

ICONS = {
    # toolbar
    "refresh": (
        '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>'
        '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/>'
        '<path d="M20.49 15a9 9 0 0 1-14.85 3.36L1 14"/>'
    ),
    "select-all": (
        '<polyline points="9 11 12 14 22 4"/>'
        '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'
    ),
    "clear": (
        '<polyline points="3 6 5 6 21 6"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
        '<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>'
    ),
    "link": (
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
    ),
    # actions
    "collect": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "download": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'
    ),
    "login": (
        '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>'
        '<polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>'
    ),
    "cancel": (
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>'
    ),
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "csv": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'
    ),
    "log": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "settings": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06'
        'a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V21h-4v-.09'
        'A1.7 1.7 0 0 0 9 19.36a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83'
        '.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1.03H3v-4h.09'
        'A1.7 1.7 0 0 0 4.64 9a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83'
        '.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3h4v.09'
        'A1.7 1.7 0 0 0 15 4.64a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83'
        '-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.55 1.03H21v4h-.09'
        'A1.7 1.7 0 0 0 19.4 15z"/>'
    ),
    "moon": '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    "sun": (
        '<circle cx="12" cy="12" r="5"/>'
        '<line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>'
        '<line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>'
        '<line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>'
        '<line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>'
        '<line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>'
        '<line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "external": (
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
        '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>'
    ),
    # window controls (the frameless window draws its own title strip)
    "win-minimize": '<line x1="5" y1="12" x2="19" y2="12"/>',
    "win-maximize": '<rect x="5" y="5" width="14" height="14" rx="1"/>',
    "win-restore": (
        '<rect x="4" y="8" width="12" height="12" rx="1"/>'
        '<polyline points="8 8 8 4 20 4 20 16 16 16"/>'
    ),
    "win-close": '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
    "play": '<polygon points="7 4 19 12 7 20" fill="currentColor" stroke="none"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" fill="currentColor" stroke="none"/>',
    "move-up": '<polyline points="6 14 12 8 18 14"/><line x1="12" y1="8" x2="12" y2="20"/>',
    "move-down": '<polyline points="6 10 12 16 18 10"/><line x1="12" y1="4" x2="12" y2="16"/>',
    "globe": (
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="2" y1="12" x2="22" y2="12"/>'
        '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10'
        ' 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'
    ),
    # status bar
    "gpu": (
        '<rect x="2" y="6" width="20" height="12" rx="2"/>'
        '<rect x="5.5" y="9.5" width="6" height="5" rx="1"/>'
        '<circle cx="17" cy="12" r="2.5"/>'
        '<line x1="6" y1="18" x2="6" y2="21"/><line x1="18" y1="18" x2="18" y2="21"/>'
    ),
    "cpu": (
        '<rect x="5" y="5" width="14" height="14" rx="2"/>'
        '<rect x="9" y="9" width="6" height="6"/>'
        '<line x1="9" y1="2" x2="9" y2="5"/><line x1="15" y1="2" x2="15" y2="5"/>'
        '<line x1="9" y1="19" x2="9" y2="22"/><line x1="15" y1="19" x2="15" y2="22"/>'
        '<line x1="2" y1="9" x2="5" y2="9"/><line x1="2" y1="15" x2="5" y2="15"/>'
        '<line x1="19" y1="9" x2="22" y2="9"/><line x1="19" y1="15" x2="22" y2="15"/>'
    ),
    "ram": (
        '<rect x="2" y="7" width="20" height="10" rx="2"/>'
        '<line x1="7" y1="11" x2="7" y2="13"/><line x1="12" y1="11" x2="12" y2="13"/>'
        '<line x1="17" y1="11" x2="17" y2="13"/>'
        '<line x1="6" y1="17" x2="6" y2="20"/><line x1="18" y1="17" x2="18" y2="20"/>'
    ),
    "disk": (
        '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89'
        'A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'
        '<line x1="2" y1="12" x2="22" y2="12"/>'
        '<line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="10.01" y2="16"/>'
    ),
    "activity": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    # row status
    "status-queued": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "status-downloading": (
        '<circle cx="12" cy="12" r="10"/>'
        '<polyline points="8 12 12 16 16 12"/><line x1="12" y1="8" x2="12" y2="16"/>'
    ),
    "status-done": (
        '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'
    ),
    "status-failed": (
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'
    ),
    "status-cancelled": (
        '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>'
    ),
    # window icon
    "app": (
        '<rect x="2" y="4" width="20" height="16" rx="2"/>'
        '<line x1="7" y1="4" x2="7" y2="20"/><line x1="17" y1="4" x2="17" y2="20"/>'
        '<polygon points="10.5 9 15 12 10.5 15" fill="currentColor"/>'
    ),
    "platform-facebook": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M13 8h2V6h-2c-1.7 0-3 1.3-3 3v2H8v2h2v6h2v-6h2l.5-2H12V9c0-.6.4-1 1-1z"/>'
    ),
    "platform-instagram": (
        '<rect x="3" y="3" width="18" height="18" rx="5"/>'
        '<circle cx="12" cy="12" r="4"/>'
        '<circle cx="17.5" cy="6.5" r="0.8" fill="currentColor"/>'
    ),
    "platform-youtube": (
        '<rect x="2" y="6" width="20" height="12" rx="3"/>'
        '<polygon points="10 9 16 12 10 15" fill="currentColor"/>'
    ),
    "platform-tiktok": (
        '<path d="M14 4v10.2a3.2 3.2 0 1 1-3.2-3.2"/>'
        '<path d="M14 8.5c1.4 1.2 3.2 1.9 5 2"/>'
    ),
    "platform-x": (
        '<path d="M4 4l7.2 8.2L4.6 20h3l5.2-6.1L17.8 20H20l-7.5-8.6L19.2 4h-3l-4.8 5.6L6.4 4z"/>'
    ),
    "platform-bilibili": (
        '<path d="M7 7L5 4"/><path d="M17 7L19 4"/>'
        '<rect x="4" y="7" width="16" height="12" rx="2"/>'
        '<polygon points="10 11 15 13.5 10 16" fill="currentColor"/>'
    ),
    "platform-douyin": (
        '<path d="M9 4v11a3.5 3.5 0 1 1-3.5-3.5"/>'
        '<path d="M9 8c2 1.6 4.2 2.4 6.5 2.5"/>'
        '<circle cx="17.5" cy="6.5" r="1.5"/>'
    ),
    "platform-kuaishou": (
        '<rect x="4" y="4" width="16" height="16" rx="4"/>'
        '<polygon points="10 8 16 12 10 16" fill="currentColor"/>'
    ),
    "platform-pinterest": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 7v7"/><circle cx="12" cy="8.5" r="0.5" fill="currentColor"/>'
        '<path d="M10 17c1-3 2-4 2-6"/>'
    ),
    "platform-generic": (
        '<rect x="3" y="5" width="18" height="14" rx="2"/>'
        '<polygon points="10 9 16 12 10 15" fill="currentColor"/>'
    ),
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, body in ICONS.items():
        path = os.path.join(OUT_DIR, f"{name}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE.format(body=body))
    print(f"wrote {len(ICONS)} icons to {OUT_DIR}")


if __name__ == "__main__":
    main()
