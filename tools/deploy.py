"""Build and package CamDot for the current platform (PyInstaller + optional PyArmor)."""
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
SPEC = ROOT / "camdot.spec"


def version():
    import app

    return app.__version__


def arch_label():
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine


def platform_label():
    if sys.platform == "win32":
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    return "Linux"


def artifact_name(suffix):
    return f"CamDot-v{version()}-{platform_label()}-{arch_label()}{suffix}"


def maybe_pyarmor():
    if os.environ.get("PYARMOR", "").lower() not in ("1", "true", "yes"):
        return
    obf = ROOT / "obf"
    if obf.exists():
        shutil.rmtree(obf)
    cmd = [
        sys.executable,
        "-m",
        "pyarmor",
        "gen",
        "-O",
        str(obf),
        "-r",
        str(ROOT / "app"),
    ]
    print("Running:", " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"PyArmor skipped: {exc}", file=sys.stderr)


def run_pyinstaller():
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean"]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def package_windows():
    exe = DIST / "CamDot.exe"
    if not exe.is_file():
        raise SystemExit(f"Missing build output: {exe}")
    out = DIST / artifact_name(".exe")
    shutil.copy2(exe, out)
    return out


def package_linux():
    exe = DIST / "CamDot"
    if not exe.is_file():
        raise SystemExit(f"Missing build output: {exe}")
    out = DIST / artifact_name(".tar.gz")
    with tarfile.open(out, "w:gz") as tar:
        tar.add(exe, arcname="CamDot")
    return out


def package_macos():
    app = DIST / "CamDot.app"
    if not app.is_dir():
        raise SystemExit(f"Missing build output: {app}")
    staging = DIST / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    shutil.copytree(app, staging / "CamDot.app")
    os.symlink("/Applications", staging / "Applications")
    dmg = DIST / artifact_name(".dmg")
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-srcfolder",
            str(staging),
            "-volname",
            "CamDot",
            "-fs",
            "HFS+",
            "-format",
            "UDZO",
            "-size",
            "600m",
            str(dmg),
        ],
        check=True,
    )
    shutil.rmtree(staging)
    return dmg


def main():
    maybe_pyarmor()
    run_pyinstaller()
    if sys.platform == "win32":
        out = package_windows()
    elif sys.platform == "darwin":
        out = package_macos()
    else:
        out = package_linux()
    print(f"VERSION={version()}")
    print(f"ARTIFACT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
