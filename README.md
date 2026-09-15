<p align="center">
  <img width="15%" align="center" src="images/icons/app.svg" alt="CamDot logo">
</p>
<h1 align="center">CamDot</h1>
<p align="center">
  A cross-platform download manager for Facebook, Instagram, TikTok, YouTube, X, and more — PySide6 GUI + yt-dlp + Selenium
</p>

<p align="center">
  <a style="text-decoration:none">
    <img src="https://img.shields.io/badge/Python-3.12-blue.svg?color=00B16A" alt="Python 3.12"/>
  </a>
  <a style="text-decoration:none">
    <img src="https://img.shields.io/badge/PySide6-6-blue?color=00B16A" alt="PySide6"/>
  </a>
  <a style="text-decoration:none">
    <img src="https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20macOS-blue?color=00B16A" alt="Platform Windows | Linux | macOS"/>
  </a>
  <a style="text-decoration:none" href="https://github.com/VOK-KH/CamDot/releases">
    <img src="https://img.shields.io/github/v/release/VOK-KH/CamDot?label=release&color=00B16A" alt="Release"/>
  </a>
</p>

<p align="center">
  <a href="https://github.com/VOK-KH/CamDot">Repository</a> ·
  <a href="https://github.com/VOK-KH/CamDot/releases">Downloads</a> ·
  <a href="https://github.com/VOK-KH/CamDot/issues">Issues</a>
</p>

![CamDot preview](preview.png)

## Features

* JDownloader-style **Grabber** and **Download** tabs with clipboard monitoring
* Collect feeds and posts from **Facebook, Instagram, TikTok, YouTube, X**, Bilibili, Douyin, Pinterest, and more
* **yt-dlp** downloads with resume, parallel workers, and optional speed limits
* **Selenium** fallback when a site needs a logged-in browser session
* Filter by **Video / Music / Image** and host; package or link properties panel
* System **tray** support — downloads keep running when the window is hidden
* **Auto-update** check for new app releases from GitHub

## Quick start

1. Clone and install with [uv](https://docs.astral.sh/uv/):

    ```shell
    git clone https://github.com/VOK-KH/CamDot.git
    cd CamDot
    uv python install
    uv sync
    ```

2. Launch the GUI:

    ```shell
    uv run camdot
    # or
    uv run camdot-gui
    ```

3. Optional — verify bundled tools (yt-dlp, FFmpeg):

    ```shell
    uv run camdot-setup
    ```

### Usage

1. Paste a post, channel, or playlist URL and click **Collect**.
2. Review titles and host icons in the table.
3. Click **Start all Downloads** (or download checked rows only).

**Grabber On** watches the clipboard like JDownloader's LinkGrabber — copy supported links and they are queued for metadata collection in the background.

Default download folder:

* Windows / Linux: `Downloads/CamDot/<channel>/`
* macOS: `Documents/CamDot/<channel>/`

App data (Chrome profile, lists, caches): `%LOCALAPPDATA%/camdot` on Windows.

## Deploy

Build a standalone app for the current platform:

```shell
uv sync --group dev
uv run python tools/deploy.py
```

Output lands in `dist/`:

| Platform | Artifact |
|---|---|
| Windows x86_64 | `CamDot-v{version}-Windows-x86_64.exe` |
| Linux x86_64 / arm64 | `CamDot-v{version}-Linux-{arch}.tar.gz` |
| macOS arm64 / x86_64 | `CamDot-v{version}-macOS-{arch}.dmg` |

Optional PyArmor obfuscation before packaging:

```shell
PYARMOR=1 uv run python tools/deploy.py
```

## Release

CI builds run on GitHub Actions. To publish a new version:

1. Bump `version` in `pyproject.toml` and `app/__init__.py`
2. Commit, tag, and push:

    ```shell
    git tag v0.2.0
    git push origin v0.2.0
    ```

3. The **Release** workflow builds all platforms and uploads assets to [GitHub Releases](https://github.com/VOK-KH/CamDot/releases).

The app checks that release page on startup and from **Tools → Check for app updates**.

## Tests

```shell
uv run python -m unittest discover -s tests -v
```

GUI layout preview (offscreen):

```shell
uv run python tools/preview.py preview.png
```

## See also

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — media downloader used by CamDot
- [PySide6](https://doc.qt.io/qtforpython/) — Qt for Python GUI toolkit
- [uv](https://docs.astral.sh/uv/) — fast Python package manager

## License

CamDot is licensed under [MIT](LICENSE).

Copyright © 2025–2026 VOK-KH.
