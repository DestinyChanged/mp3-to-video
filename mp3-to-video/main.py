# -*- coding: utf-8 -*-
"""MP3 批量转视频工具。

选择一张封面图片 + 一个音乐文件夹，将其中所有 MP3 批量渲染为
以封面为静态背景的 MP4 视频。依赖 ffmpeg / ffprobe（打包时内置）。
"""
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "MP3 批量转视频"
FONT_FAMILY = "Microsoft YaHei UI"
FONT = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 9)
COLOR_BG = "#FFFFFF"      # 背景只用白色
COLOR_FG = "#000000"      # 字体只用黑色
COLOR_HOVER = "#F2F2F2"   # 悬停填充
COLOR_PRESS = "#DCDCDC"   # 按下填充（0.12s 后恢复，满足 0.2s 内完成动画要求）
RES_PRESETS = {"1280 x 720": (1280, 720), "1920 x 1080": (1920, 1080), "跟随封面原始尺寸": None}
FPS_PRESETS = {"24": 24, "30": 30, "60": 60}
AUDIO_MODES = {"AAC 320kbps（推荐）": "aac", "MP3 直通（无损，兼容性略差）": "copy"}
SIZE_CAP = 1920  # 跟随封面时长边上限


# ---------------------------------------------------------------- 资源定位

def resource_dir():
    """PyInstaller onefile 模式下返回解包目录，否则返回脚本目录。"""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def find_binaries():
    """返回 (ffmpeg, ffprobe) 路径；优先内置，其次系统 PATH。"""
    base = os.path.join(resource_dir(), "ffmpeg_bin")
    ext = ".exe" if os.name == "nt" else ""
    ffmpeg = os.path.join(base, "ffmpeg" + ext)
    ffprobe = os.path.join(base, "ffprobe" + ext)
    if not os.path.isfile(ffmpeg):
        ffmpeg = shutil.which("ffmpeg") or ""
    if not os.path.isfile(ffprobe):
        ffprobe = shutil.which("ffprobe") or ""
    if not ffmpeg or not ffprobe:
        raise FileNotFoundError(
            "未找到 ffmpeg / ffprobe。请使用 build.bat 打包（内置 ffmpeg），"
            "或将 ffmpeg 所在目录加入系统 PATH。")
    return ffmpeg, ffprobe


# ---------------------------------------------------------------- 核心逻辑

def scan_mp3(folder, recursive):
    """扫描文件夹内的 .mp3 文件，忽略其他文件。"""
    folder = os.path.abspath(folder)
    if recursive:
        found = []
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                if name.lower().endswith(".mp3"):
                    found.append(os.path.join(root, name))
        return sorted(found)
    return sorted(
        os.path.join(folder, n) for n in os.listdir(folder)
        if n.lower().endswith(".mp3") and os.path.isfile(os.path.join(folder, n))
    )


def probe_audio(ffprobe, path):
    """返回音频时长（秒）。"""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return float(out.stdout.strip())


def probe_image(ffprobe, path):
    """返回封面 (宽, 高)。"""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    w, h = out.stdout.strip().split("x")
    return int(w), int(h)


def calc_size(w, h):
    """跟随封面尺寸：最长边不超过 1920，且宽高取偶（H.264 要求）。"""
    scale = min(1.0, SIZE_CAP / max(w, h))
    w, h = int(w * scale), int(h * scale)
    return max(2, w - w % 2), max(2, h - h % 2)


def unique_output_path(out_dir, mp3_path):
    """输出路径 = 音频名 + .mp4，重名自动追加序号。"""
    stem = os.path.splitext(os.path.basename(mp3_path))[0]
    candidate = os.path.join(out_dir, stem + ".mp4")
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(out_dir, "%s(%d).mp4" % (stem, n))
        n += 1
    return candidate


def build_args(ffmpeg, cover, audio, out_path, width, height, fps, audio_mode):
    """构造 ffmpeg 命令行。封面 cover-crop 铺满画面；音频不指定 -ar，保持原采样率。"""
    vf = ("scale=%d:%d:force_original_aspect_ratio=increase,"
          "crop=%d:%d,format=yuv420p,setsar=1" % (width, height, width, height))
    args = [
        ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", str(fps), "-i", cover, "-i", audio,
        "-filter_complex", "[0:v]" + vf + "[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage", "-crf", "20",
    ]
    if audio_mode == "aac":
        args += ["-c:a", "aac", "-b:a", "320k"]
    else:
        args += ["-c:a", "copy"]
    args += ["-shortest", "-movflags", "+faststart",
             "-progress", "pipe:1", "-nostats", out_path]
    return args


