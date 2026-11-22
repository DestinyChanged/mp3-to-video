# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单个 exe，内置 ffmpeg.exe / ffprobe.exe。

使用: python -m PyInstaller app.spec --noconfirm --clean
前提: ffmpeg_bin/ 目录下已放置 ffmpeg.exe 与 ffprobe.exe（由 build.bat 自动下载）
"""
import os

binaries = []
for name in ("ffmpeg.exe", "ffprobe.exe"):
    path = os.path.join("ffmpeg_bin", name)
    if os.path.isfile(path):
        binaries.append((path, "ffmpeg_bin"))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "PIL", "scipy", "pandas"],
    noarchive=False,
)
pyz = Pyz(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MP3ToVideo",
    debug=False,
    upx=False,
    console=False,          # 无控制台黑窗，双击即运行
    icon=None,
)
