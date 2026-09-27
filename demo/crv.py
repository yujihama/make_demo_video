"""crv 代替: 動画を機械的に確認する（解像度・長さ・黒画面・静止区間・コンタクトシート）。

    python -m demo.crv <video> [--out DIR] [--frames 12] [--at 1.5,4.2,...]
結果は <out>/crv.json とコンタクトシート PNG に書き出す。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from .ff import FFMPEG, FFPROBE


def probe(video: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_read_packets:format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    num, den = (int(x) for x in s["avg_frame_rate"].split("/"))
    duration = float(j["format"].get("duration") or 0)
    frames = int(s.get("nb_read_packets") or 0)
    return {"codec": s["codec_name"], "width": s["width"], "height": s["height"],
            "fps": round(num / den, 2) if den else 0, "duration": round(duration, 2), "frames": frames}


def detect(video: Path) -> dict:
    """黒画面（0.5秒以上）と静止区間（3秒以上）を ffmpeg のフィルタで検出する。"""
    err = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(video), "-vf",
         "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=0.003:d=3", "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]
    fs = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    fe = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)]
    freeze = [(a, fe[i] if i < len(fe) else None) for i, a in enumerate(fs)]
    return {"black": black, "freeze": freeze}


def frame_at(video: Path, t: float, dst: Path, width: int = 960) -> Path:
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                    "-frames:v", "1", "-vf", f"scale={width}:-2", str(dst)], check=True)
    return dst


def contact_sheet(video: Path, times: list[float], dst: Path, cols: int = 3) -> Path:
    from PIL import Image, ImageDraw

    tmp = dst.parent / "_frames"
    tmp.mkdir(parents=True, exist_ok=True)
    imgs = [Image.open(frame_at(video, t, tmp / f"f{i:03d}.png", 640)) for i, t in enumerate(times)]
    w, h = imgs[0].size
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 22)), "white")
    d = ImageDraw.Draw(sheet)
    for i, (im, t) in enumerate(zip(imgs, times)):
        x, y = (i % cols) * w, (i // cols) * (h + 22)
        sheet.paste(im, (x, y + 22))
        d.text((x + 6, y + 4), f"t={t:.1f}s", fill="black")
    sheet.save(dst)
    return dst


def run(video: Path, out: Path, n_frames: int = 12, at: list[float] | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    det = detect(video)
    dur = info["duration"]
    times = at or [round(dur * (i + 0.5) / n_frames, 2) for i in range(n_frames)]
    times = [min(max(0.0, t), max(0.0, dur - 0.1)) for t in times]  # 動画の範囲に収める
    sheet = contact_sheet(video, times, out / f"{video.stem}_sheet.png")
    report = {"video": str(video), **info, **det, "sheet": str(sheet), "sheet_times": times}
    (out / "crv.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--at", type=str)
    a = ap.parse_args()
    at = [float(x) for x in a.at.split(",")] if a.at else None
    r = run(a.video, a.out or a.video.parent / "crv", a.frames, at)
    print(json.dumps({k: v for k, v in r.items() if k != "sheet_times"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
