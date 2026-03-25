# -*- mode: python ; coding: utf-8 -*-

import os
import glob
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

logo_files = []
src_dir = os.path.join(os.getcwd(), "src")
for png in glob.glob(os.path.join(src_dir, "simple_circle_*.png")):
    logo_files.append((png, "src"))

nba_meta = copy_metadata("nba_api")
logo_files += nba_meta

excluded = [
    "PyQt5",
    "tkinter",
]

hidden = [
    "nba_api",
    "nba_api.live",
    "nba_api.live.nba",
    "nba_api.live.nba.endpoints",
    "nba_api.stats",
    "nba_api.stats.endpoints",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=logo_files,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyi_rth_cleanpath.py"],
    excludes=excluded,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="nba-scoreboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
