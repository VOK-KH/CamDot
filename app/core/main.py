"""
CamDot
Download posts from Facebook, Instagram, TikTok, YouTube, and X.

Usage:
    uv run camdot                 # PySide6 GUI
    uv run camdot --gui
    uv run camdot --cli           # interactive terminal prompts
    uv run camdot <name> "<post_or_feed_url>"
    uv run camdot <name> --from-csv output/<name>.csv
"""
import os
import sys

from app.core.collect import collect_entries
from app.core.download import DEFAULT_FRAGMENTS, DEFAULT_WORKERS, download_from_csv
from app.core.runtime import schedule_auto_update
from app.core.urls import clean_url, looks_shell_truncated, normalize_source_url

USAGE = """Usage:
  uv run camdot                          (opens the PySide6 GUI)
  uv run camdot --gui
  uv run camdot --cli                    (interactive terminal prompts)
  uv run camdot <output_name> "<url>"
  uv run camdot <output_name> --from-csv <path_to_csv>

  uv run camdot-gui                      (same as --gui)

Supported URLs:
  Facebook   single reel/video, or a page /reels tab (Chrome login)
  Instagram  single post / reel / TV (profiles are not supported)
  TikTok     single video, or @user profile
  YouTube    watch/shorts, channel, or playlist
  X          single post /status/ (timelines are not supported)

Speed options (any mode):
  --workers N     items downloaded at the same time (default 4)
  --fragments N   fragments fetched in parallel per item (default 8)

Keep the URL inside quotes when it contains "&".
"""

TRUNCATED_URL_WARNING = """
WARNING: the URL you passed ends right after the profile id, which is what a
shell leaves behind when it eats an unquoted "&". Continuing with the reels
tab added back automatically.

Next time, put the URL in quotes:
  uv run camdot <name> "<url>"
"""


def _prompt(label):
    try:
        return input(label).strip()
    except EOFError:
        return ""


def _take_speed_options(args):
    speed = {"workers": DEFAULT_WORKERS, "fragments": DEFAULT_FRAGMENTS}
    rest = []
    index = 0
    while index < len(args):
        name = args[index].lstrip("-")
        if name in speed and index + 1 < len(args) and args[index + 1].isdigit():
            speed[name] = int(args[index + 1])
            index += 2
            continue
        rest.append(args[index])
        index += 1
    return speed, rest


def main():
    schedule_auto_update()
    args = sys.argv[1:]
    speed, args = _take_speed_options(args)

    if args and args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    if not args or args[0] in ("--gui", "-g"):
        from app.gui import run_gui
        return run_gui()

    if args[0] in ("--cli",):
        args = args[1:]
        if not args:
            print(USAGE)
            print("Nothing to do yet - let's fill it in (paste is safe here).\n")
            channel = _prompt("Output name (folder): ")
            raw_url = _prompt("Post or feed URL: ")
            if not channel or not raw_url:
                print("\nA name and a URL are both required.")
                return 1
            return _collect_and_download(channel, raw_url, speed)

    if len(args) >= 2 and args[1] == "--from-csv":
        if len(args) < 3:
            print("Please provide the CSV path: uv run camdot <name> --from-csv <path>")
            return 1
        csv_path = clean_url(args[2])
        if not os.path.isfile(csv_path):
            print(f"CSV not found: {csv_path}")
            return 1
        return download_from_csv(args[0], csv_path, **speed)

    if len(args) >= 2:
        return _collect_and_download(args[0], args[1], speed)

    print(USAGE)
    print("Nothing to do yet - let's fill it in (paste is safe here).\n")
    channel = args[0]
    raw_url = _prompt("Post or feed URL: ")
    if not channel or not raw_url:
        print("\nA name and a URL are both required.")
        return 1
    return _collect_and_download(channel, raw_url, speed)


def _collect_and_download(channel, raw_url, speed):
    if looks_shell_truncated(raw_url):
        print(TRUNCATED_URL_WARNING)

    try:
        url = normalize_source_url(raw_url)
    except ValueError as exc:
        print(f"Error: {exc}\n")
        print(USAGE)
        return 1

    if url != clean_url(raw_url) and not looks_shell_truncated(raw_url):
        print(f"Using URL: {url}")

    csv_path, _entries = collect_entries(channel, url)
    return download_from_csv(channel, csv_path, **speed)


if __name__ == "__main__":
    sys.exit(main())
