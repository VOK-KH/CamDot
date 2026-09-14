# VokGet

Python download manager (PySide6 GUI + yt-dlp/selenium). Package lives in `app/`. Tests: `uv run python -m unittest discover -s tests -v`. GUI entry: `uv run reels`.

## Agent org

The **CTO** (`cto` subagent, skill `cto-dispatch`) is the only manager. It reads `.cursor/job.json`, assigns jobs to specialist subagents, and writes status back. Do not implement a queued job yourself unless you are that job's assignee or the user asked you to do the work directly.

Specialists: `gui-engineer`, `core-engineer`, `qa-tester`, `explorer`, `reviewer`.
