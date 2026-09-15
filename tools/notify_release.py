"""Post a Telegram notice when GitHub publishes a CamDot release.

Used by the Release workflow after installers are uploaded. Credentials:
CAMDOT_TELEGRAM_BOT_TOKEN and CAMDOT_TELEGRAM_CHAT_ID.
"""
import os
import sys

os.environ.setdefault("CAMDOT_TELEGRAM_RELEASE_NOTICE", "1")

from app.core.telegram_report import notify_github_release
from app.core.updates import fetch_release, parse_release


def _tag_from_env():
    ref = os.environ.get("GITHUB_REF_NAME") or os.environ.get("GITHUB_REF") or ""
    if ref.startswith("refs/tags/"):
        ref = ref.split("refs/tags/", 1)[-1]
    return ref.strip()


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    tag = (argv[0] if argv else "") or _tag_from_env()
    try:
        info = parse_release(fetch_release(tag=tag), current="")
    except Exception as exc:
        print(f"Could not load GitHub release: {exc}", file=sys.stderr)
        return 1
    if not info.get("tag") and not info.get("latest"):
        print("No release tag on GitHub.", file=sys.stderr)
        return 1
    if not notify_github_release(info, block=True):
        print("Telegram credentials missing; skipped notice.")
        return 0
    print(f"Posted Telegram notice for {info.get('tag') or info.get('latest')}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
