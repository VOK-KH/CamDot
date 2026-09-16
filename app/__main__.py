"""Allow `python -m app` / `uv run python -m app`."""
import sys

from app.core.runtime import quiet_qt_logs

quiet_qt_logs()
from app.main import main

if __name__ == "__main__":
    sys.exit(main())
