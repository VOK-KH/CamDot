# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CamDot (Windows / Linux one-file, macOS .app bundle)."""
import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)
entry = str(root / "tools" / "camdot_entry.py")
obf_entry = root / "obf" / "app"
if obf_entry.is_dir():
    entry = str(root / "obf" / "tools" / "camdot_entry.py")

a = Analysis(
    [entry],
    pathex=[str(root), str(root / "obf")] if obf_entry.is_dir() else [str(root)],
    binaries=[],
    datas=[(str(root / "images"), "images")],
    hiddenimports=[
        "yt_dlp",
        "yt_dlp.extractor",
        "yt_dlp.postprocessor",
        "yt_dlp.downloader",
        "curl_cffi",
        "certifi",
        "imageio_ffmpeg",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="CamDot",
        debug=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="CamDot",
    )
    app = BUNDLE(
        coll,
        name="CamDot.app",
        icon=None,
        bundle_identifier="com.vokkh.camdot",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="CamDot",
        debug=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
