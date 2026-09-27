"""ffmpeg / ffprobe の実行パス。PATH に無ければ static-ffmpeg（入っていれば）の同梱バイナリを使う。"""
import shutil

if not shutil.which("ffmpeg"):
    try:
        import static_ffmpeg

        static_ffmpeg.add_paths(weak=True)
    except ImportError:
        pass

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
if not (FFMPEG and FFPROBE):
    raise RuntimeError("ffmpeg / ffprobe が見つかりません。apt install ffmpeg などで導入してください")
