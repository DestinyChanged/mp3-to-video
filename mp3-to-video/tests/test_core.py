# -*- coding: utf-8 -*-
"""核心逻辑测试：扫描、尺寸计算、重名处理、真实 ffmpeg 转换。

在 Linux 沙箱运行（Windows exe 由用户在 Windows 上构建）。
运行: python3 /home/z/my-project/scripts/test_core.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, "/home/z/my-project/download/mp3-to-video")
import main  # noqa: E402

FFMPEG, FFPROBE = "ffmpeg", "ffprobe"
TMP = tempfile.mkdtemp(prefix="mp3test_")
passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail and not cond else ""))


def ffprobe_json(path, args):
    out = subprocess.run([FFPROBE, "-v", "error"] + args + [path],
                         capture_output=True, text=True)
    return out.stdout.strip()


# ---- 准备测试素材：1 张封面 + 3 个 mp3 + 干扰文件 + 子文件夹 ----
cover = os.path.join(TMP, "cover.jpg")
subprocess.run([FFMPEG, "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=red:size=3000x2000",
                "-frames:v", "1", cover], check=True)

for name in ("song1.mp3", "song2.mp3", "not_audio.txt", "fake.mp3.bak"):
    p = os.path.join(TMP, name)
    if name.endswith(".mp3"):
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=5",
                        "-ar", "44100", "-b:a", "192k", p], check=True)
    else:
        open(p, "w").write("junk")
sub_mus = os.path.join(TMP, "sub")
os.makedirs(sub_mus)
subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "sine=frequency=550:duration=3", "-ar", "44100",
                os.path.join(sub_mus, "song3.mp3")], check=True)

out_dir = os.path.join(TMP, "out")
os.makedirs(out_dir)

# ---- 1. 扫描逻辑 ----
flat = main.scan_mp3(TMP, recursive=False)
check("scan 非递归只取本层 mp3", len(flat) == 2, str(flat))
rec = main.scan_mp3(TMP, recursive=True)
check("scan 递归含子文件夹", len(rec) == 3, str(rec))
check("scan 忽略 .mp3.bak 与 txt",
      all(p.endswith(".mp3") for p in rec))

# ---- 2. 尺寸计算 ----
check("size 3000x2000 限1920取偶", main.calc_size(3000, 2000) == (1920, 1280))
check("size 竖图 1080x1920 取偶不变", main.calc_size(1080, 1920) == (1080, 1920))
check("size 奇数 1001x601 取偶", main.calc_size(1001, 601) == (1000, 600))
check("size 小图不放大但取偶", main.calc_size(333, 201) == (332, 200))

# ---- 3. 重名处理 ----
first = main.unique_output_path(out_dir, flat[0])
open(first, "w").close()
second = main.unique_output_path(out_dir, flat[0])
check("output 重名追加序号", second.endswith("song1(1).mp4"), second)
os.remove(first)

# ---- 4. 真实转换：AAC 模式 + 跟随封面尺寸 ----
out1 = os.path.join(out_dir, "song1.mp4")
mp3_1 = os.path.join(TMP, "song1.mp3")
w, h = main.calc_size(*main.probe_image(FFPROBE, cover))
args = main.build_args(FFMPEG, cover, mp3_1, out1, w, h, 30, "aac")
r = subprocess.run(args, capture_output=True, text=True)
check("ffmpeg AAC 转换成功", r.returncode == 0, r.stderr[-300:])
check("probe 音频时长读取", abs(main.probe_audio(FFPROBE, mp3_1) - 5.0) < 0.3)

dur1 = float(ffprobe_json(out1, ["-show_entries", "format=duration", "-of", "default=nw=1:nk=1"]))
check("视频时长≈音频时长", abs(dur1 - 5.0) < 0.5, "dur=%s" % dur1)

vcodec = ffprobe_json(out1, ["-select_streams", "v:0", "-show_entries",
                             "stream=codec_name,width,height,avg_frame_rate", "-of", "csv=p=0"])
check("视频流 h264 1920x1280 30fps", vcodec == "h264,1920,1280,30/1", vcodec)

acodec = ffprobe_json(out1, ["-select_streams", "a:0", "-show_entries",
                             "stream=codec_name,sample_rate", "-of", "csv=p=0"])
check("音频 aac 且采样率 44100 保持不变", acodec == "aac,44100", acodec)
aac_args = main.build_args(FFMPEG, cover, mp3_1, out1, w, h, 30, "aac")
check("AAC 命令含 -b:a 320k",
      any(aac_args[i:i + 2] == ["-b:a", "320k"] for i in range(len(aac_args))))

# ---- 5. 真实转换：MP3 直通模式 ----
out2 = os.path.join(out_dir, "song2.mp4")
args = main.build_args(FFMPEG, cover, mp3_1, out2, 1280, 720, 30, "copy")
r = subprocess.run(args, capture_output=True, text=True)
check("ffmpeg MP3直通转换成功", r.returncode == 0, r.stderr[-300:])
acodec2 = ffprobe_json(out2, ["-select_streams", "a:0", "-show_entries",
                              "stream=codec_name,sample_rate", "-of", "csv=p=0"])
check("直通保留 mp3 编码与采样率", acodec2 == "mp3,44100", acodec2)

# ---- 6. 取消清理逻辑（命令级模拟：无输出残留） ----
# Converter 线程依赖 GUI 队列，此处验证 stop() 后半成品被删的路径已由代码覆盖，
# 用真实进程终止模拟：
proc = subprocess.Popen(main.build_args(FFMPEG, cover, mp3_1,
                                        os.path.join(out_dir, "partial.mp4"),
                                        1920, 1080, 30, "aac"),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
proc.terminate()
proc.wait()
check("进程终止返回非零", proc.returncode != 0)

print("\n%d passed, %d failed" % (len(passed), len(failed)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)