class Converter(threading.Thread):
    """后台转换线程：逐个文件调用 ffmpeg，通过队列向 GUI 汇报。"""

    def __init__(self, ffmpeg, ffprobe, cover, mp3_list, out_dir,
                 width, height, fps, audio_mode):
        super().__init__(daemon=True)
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.cover = cover
        self.mp3_list = mp3_list
        self.out_dir = out_dir
        self.width = width
        self.height = height
        self.fps = fps
        self.audio_mode = audio_mode
        self.q = queue.Queue()
        self.cancelled = threading.Event()
        self._proc = None

    def stop(self):
        self.cancelled.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self):
        total = len(self.mp3_list)
        ok = fail = 0
        for idx, mp3 in enumerate(self.mp3_list, 1):
            if self.cancelled.is_set():
                break
            out_path = unique_output_path(self.out_dir, mp3)
            self.q.put(("file_start", idx, total, os.path.basename(mp3)))
            try:
                duration = probe_audio(self.ffprobe, mp3)
                args = build_args(self.ffmpeg, self.cover, mp3, out_path,
                                  self.width, self.height, self.fps, self.audio_mode)
                self._proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                for line in self._proc.stdout:
                    if self.cancelled.is_set():
                        break
                    if line.startswith("out_time_us="):
                        try:
                            frac = min(1.0, float(line.split("=", 1)[1]) / 1e6 / max(duration, 0.1))
                            self.q.put(("file_progress", frac))
                        except ValueError:
                            pass
                self._proc.wait()
                if self.cancelled.is_set():
                    if os.path.exists(out_path):
                        os.remove(out_path)  # 清理半成品
                    break
                if self._proc.returncode == 0:
                    ok += 1
                    self.q.put(("file_done", True, out_path))
                else:
                    fail += 1
                    err = (self._proc.stderr.read() or "").strip().splitlines()
                    self.q.put(("file_done", False,
                                err[-1] if err else "ffmpeg 返回码 %d" % self._proc.returncode))
                    if os.path.exists(out_path):
                        os.remove(out_path)
            except Exception as exc:  # 单文件失败不影响后续文件
                fail += 1
                if os.path.exists(out_path):
                    os.remove(out_path)
                self.q.put(("file_done", False, str(exc)))
        if self.cancelled.is_set():
            self.q.put(("done", "已取消"))
        else:
            self.q.put(("done", "转换结束：成功 %d 个，失败 %d 个" % (ok, fail)))


# ---------------------------------------------------------------- GUI

