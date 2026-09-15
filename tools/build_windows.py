"""Build CamDot for Windows (delegates to tools/deploy.py)."""
import subprocess
import sys
from pathlib import Path


def main():
    deploy = Path(__file__).resolve().parent / "deploy.py"
    result = subprocess.run([sys.executable, str(deploy)], cwd=deploy.parents[1], check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
