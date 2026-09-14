"""Non-GUI download engine: collect, download, list model, and runtime.

    app/core/main.py             CLI entry (`uv run reels`)
    app/core/collect.py           URL listing and metadata
    app/core/download.py          yt-dlp download pool
    app/core/scrape.py           Facebook /reels Selenium scrape
    app/core/urls.py             URL classification
    app/core/jobs.py             cancellation token
    app/core/store.py            persisted download list
    app/core/model.py            Qt table model
    app/core/icons.py            recolored SVG / PNG artwork
    app/core/platform_icons.py  host logos
    app/core/theme.py            palettes and stylesheets
    app/core/runtime.py          yt-dlp / FFmpeg setup
    app/core/sysinfo.py          status-bar meters
"""
