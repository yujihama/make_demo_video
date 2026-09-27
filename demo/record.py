"""決定的ランナー: シーン YAML を Playwright で実行し、録画と操作ログを出す（browser モード）。

出力: <out>/raw.webm, events.json（ホスト時刻基準の操作ログ）, downloads/
desktop モード（Xvfb 画面録画）は demo/desktop.py が同じステップ処理を使って実行する。
"""
from __future__ import annotations

import json
import math
import os
import random
import shutil
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from . import scene as scene_mod
from .style import scene_style

ASSETS = Path(__file__).with_name("assets")
SYNC_COLOR = "#ff00ff"
SYNC_MS = 400
# Linux の Chromium は UI 言語（ファイル選択ボタン等）を --lang ではなく環境変数で決める
BROWSER_ENV = {**os.environ, "LANG": "ja_JP.UTF-8", "LANGUAGE": "ja"}
GHOST_STYLE = "document.addEventListener('DOMContentLoaded',()=>window.__playwriterGhostCursor?.enable({style:'screenstudio',size:28}))"


class Recorder:
    """ステップを実行し、各ステップの開始・操作・終了時刻を記録する。"""

    def __init__(self, page: Page, scene: dict, out: Path, dry: bool = False, screen=None):
        self.page, self.scene, self.out, self.dry = page, scene, out, dry
        self.screen = screen  # desktop モードでは実カーソルを動かすオブジェクト（xdotool）
        self.t0 = time.monotonic()
        self.events: list[dict] = []
        self.pos = (scene["viewport"]["width"] / 2, scene["viewport"]["height"] / 2)
        self.last_download: Path | None = None
        self.human = None
        if scene["cursor"] == "smooth" and not screen:
            from human_cursor import SyncHumanCursor, Vector
            self.human = SyncHumanCursor(page, start=Vector(*self.pos))

    # --- 時刻と待ち ------------------------------------------------------
    def now(self) -> float:
        return round(time.monotonic() - self.t0, 3)

    def wait(self, ms: int) -> None:
        if not self.dry and ms > 0:
            self.page.wait_for_timeout(ms)

    # --- カーソル --------------------------------------------------------
    def locate(self, testid: str):
        loc = self.page.get_by_test_id(testid)
        loc.wait_for(state="visible", timeout=15000)
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        # 一部しか見えていなければ、全体が見える位置まで滑らかにスクロールする（演出の枠が切れないように）
        vh = self.page.viewport_size["height"] if self.page.viewport_size else self.page.evaluate("innerHeight")
        margin = 80
        delta = 0
        if box["y"] + box["height"] > vh - margin:
            delta = min(box["y"] + box["height"] - (vh - margin), box["y"] - margin)
        elif box["y"] < margin:
            delta = box["y"] - margin
        if abs(delta) > 4:
            self.page.evaluate("([d, b]) => window.scrollBy({top: d, behavior: b})", [delta, "instant" if self.dry else "smooth"])
            self.page.wait_for_function(
                "() => new Promise(r => { let y = scrollY; setTimeout(() => r(scrollY === y), 120); })", timeout=5000)
            box = loc.bounding_box()
        return loc, (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2), box

    def move(self, xy: tuple[float, float], idx: int) -> None:
        if self.dry:
            self.page.mouse.move(*xy)
        elif self.screen:
            self.screen.move_to(self.page, xy)
        elif self.scene["cursor"] == "ghost":
            dist = math.dist(self.pos, xy)
            dur = min(1500, max(220, dist / 1.2))
            self.page.evaluate("([x,y])=>window.__playwriterGhostCursor?.applyMouseAction({type:'move',x,y})", list(xy))
            self.page.mouse.move(*xy)  # 実際のホバー状態も合わせる
            self.page.wait_for_timeout(dur + 60)
        elif self.scene["cursor"] == "smooth":
            from human_cursor import Vector
            random.seed(self.scene["seed"] * 1000 + idx)  # 軌跡を毎回同じにする
            self.human.move_to(Vector(*xy))
        else:
            self.page.mouse.move(*xy)
        self.pos = xy

    def press(self, xy) -> None:
        if self.screen and not self.dry:
            self.screen.click()
            return
        if self.scene["cursor"] == "ghost" and not self.dry:
            self.page.evaluate("([x,y])=>window.__playwriterGhostCursor?.applyMouseAction({type:'down',x,y})", list(xy))
        self.page.mouse.down()
        self.page.wait_for_timeout(0 if self.dry else 90)
        self.page.mouse.up()
        if self.scene["cursor"] == "ghost" and not self.dry:
            self.page.evaluate("([x,y])=>window.__playwriterGhostCursor?.applyMouseAction({type:'up',x,y})", list(xy))

    # --- ステップ --------------------------------------------------------
    def run(self) -> list[dict]:
        pace = self.scene["pace"]
        for i, kind, spec in scene_mod.steps(self.scene):
            ev = {"i": i, "kind": kind, "start": self.now(), **{k: spec[k] for k in ("caption", "name", "testid", "title") if k in spec}}
            handler = getattr(self, f"do_{kind}")
            handler(i, spec, ev, pace)
            self.wait(spec.get("hold", 0))
            if spec.get("name") and not self.dry and kind != "open_download":
                self.snapshot(spec["name"], ev)
            ev["end"] = self.now()
            self.events.append(ev)
            print(f"  [{ev['start']:6.2f}-{ev['end']:6.2f}] {kind} {spec.get('testid', spec.get('title', ''))}", flush=True)
        return self.events

    def snapshot(self, name: str, ev: dict) -> None:
        """review 用: その時点の画面テキストとスクリーンショットを残す（動画に同じ状態が映っているかの照合用）。"""
        snaps = self.out / "snaps"
        snaps.mkdir(exist_ok=True)
        ev["snap_at"] = self.now()
        self.page.screenshot(path=str(snaps / f"{name}.png"))
        ev["snap_text"] = self.page.evaluate("document.body.innerText")

    def _pointer_action(self, i, spec, ev, pace, action):
        loc, xy, box = self.locate(spec["testid"])
        ev["box"] = [round(v) for v in (box["x"], box["y"], box["width"], box["height"])]
        self.move(xy, i)
        self.wait(pace["before_action"])
        ev["act"] = self.now()
        action(loc, xy)
        self.wait(pace["after_action"])

    def do_click(self, i, spec, ev, pace):
        self._pointer_action(i, spec, ev, pace, lambda loc, xy: self.press(xy))

    def do_hover(self, i, spec, ev, pace):
        self._pointer_action(i, spec, ev, pace, lambda loc, xy: None)

    def do_type(self, i, spec, ev, pace):
        def act(loc, xy):
            self.press(xy)
            loc.press_sequentially(spec["text"], delay=0 if self.dry else 60)
        self._pointer_action(i, spec, ev, pace, act)

    def do_upload(self, i, spec, ev, pace):
        def act(loc, xy):
            with self.page.expect_file_chooser() as fc:
                self.press(xy)
            if self.screen and not self.dry:
                self.screen.close_native_dialog()
            fc.value.set_files(spec["file"])
        self._pointer_action(i, spec, ev, pace, act)

    def do_download(self, i, spec, ev, pace):
        def act(loc, xy):
            with self.page.expect_download() as dl:
                self.press(xy)
            d = dl.value
            dst = self.out / "downloads" / d.suggested_filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            d.save_as(dst)
            self.last_download = dst
            ev["file"] = str(dst)
        self._pointer_action(i, spec, ev, pace, act)

    def do_wait_for(self, i, spec, ev, pace):
        loc = self.page.get_by_test_id(spec["testid"])
        if "text" in spec:
            loc = loc.filter(has_text=spec["text"])
        loc.first.wait_for(state="visible", timeout=spec.get("timeout", 30000))
        ev["act"] = ev["done"] = self.now()
        box = loc.first.bounding_box()
        if box:  # 完了時に光らせる（パルス）位置
            ev["box"] = [round(v) for v in (box["x"], box["y"], box["width"], box["height"])]
        # アプリ側の処理時間は毎回揺れる（ポーリング間隔など）。duration を指定すると
        # ステップ長をその値に固定し、以降のタイムラインを決定的にする。
        if "duration" in spec and not self.dry:
            spent = (ev["act"] - ev["start"]) * 1000
            if spent > spec["duration"]:
                ev["overrun_ms"] = round(spent - spec["duration"])
            else:
                self.wait(round(spec["duration"] - spent))
                ev["act"] = self.now()

    def do_chapter(self, i, spec, ev, pace):
        if self.dry:
            return
        ms = spec.get("duration", 2200)
        if scene_style(self.scene)["effects"] == "simple":
            self.page.evaluate("([t,d,ms])=>window.__demo.chapter(t,d,ms)", [spec["title"], spec.get("description", ""), ms])
        else:
            # rich: 章カードは後工程で重ねる（背景ぼかし・進捗つき）。録画側は間だけ取る
            self.wait(ms)

    def do_pause(self, i, spec, ev, pace):
        self.wait(spec["ms"])

    def do_open_download(self, i, spec, ev, pace):
        if not self.screen:
            raise scene_mod.SceneError("open_download は desktop モード専用です")
        if not self.last_download:
            raise scene_mod.SceneError("open_download の前に download ステップが必要です")
        ev["act"] = self.now()
        if not self.dry:
            def ready():  # Calc の窓が出た時刻と、見せたい範囲（画面座標）を残す
                ev["act"] = self.now()
                ev["screen_box"] = list(self.screen.CALC_FOCUS)
            self.screen.open_in_calc(self.last_download, spec.get("hold", 3000), on_ready=ready)
            spec["hold"] = 0


