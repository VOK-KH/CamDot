"""Allow `python -m app` / `uv run python -m app`."""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
