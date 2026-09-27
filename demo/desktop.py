"""desktop モード（P3）: Xvfb 上の画面全体を ffmpeg で録画し、xdotool の実カーソルで操作する。

コンテナ内で実行する（recorder/Dockerfile）。ステップ処理は record.Recorder をそのまま使い、
カーソル移動とクリックだけを XScreen に差し替える。
  python -m demo.desktop <scene.yaml> --out <dir> [--vnc]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import scene as scene_mod
from .record import BROWSER_ENV, SYNC_COLOR, SYNC_MS, Recorder, install_overlays

W, H, FPS = 1920, 1080, 30
MOUSE_PROBE = """window.__lastMouse = window.__lastMouse || null;
window.addEventListener('mousemove', e => { window.__lastMouse = [e.clientX, e.clientY]; }, true);"""


def sh(*cmd: str, check: bool = True) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=check).stdout.strip()


class XScreen:
    """実カーソル（X のポインタ）を動かす。ページ座標→画面座標はキャリブレーションで求める。"""

    def __init__(self):
        self.offset = (0.0, 0.0)
        self.pos = (W / 2, H / 2)
        self.errors: list[dict] = []
        self.calc_proc = None

    def _moves(self, pts, dt):
        args = []
        for x, y in pts:
            args += ["mousemove", str(round(x)), str(round(y)), "sleep", f"{dt:.3f}"]
        subprocess.run(["xdotool", *args], check=True)

    def glide(self, dst, speed=1.2, lo=250, hi=1200):
        """ease-in-out で dst（画面座標）まで動かす。1プロセスで連続移動させて滑らかにする。"""
        dist = math.dist(self.pos, dst)
        dur = min(hi, max(lo, dist / speed)) / 1000
        n = max(2, int(dur * 60))
        ease = lambda t: 0.5 - math.cos(math.pi * t) / 2
        pts = [(self.pos[0] + (dst[0] - self.pos[0]) * ease(k / n), self.pos[1] + (dst[1] - self.pos[1]) * ease(k / n))
               for k in range(1, n + 1)]
        self._moves(pts, dur / n)
        self.pos = dst

    def calibrate(self, page) -> tuple[float, float]:
        """画面上の既知の点にポインタを置き、ページが受け取った clientX/Y との差を offset とする。"""
        probes = [(W * 0.5, H * 0.5), (W * 0.3, H * 0.6), (W * 0.7, H * 0.4)]
        diffs = []
        for sx, sy in probes:
            self._moves([(sx - 3, sy - 3), (sx, sy)], 0.05)
            page.wait_for_timeout(120)
            cx, cy = page.evaluate("window.__lastMouse")
            diffs.append((sx - cx, sy - cy))
        self.offset = diffs[0]
        self.pos = probes[-1]
        spread = max(abs(d[0] - diffs[0][0]) + abs(d[1] - diffs[0][1]) for d in diffs)
        return {"offset": self.offset, "probe_spread_px": spread}

    def move_to(self, page, xy):
        dst = (xy[0] + self.offset[0], xy[1] + self.offset[1])
        self.glide(dst)
        page.wait_for_timeout(60)
        got = page.evaluate("window.__lastMouse")
        err = math.dist(got, xy) if got else None
        self.errors.append({"target": [round(v, 1) for v in xy], "page_saw": got, "err_px": round(err, 2) if err is not None else None})

    def click(self):
        subprocess.run(["xdotool", "click", "1"], check=True)

    def close_native_dialog(self):
        # Playwright がファイル選択を横取りするため、ネイティブのダイアログは出ない（出たら Escape で閉じる）
        if sh("xdotool", "search", "--name", "ファイルを開く|Open File", check=False):
            subprocess.run(["xdotool", "key", "Escape"])

    def open_in_calc(self, path: Path, hold_ms: int):
        t = time.monotonic()
        self.calc_proc = subprocess.Popen(
            ["soffice", "--calc", "--nologo", "--norestore", "--nodefault", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wid = sh("xdotool", "search", "--sync", "--onlyvisible", "--name", path.stem)
        wid = wid.splitlines()[0]
        subprocess.run(["wmctrl", "-i", "-r", str(int(wid)), "-b", "add,maximized_vert,maximized_horz"])
        subprocess.run(["xdotool", "windowactivate", "--sync", wid], check=False)
        self.calc_open_s = round(time.monotonic() - t, 2)
        time.sleep(1.0)  # 描画が落ち着くまで
        # セル範囲をなぞって「開いたファイルを見ている」動きを付ける
        for dst in [(W * 0.22, H * 0.30), (W * 0.40, H * 0.30), (W * 0.40, H * 0.42)]:
            self.glide(dst)
            time.sleep(0.5)
        time.sleep(max(0, hold_ms / 1000 - 2.5))


class MemSampler(threading.Thread):
    """コンテナ全体のメモリ使用量（cgroup v2）を 0.5 秒ごとに記録する。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.stop = [], threading.Event()

    def run(self):
        f = Path("/sys/fs/cgroup/memory.current")
        while not self.stop.is_set():
            if f.exists():
                self.samples.append(int(f.read_text()))
            time.sleep(0.5)

    def summary(self):
        peak_file = Path("/sys/fs/cgroup/memory.peak")
        peak = int(peak_file.read_text()) if peak_file.exists() else max(self.samples or [0])
        return {"peak_mb": round(peak / 2**20), "max_sampled_mb": round(max(self.samples or [0]) / 2**20)}