def install_overlays(context, cursor: str, zoom: float = 1.0) -> None:
    # Playwright の録画は CSS ピクセル寸法で撮られ、device_scale_factor は反映されない。
    # 画面を大きく見せたいときは body に CSS zoom をかける（オーバーレイは html 直下なので影響しない）。
    if zoom != 1:
        context.add_init_script(script=f"document.addEventListener('DOMContentLoaded',()=>document.body.style.zoom='{zoom}')")
    context.add_init_script(path=str(ASSETS / "overlay.js"))
    if cursor == "ghost":
        context.add_init_script(path=str(ASSETS / "vendor" / "playwriter-ghost-cursor.js"))
        context.add_init_script(script=GHOST_STYLE)
    elif cursor == "smooth":
        context.add_init_script(script="document.addEventListener('DOMContentLoaded',()=>window.__demo.enableFollow())")


def record(scene_path: str | Path, out: str | Path, dry: bool = False, headless: bool = True, trace: bool = False) -> dict:
    """browser モードで1本録画する。dry=True は録画せず最速で操作だけ通す（セレクタ確認）。
    trace=True で Playwright トレース（trace.zip）も残す（playwright-recast 比較用）。"""
    scene = scene_mod.load(scene_path)
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    vp = scene["viewport"]
    with sync_playwright() as p:
        # headless shell はネイティブ部品（ファイル選択ボタン等）が英語になるため、フル版 Chromium を使う
        browser = p.chromium.launch(headless=headless, channel="chromium", args=["--lang=ja-JP"], env=BROWSER_ENV)
        ctx_opts = dict(viewport=vp, locale="ja-JP", accept_downloads=True)
        if not dry:
            ctx_opts.update(record_video_dir=str(out / "_video"), record_video_size=vp)
        context = browser.new_context(**ctx_opts)
        install_overlays(context, "none" if dry else scene["cursor"], scene["zoom"])
        if trace:
            context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        rec = Recorder(page, scene, out, dry=dry)
        page.goto(scene["url"])
        page.wait_for_load_state("networkidle")
        sync_at = None
        if not dry:
            sync_at = rec.now()
            page.evaluate("([c,ms])=>window.__demo.sync(c,ms)", [SYNC_COLOR, SYNC_MS])
            page.wait_for_timeout(500)
        started = rec.now()
        events = rec.run()
        ended = rec.now()
        video = page.video
        if trace:
            context.tracing.stop(path=str(out / "trace.zip"))
        context.close()
        browser.close()
        raw = None
        if video:
            raw = out / "raw.webm"
            Path(video.path()).replace(raw)
            shutil.rmtree(out / "_video", ignore_errors=True)
    manifest = {"scene": scene["id"], "scene_path": scene["_path"], "mode": "browser", "cursor": scene["cursor"],
                "viewport": vp, "zoom": scene["zoom"], "video": str(raw) if raw else None, "sync_host": sync_at, "sync_color": SYNC_COLOR,
                "started": started, "ended": ended, "events": events,
                "captions": [e for e in events if e.get("caption")]}
    (out / "events.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest
