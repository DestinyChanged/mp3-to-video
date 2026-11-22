# MP3 批量转视频工具

选择一张封面图片和一个音乐文件夹，自动将其中所有 MP3 批量渲染为以封面为
静态背景的 MP4 视频。打包后为单个 exe，双击即用，**无需安装 Python 或 ffmpeg**。

## 功能

- 选择封面图片（jpg / jpeg / png / bmp / webp）
- 选择音乐文件夹，自动扫描其中所有 `.mp3`（忽略其他文件），可勾选递归扫描子文件夹
- 每个生成一个独立 `.mp4`，文件名与音频一致；重名自动追加 `(1)`、`(2)` 序号
- 可单独选择输出文件夹（默认与音乐文件夹相同）
- 分辨率：1280x720 / 1920x1080（默认）/ 跟随封面原始尺寸（最长边不超过 1920，自动取偶）
- 帧率：24 / 30（默认）/ 60 fps
- 音频：AAC 320kbps（默认，兼容性最好）/ MP3 直通（零损耗，兼容性略差）。
  两种模式均不改动采样率，MP3 原始频率保持不变
- 总进度条 + 当前文件进度条 + 日志，支持中途取消（取消时自动删除未完成文件）
- 界面白底黑字，圆角按钮，点击反馈动画 0.12 秒

## 获取 exe 的两种方式

### 方式一：GitHub Actions 云端构建（无需本地安装任何东西）

1. 将本项目推送到你的 GitHub 仓库
2. 打开仓库页面 → Actions 标签 → 选择 "Build Windows EXE" → Run workflow
3. 构建完成后（约 3 分钟），在该次运行页面底部 Artifacts 处
   下载 `MP3ToVideo-windows-exe`，解压得到 `MP3ToVideo.exe`

### 方式二：本地 Windows 构建（一次性）

1. 安装 Python 3.10+（安装时勾选 "Add Python to PATH"）
2. 双击运行 `build.bat`，脚本会自动：
   下载 ffmpeg.exe / ffprobe.exe → 安装 PyInstaller → 打包
3. 产物位于 `dist\MP3ToVideo.exe`

## 技术说明

- 技术栈：Python + Tkinter，直接调用 ffmpeg 子进程（无第三方 GUI/媒体库依赖）
- ffmpeg 命令要点：`-loop 1 -framerate N -i 封面 -i 音频`，
  视频 `libx264 -tune stillimage -crf 20`，
  封面按 `scale=...:force_original_aspect_ratio=increase,crop=...` 铺满画面，
  `format=yuv420p` 保证播放器兼容，`-shortest` 使视频时长等于音频时长，
  `-movflags +faststart` 便于流式播放
- 进度解析：`-progress pipe:1` 输出 `out_time_us`，除以音频实际时长得到百分比
- 取消：终止 ffmpeg 进程并删除半成品文件

## 常见问题

- **提示"未找到 ffmpeg"**：说明运行的是未打包的 main.py 或 ffmpeg 下载失败。
  使用 build.bat 打包即可内置；开发调试可将 ffmpeg 加入系统 PATH。
- **视频画面被裁剪**：封面图与所选分辨率比例不一致时会铺满裁剪（cover 模式）。
  想保留完整画面请选择"跟随封面原始尺寸"。
- **杀毒软件报毒**：PyInstaller 单文件程序偶有误报，添加信任即可。
