@echo off
setlocal
cd /d "%~dp0"
title MP3 批量转视频 - 打包脚本

echo ============================================
echo   MP3 批量转视频工具 - 一键打包为单个 exe
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3.10 或更高版本，
    echo        安装时务必勾选 "Add Python to PATH"，然后重新运行本脚本。
    pause
    exit /b 1
)

rem ---- 第 1 步：下载 ffmpeg / ffprobe（若已存在则跳过） ----
if exist ffmpeg_bin\ffmpeg.exe if exist ffmpeg_bin\ffprobe.exe (
    echo [1/3] ffmpeg 已存在，跳过下载。
) else (
    echo [1/3] 正在下载 ffmpeg（约 80 MB，仅下载一次）...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip' -OutFile 'ffmpeg.zip'"
    if errorlevel 1 (
        echo [错误] ffmpeg 下载失败，请检查网络后重试，
        echo        或手动下载该 zip，将其中 bin\ffmpeg.exe 与 ffprobe.exe 放入 ffmpeg_bin\ 目录。
        pause
        exit /b 1
    )
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "Expand-Archive -Path 'ffmpeg.zip' -DestinationPath 'ffmpeg_tmp' -Force"
    if not exist ffmpeg_bin mkdir ffmpeg_bin
    copy /y ffmpeg_tmp\*\bin\ffmpeg.exe ffmpeg_bin\ >nul
    copy /y ffmpeg_tmp\*\bin\ffprobe.exe ffmpeg_bin\ >nul
    rmdir /s /q ffmpeg_tmp
    del ffmpeg.zip
    if not exist ffmpeg_bin\ffmpeg.exe (
        echo [错误] ffmpeg 解压失败。
        pause
        exit /b 1
    )
)

rem ---- 第 2 步：安装 PyInstaller ----
echo [2/3] 检查并安装 PyInstaller...
python -m pip install --quiet pyinstaller
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败，请检查网络后重试。
    pause
    exit /b 1
)

rem ---- 第 3 步：打包 ----
echo [3/3] 正在打包（约 1-3 分钟）...
python -m PyInstaller app.spec --noconfirm --clean
if errorlevel 1 (
    echo [错误] 打包失败，请把上方报错信息反馈给开发者。
    pause
    exit /b 1
)

echo.
echo ============================================
echo   打包完成！
echo   产物位置: %~dp0dist\MP3ToVideo.exe
echo   双击即可运行，无需安装任何其他软件。
echo ============================================
pause