def start_display(vnc: bool) -> list[subprocess.Popen]:
    procs = [subprocess.Popen(["Xvfb", ":99", "-screen", "0", f"{W}x{H}x24", "-nolisten", "tcp"])]
    for _ in range(50):
        if subprocess.run(["xdpyinfo"], capture_output=True).returncode == 0:
            break
        time.sleep(0.1)
    subprocess.run(["xsetroot", "-cursor_name", "left_ptr", "-solid", "#1f2933"])
    procs.append(subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    if vnc:
        procs.append(subprocess.Popen(["x11vnc", "-display", ":99", "-forever", "-nopw", "-shared", "-quiet"]))
        procs.append(subprocess.Popen(["websockify", "--web", "/usr/share/novnc", "6080", "localhost:5900"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.5)
    return procs


def record_desktop(scene_path: Path, out: Path, vnc: bool = False) -> dict:
    scene = scene_mod.load(scene_path)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    procs = start_display(vnc)
    mem = MemSampler()
    mem.start()
    raw = out / "raw.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", str(FPS),
         "-video_size", f"{W}x{H}", "-draw_mouse", "1", "-i", ":99",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", str(raw)],
        stdin=subprocess.PIPE)
    screen = XScreen()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False, channel="chromium",
                args=["--lang=ja-JP", "--start-maximized", "--window-position=0,0", f"--window-size={W},{H}",
                      "--no-first-run", "--disable-infobars"],
                ignore_default_args=["--enable-automation"], env=BROWSER_ENV)
            context = browser.new_context(no_viewport=True, locale="ja-JP", accept_downloads=True)
            install_overlays(context, "none", scene["zoom"])
            context.add_init_script(script=MOUSE_PROBE)
            page = context.new_page()
            rec = Recorder(page, scene, out, screen=screen)
            page.goto(scene["url"])
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(800)
            calib = screen.calibrate(page)
            sync_at = rec.now()
            page.evaluate("([c,ms])=>window.__demo.sync(c,ms)", [SYNC_COLOR, SYNC_MS])
            page.wait_for_timeout(500)
            started = rec.now()
            events = rec.run()
            ended = rec.now()
            time.sleep(0.5)
            context.close()
            browser.close()
    finally:
        ff.communicate(b"q", timeout=30)
        mem.stop.set()
        if screen.calc_proc:
            screen.calc_proc.terminate()
        for pr in reversed(procs):
            pr.terminate()
    errs = [e["err_px"] for e in screen.errors if e["err_px"] is not None]
    manifest = {"scene": scene["id"], "scene_path": scene["_path"], "mode": "desktop", "cursor": "xdotool",
                "viewport": {"width": W, "height": H}, "zoom": scene["zoom"], "video": str(raw),
                "sync_host": sync_at, "sync_color": SYNC_COLOR, "started": started, "ended": ended,
                "events": events, "captions": [e for e in events if e.get("caption")],
                "calibration": calib, "cursor_errors": screen.errors,
                "max_cursor_err_px": max(errs) if errs else None,
                "calc_open_s": getattr(screen, "calc_open_s", None), "memory": mem.summary()}
    (out / "events.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--vnc", action="store_true")
    a = ap.parse_args()
    m = record_desktop(a.scene, a.out, a.vnc)
    print(json.dumps({k: m[k] for k in ("calibration", "max_cursor_err_px", "calc_open_s", "memory")}, ensure_ascii=False))


if __name__ == "__main__":
    os.environ.setdefault("DISPLAY", ":99")
    # ホストの uid で動かすと HOME が無いことがある（LibreOffice のプロファイル作成に必要）
    Path(os.environ.setdefault("HOME", "/tmp/home")).mkdir(parents=True, exist_ok=True)
    main()
