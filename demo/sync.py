"""同期マーカー検出と、動画フレームの読み出し。

録画開始直後に画面全体をマゼンタで塗る（SYNC_*）。動画上で最初にその色が
現れた時刻 v と、ホスト側で塗った時刻 h から offset = v - h を求め、操作ログを動画時刻に変換する。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from .ff import FFMPEG

W, H = 64, 36
SYNC_COLOR = "#ff00ff"
SYNC_MS = 400


def frames(video: Path, start: float = 0, dur: float | None = None, w: int = W, h: int = H):
    """(pts_time, RGB ndarray) を順に返す。"""
    cmd = [FFMPEG, "-hide_banner", "-v", "info", "-ss", str(start), "-i", str(video)]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-vf", f"scale={w}:{h},showinfo", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.run(cmd, capture_output=True)
    pts = [float(x) + start for x in re.findall(rb"pts_time:([\d.]+)", p.stderr)]
    arr = np.frombuffer(p.stdout, np.uint8).reshape(-1, h, w, 3)
    return list(zip(pts, arr))


def find_sync(video: Path, color=(255, 0, 255), search: float = 30.0, tol: float = 40) -> float | None:
    for t, f in frames(video, 0, search):
        # 画面中央部で判定する（desktop モードではブラウザの枠やタスクバーが周囲に映るため）
        center = f[H // 4: H * 3 // 4, W // 4: W * 3 // 4]
        if np.abs(center.reshape(-1, 3).mean(0) - color).max() < tol:
            return round(t, 3)
    return None


def offset(video: Path, sync_host: float) -> float:
    v = find_sync(video)
    if v is None:
        raise RuntimeError(f"{video}: 同期マーカーが見つかりません")
    return round(v - sync_host, 3)


def gray_at(video: Path, t: float, w: int = 480, h: int = 270) -> np.ndarray:
    fr = frames(video, max(0, t), 0.2, w, h)
    if not fr:
        raise RuntimeError(f"{video}: t={t:.2f}s のフレームがありません")
    return fr[0][1].mean(axis=2)
