"""カメラ（ズーム・パン）の計画と評価。

操作ログの対象要素の位置から「寄り」「引き」のショットを作り、完成動画の時間軸で滑らかに補間する。
状態は (cx, cy, s) = 注視点と拡大率。s=1 が全体。切り出し範囲は幅 W/s・高さ H/s で、画面外に出ないよう寄せる。
"""
from __future__ import annotations

from dataclasses import dataclass

MOVE_MIN, MOVE_MAX = 0.35, 0.8   # カメラ移動にかける秒数


def ease(t: float) -> float:
    """easeInOutCubic"""
    t = min(1.0, max(0.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


@dataclass
class Shot:
    t: float                 # 移動を始める時刻（完成動画の秒）
    dur: float               # 移動にかける秒数
    target: tuple[float, float, float]


class Camera:
    def __init__(self, W: int, H: int, max_zoom: float):
        self.W, self.H, self.max_zoom = W, H, max_zoom
        self.shots: list[Shot] = []
        self.home = (W / 2, H / 2, 1.0)
        self._starts: list | None = None

    # --- ショットの目標 --------------------------------------------------------
    def framing(self, box, mode) -> tuple[float, float, float]:
        W, H = self.W, self.H
        if box is None or mode in (None, "out"):
            return (W / 2, H / 2, 1.0)
        x, y, w, h = box
        cx, cy = x + w / 2, y + h / 2
        if isinstance(mode, (int, float)) and not isinstance(mode, bool):
            s = float(mode)
        elif mode == "fit":            # 対象全体が画面の 85% に収まる程度
            rw, rh = w + 120, h + 120
            s = min(0.85 * W / rw, 0.85 * H / rh)
        else:                           # focus: 対象の周りに文脈を残して寄る
            pad = max(220.0, 0.9 * max(w, h))
            s = min(W / (w + 2 * pad), H / (h + 2 * pad))
        s = max(1.0, min(self.max_zoom, s))
        return (cx, cy, s)

    def add(self, t: float, available: float, box, mode) -> None:
        target = self.framing(box, mode)
        if self.shots and _close(self.shots[-1].target, target):
            return
        dur = max(MOVE_MIN, min(MOVE_MAX, available))
        self.shots.append(Shot(t, dur, target))

    # --- 評価 ----------------------------------------------------------------
    def state(self, t: float) -> tuple[float, float, float]:
        """時刻 t のカメラ状態。前の移動の途中で次のショットが始まっても、その時点の状態から動き出す。"""
        if self._starts is None or len(self._starts) != len(self.shots):
            self._starts = []
            for i, sh in enumerate(self.shots):
                prev = self._starts[i - 1] if i else self.home
                self._starts.append(self._at(self.shots[i - 1], prev, sh.t) if i else prev)
        cur = self.home
        for i, sh in enumerate(self.shots):
            if t < sh.t:
                break
            cur = self._at(sh, self._starts[i], t)
        return cur

    @staticmethod
    def _at(sh: Shot, start, t: float) -> tuple[float, float, float]:
        p = ease((t - sh.t) / sh.dur)
        if p >= 1:
            return sh.target
        # 拡大率は比で補間すると、寄り・引きの見かけの速さが一定になる
        s = start[2] * (sh.target[2] / start[2]) ** p
        return (start[0] + (sh.target[0] - start[0]) * p, start[1] + (sh.target[1] - start[1]) * p, s)

    def crop(self, t: float) -> tuple[float, float, float]:
        """(x0, y0, s): 元フレームの切り出し左上と拡大率。"""
        cx, cy, s = self.state(t)
        w, h = self.W / s, self.H / s
        x0 = min(max(cx - w / 2, 0), self.W - w)
        y0 = min(max(cy - h / 2, 0), self.H - h)
        return x0, y0, s

    @staticmethod
    def to_screen(pt, crop) -> tuple[float, float]:
        x0, y0, s = crop
        return ((pt[0] - x0) * s, (pt[1] - y0) * s)

    @staticmethod
    def rect_to_screen(box, crop) -> tuple[float, float, float, float]:
        x0, y0, s = crop
        x, y, w, h = box
        return ((x - x0) * s, (y - y0) * s, w * s, h * s)


def _close(a, b) -> bool:
    return abs(a[0] - b[0]) < 8 and abs(a[1] - b[1]) < 8 and abs(a[2] - b[2]) < 0.02
