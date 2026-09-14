#!/usr/bin/env python3
"""subagentStop: remind the CTO to write job status back to job.json."""
from __future__ import annotations

import json
import sys

REMINDER = (
    "Update .cursor/job.json for the job this subagent ran: set status "
    "(done|blocked|pending), notes, and updated_at. Do not leave it in_progress."
)


def main() -> None:
    print(json.dumps({"followup_message": REMINDER}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({}))
        sys.exit(0)
