#!/usr/bin/env python3
"""sessionStart: inject a short job.json board into agent context."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / ".cursor" / "job.json"


def main() -> None:
    if not JOBS.is_file():
        print(json.dumps({}))
        return
    data = json.loads(JOBS.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    lines = [
        "CTO queue (.cursor/job.json). auto_start=%s. Do not execute until the user asks."
        % data.get("policy", {}).get("auto_start", False)
    ]
    for job in jobs:
        lines.append(
            "- {id} [{status}] p{priority} -> {assignee}: {title} deps={deps}".format(
                id=job.get("id"),
                status=job.get("status"),
                priority=job.get("priority"),
                assignee=job.get("assignee"),
                title=job.get("title"),
                deps=",".join(job.get("depends_on") or []) or "-",
            )
        )
    print(json.dumps({"additional_context": "\n".join(lines)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail open
        print(json.dumps({"additional_context": "job.json hook error: %s" % exc}), file=sys.stdout)