def rounded_points(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class RoundedButton(tk.Canvas):
    """圆角矩形按钮，按下后 0.12 秒内恢复并触发命令。"""

    def __init__(self, master, text, command, width=140, height=36, radius=12,
                 font=FONT, fill="#000000", fg="#FFFFFF"):
        super().__init__(master, width=width, height=height, bg=COLOR_BG,
                         highlightthickness=0)
        self.command = command
        self.font = font
        self._text = text
        self._cw, self._ch, self._r = width, height, radius
        self._fill, self._fg = fill, fg
        self._draw(fill, fg)
        self.bind("<Button-1>", self._on_press)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _draw(self, fill, fg):
        self.delete("all")
        self.create_polygon(rounded_points(1, 1, self._cw - 1, self._ch - 1, self._r),
                            smooth=True, fill=fill, outline="#000000", width=1)
        self.create_text(self._cw // 2, self._ch // 2, text=self._text, fill=fg,
                         font=self.font)

    def _on_enter(self, _event):
        if self._fill == COLOR_BG:
            self._draw(COLOR_HOVER, self._fg)

    def _on_leave(self, _event):
        self._draw(self._fill, self._fg)

    def _on_press(self, _event):
        self._draw(COLOR_PRESS, COLOR_FG)
        self.after(120, self._release)

    def _release(self):
        if not self.winfo_exists():
            return
        self._draw(self._fill, self._fg)
        if self.command:
            self.command()


class App:
    def __init__(self, root):
        self.root = root
        self.ffmpeg, self.ffprobe = find_binaries()
        self.worker = None
        self.q = queue.Queue()
        self.cover = tk.StringVar()
        self.music_dir = tk.StringVar()
        self.out_dir = tk.StringVar()
        self.recursive = tk.BooleanVar(value=False)
        self.resolution = tk.StringVar(value="1920 x 1080")
        self.fps = tk.StringVar(value="30")
        self.audio_mode = tk.StringVar(value="AAC 320kbps（推荐）")

        root.title(APP_TITLE)
        root.configure(bg=COLOR_BG)
        root.geometry("700x740")
        root.minsize(640, 660)
        self._build_ui()
        root.after(100, self._poll_queue)

    # ---- 界面 ----------------------------------------------------------

    def _build_ui(self):
        rowpad = {"padx": 18, "pady": (6, 0)}
        tk.Label(self.root, text=APP_TITLE, bg=COLOR_BG, fg=COLOR_FG,
                 font=(FONT_FAMILY, 16, "bold")).pack(pady=(16, 2))
        tk.Label(self.root, text="将音乐文件夹内的 MP3 逐个渲染为以封面图为背景的 MP4 视频",
                 bg=COLOR_BG, fg=COLOR_FG, font=FONT_SMALL).pack(pady=(0, 10))

        self._path_row("封面图片", self.cover, self.pick_cover, rowpad)
        self._path_row("音乐文件夹", self.music_dir, self.pick_music, rowpad)
        self._path_row("输出文件夹", self.out_dir, self.pick_output, rowpad)

        opts = tk.Frame(self.root, bg=COLOR_BG)
        opts.pack(fill="x", padx=18, pady=(6, 0))
        tk.Checkbutton(opts, text="递归扫描子文件夹", variable=self.recursive,
                       bg=COLOR_BG, fg=COLOR_FG, activebackground=COLOR_BG,
                       activeforeground=COLOR_FG, highlightthickness=0,
                       font=FONT_SMALL).pack(side="left")
        for label, var, values, width in (
                ("分辨率", self.resolution, list(RES_PRESETS), 18),
                ("帧率", self.fps, list(FPS_PRESETS), 6),
                ("音频", self.audio_mode, list(AUDIO_MODES), 24)):
            tk.Label(opts, text=label, bg=COLOR_BG, fg=COLOR_FG,
                     font=FONT_SMALL).pack(side="left", padx=(14, 3))
            ttk.Combobox(opts, textvariable=var, values=values, state="readonly",
                         width=width, font=FONT_SMALL).pack(side="left")

        actions = tk.Frame(self.root, bg=COLOR_BG)
        actions.pack(pady=12)
        self.start_btn = RoundedButton(actions, "开始转换", self.start_convert,
                                       width=150, height=40,
                                       fill="#000000", fg="#FFFFFF")
        self.start_btn.pack(side="left", padx=8)
        self.cancel_btn = RoundedButton(actions, "取消", self.cancel_convert,
                                        width=110, height=40,
                                        fill=COLOR_BG, fg=COLOR_FG)
        self.cancel_btn.pack(side="left", padx=8)
        self.cancel_btn.configure(state="disabled")

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Mono.Horizontal.TProgressbar", troughcolor=COLOR_BG,
                        background="#000000", bordercolor=COLOR_BG,
                        lightcolor="#000000", darkcolor="#000000")
        style.configure("Mono.TCombobox", fieldbackground=COLOR_BG,
                        background=COLOR_HOVER, foreground=COLOR_FG,
                        arrowcolor=COLOR_FG, bordercolor="#000000",
                        lightcolor=COLOR_BG, darkcolor=COLOR_BG)
        self.status = tk.Label(self.root, text="等待开始", anchor="w",
                               bg=COLOR_BG, fg=COLOR_FG, font=FONT)
        self.status.pack(fill="x", padx=18)
        self.total_bar = ttk.Progressbar(self.root, style="Mono.Horizontal.TProgressbar",
                                         maximum=1, value=0)
        self.total_bar.pack(fill="x", padx=18, pady=(4, 0))
        self.file_bar = ttk.Progressbar(self.root, style="Mono.Horizontal.TProgressbar",
                                        maximum=1, value=0)
        self.file_bar.pack(fill="x", padx=18, pady=(4, 0))

        tk.Label(self.root, text="日志", bg=COLOR_BG, fg=COLOR_FG,
                 font=FONT_SMALL).pack(fill="x", padx=18, pady=(8, 0), anchor="w")
        self.log = tk.Text(self.root, height=12, bg=COLOR_BG, fg=COLOR_FG,
                           font=FONT_SMALL, state="disabled",
                           highlightbackground="#000000", highlightthickness=1,
                           relief="flat", wrap="word")
        self.log.pack(fill="both", expand=True, padx=18, pady=(2, 14))

    def _path_row(self, label, var, cmd, rowpad):
        row = tk.Frame(self.root, bg=COLOR_BG)
        row.pack(fill="x", **rowpad)
        tk.Label(row, text=label, width=10, anchor="w", bg=COLOR_BG, fg=COLOR_FG,
                 font=FONT).pack(side="left")
        tk.Label(row, textvariable=var, anchor="w", bg=COLOR_BG, fg=COLOR_FG,
                 font=FONT_SMALL, highlightbackground="#000000",
                 highlightthickness=1, relief="flat", padx=6,
                 takefocus=0).pack(side="left", fill="x", expand=True, ipady=6)
        RoundedButton(row, "浏览...", cmd, width=80, height=32,
                      fill=COLOR_BG, fg=COLOR_FG).pack(side="left", padx=(8, 0))

    # ---- 文件选择 ------------------------------------------------------

    def pick_cover(self):
        path = filedialog.askopenfilename(
            title="选择封面图片",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp *.webp"),
                       ("所有文件", "*.*")])
        if path:
            self.cover.set(path)

    def pick_music(self):
        path = filedialog.askdirectory(title="选择音乐文件夹")
        if path:
            self.music_dir.set(path)
            if not self.out_dir.get():
                self.out_dir.set(path)  # 默认输出到音乐文件夹，可另选

    def pick_output(self):
        path = filedialog.askdirectory(title="选择输出文件夹")
        if path:
            self.out_dir.set(path)

    # ---- 转换控制 ------------------------------------------------------

    def start_convert(self):
        cover, music, out = self.cover.get(), self.music_dir.get(), self.out_dir.get()
        if not cover:
            messagebox.showwarning(APP_TITLE, "请先选择封面图片")
            return
        if not music:
            messagebox.showwarning(APP_TITLE, "请先选择音乐文件夹")
            return
        if not out:
            messagebox.showwarning(APP_TITLE, "请先选择输出文件夹")
            return
        try:
            w, h = RES_PRESETS[self.resolution] or probe_image(self.ffprobe, cover)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "无法读取封面尺寸：%s" % exc)
            return
        mp3s = scan_mp3(music, self.recursive.get())
        if not mp3s:
            messagebox.showwarning(APP_TITLE, "所选文件夹内未找到 MP3 文件")
            return
        os.makedirs(out, exist_ok=True)

        self.log_write("封面: %s (%dx%d)" % (cover, w, h))
        self.log_write("找到 %d 个 MP3，输出目录: %s" % (len(mp3s), out))
        self.worker = Converter(self.ffmpeg, self.ffprobe, cover, mp3s, out,
                                w, h, FPS_PRESETS[self.fps], AUDIO_MODES[self.audio_mode])
        self.worker.start()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

    def cancel_convert(self):
        if self.worker and self.worker.is_alive():
            self.log_write("正在取消...")
            self.worker.stop()
            self.cancel_btn.configure(state="disabled")

    # ---- 队列轮询（线程安全刷新 GUI） -----------------------------------

    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "file_start":
                    _, idx, total, name = msg
                    self.status.config(text="正在转换 (%d/%d): %s" % (idx, total, name))
                    self.total_bar.config(maximum=total, value=idx - 1)
                    self.file_bar.config(maximum=1, value=0)
                elif kind == "file_progress":
                    self.file_bar.config(value=msg[1])
                elif kind == "file_done":
                    if msg[1]:
                        self.log_write("完成: %s" % msg[2])
                    else:
                        self.log_write("失败: %s" % msg[2])
                    self.total_bar.step(1)
                elif kind == "done":
                    self.status.config(text=msg[1])
                    self.log_write(msg[1])
                    self.file_bar.config(value=0)
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self.worker = None
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def log_write(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Windows 高分屏清晰显示
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
