"""合成エンジン（rich 演出）: 録画 + 操作ログ → 演出付きの完成動画。

録画を 30fps で1枚ずつ読み、完成動画の時刻ごとに
  早送りの時間変換 → カメラ（ズーム・パン） → スポットライト → 波紋・パルス・吹き出し・トースト・バッジ
  → 字幕 → 章カード／イントロ／まとめ
の順に重ねて ffmpeg に流す。演出は録画に焼き込まないので、撮り直さずに作り直せる。
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from . import overlays as ov
from .camera import Camera
from .ff import FFMPEG
from .style import hex_rgb, scene_style, step_effects

FPS = 30
RIPPLE_S, PULSE_S = 0.6, 1.1
INTRO_S, OUTRO_S = 2.8, 3.6


@dataclass
class Plan:
    W: int
    H: int
    accent: tuple
    intro: dict | None
    outro: dict | None
    camera: Camera
    captions: list = field(default_factory=list)
    ripples: list = field(default_factory=list)
    spotlights: list = field(default_factory=list)
    pulses: list = field(default_factory=list)
    toasts: list = field(default_factory=list)
    badges: list = field(default_factory=list)
    chapters: list = field(default_factory=list)

    @property
    def intro_s(self) -> float:
        return self.intro["duration"] if self.intro else 0.0

    @property
    def outro_s(self) -> float:
        return self.outro["duration"] if self.outro else 0.0


def make_plan(m: dict, scene: dict, tm, segs, W: int, H: int) -> Plan:
    """操作ログとシーン定義から、完成動画の時間軸での演出計画を作る。"""
    st = scene_style(scene)
    effs = step_effects(scene)
    accent = hex_rgb(st["accent"])
    ch_steps = [s["chapter"] for s in scene["steps"] if "chapter" in s]
    titles = [c["title"] for c in ch_steps]

    intro = _card_opts(st["intro"], INTRO_S, title=scene["title"], subtitle=" → ".join(titles))
    outro = _card_opts(st["outro"], OUTRO_S, title="まとめ", text=scene["title"], items=titles)
    lead = intro["duration"] if intro else 0.0
    T = lambda v: lead + tm(v)

    plan = Plan(W, H, accent, intro, outro, Camera(W, H, st["max_zoom"]))
    off = (m.get("calibration") or {}).get("offset", (0, 0))
    chapter_no, label = 0, None
    for e in m["events"]:
        eff = effs[e["i"]] if e["i"] < len(effs) else {}
        box = None
        if e.get("box"):  # ページ座標 → 画面（動画）座標
            x, y, w, h = e["box"]
            box = (x + off[0], y + off[1], w, h)
        elif e.get("screen_box"):  # 既に画面座標（Calc など）
            box = tuple(e["screen_box"])
        a, b = T(e["v_start"]), T(e["v_end"])
        act = T(e["v_act"]) if "v_act" in e else None

        if e["kind"] == "chapter":
            chapter_no += 1
            label = e.get("title")
            spec = ch_steps[chapter_no - 1]
            plan.chapters.append({"a": a, "b": b, "n": chapter_no, "total": len(ch_steps),
                                  "title": spec["title"], "desc": spec.get("description", "")})
        if "zoom" in eff:
            if e["kind"] == "open_download" and act is not None:
                # ファイルを開く場面: いったん全体へ引き、窓が出てからデータ範囲へ寄る
                plan.camera.add(a, 0.6, None, "out")
                plan.camera.add(act, 0.8, box if eff["zoom"] != "out" else None, eff["zoom"])
            else:
                avail = (act - a - 0.1) if act is not None else 0.6
                plan.camera.add(a, avail, box if eff["zoom"] != "out" else None, eff["zoom"])
        if eff.get("ripple") and act is not None and box:
            plan.ripples.append({"t": act, "pt": (box[0] + box[2] / 2, box[1] + box[3] / 2)})
        if eff.get("spotlight") and box:
            plan.spotlights.append({"a": a + 0.45, "b": b, "box": box, "callout": eff.get("callout")})
        if eff.get("pulse") and act is not None and box:
            plan.pulses.append({"t": act, "box": box})
        if eff.get("toast") and act is not None:
            text = eff["toast"] if isinstance(eff["toast"], str) and eff["toast"] != "auto" else None
            if text is None and e.get("file"):
                text = f"{Path(e['file']).name} を保存しました"
            if text:
                plan.toasts.append({"a": act + 0.35, "b": act + 2.9, "text": text})
        if e.get("caption"):
            plan.captions.append({"a": a, "b": max(b, a + 1.5), "text": e["caption"],
                                  "label": label if st["caption_label"] else None, "box": box})
    for c, nxt in zip(plan.captions, plan.captions[1:]):
        c["b"] = min(c["b"], nxt["a"] - 0.05)
    if st["speed_badge"]:
        for s, e, sp in segs:
            if sp > 1:
                plan.badges.append({"a": T(s), "b": T(e), "speed": sp})
    return plan


def _card_opts(opt, dur, **defaults):
    if not opt:
        return None
    d = {"duration": dur, **defaults}
    if isinstance(opt, dict):
        d.update(opt)
    return d


class FrameReader:
    """録画を固定 30fps で順に読む。時刻が戻ることはない前提（完成動画の時間は単調）。"""

    def __init__(self, video: Path, W: int, H: int):
        self.W, self.H = W, H
        self.p = subprocess.Popen([FFMPEG, "-v", "error", "-i", str(video), "-vf", f"fps={FPS},scale={W}:{H}",
                                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.idx, self.frame = -1, None

    def get(self, t: float) -> Image.Image:
        want = max(0, int(round(t * FPS)))
        n = self.W * self.H * 3
        while self.idx < want:
            buf = self.p.stdout.read(n)
            if len(buf) < n:
                break
            self.idx += 1
            self.frame = buf
        return Image.frombuffer("RGB", (self.W, self.H), self.frame, "raw", "RGB", 0, 1)

    def close(self):
        # 末尾まで読まずに止めることがあるので、デコーダは終了させる
        self.p.kill()
        self.p.stdout.close()
        self.p.wait()


def render(video: Path, out: Path, plan: Plan, tm, raw_start: float, raw_end: float, ffmeta: Path) -> float:
    W, H, accent = plan.W, plan.H, plan.accent
    main_s = tm.duration
    total = plan.intro_s + main_s + plan.outro_s
    n_frames = int(round(total * FPS))
    reader = FrameReader(video, W, H)
    enc = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(ffmeta),
         "-map", "0:v", "-map_metadata", "1", "-map_chapters", "1",
         "-c:v", "libx264", "-preset", os.environ.get("DEMO_X264_PRESET", "medium"), "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    cache: dict = {}
    try:
        for n in range(n_frames):
            t = n / FPS
            if t < plan.intro_s:
                frame = _intro(reader, raw_start, plan, t, cache)
            elif t >= plan.intro_s + main_s:
                frame = _outro(reader, raw_end, plan, t - plan.intro_s - main_s, cache)
            else:
                frame = _main(reader, tm, plan, t, cache)
            enc.stdin.write(frame.tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
        reader.close()
    if enc.returncode != 0:
        raise RuntimeError("ffmpeg のエンコードに失敗しました")
    return total


def _main(reader, tm, plan: Plan, t: float, cache) -> Image.Image:
    W, H, accent = plan.W, plan.H, plan.accent
    raw_t = tm.inverse(t - plan.intro_s)
    src = reader.get(raw_t)
    crop = plan.camera.crop(t)
    x0, y0, s = crop
    frame = src if s <= 1.001 else src.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + W / s, y0 + H / s))

    for sp in plan.spotlights:
        a = ov.fade(t, sp["a"], sp["b"], 0.3, 0.3)
        if a > 0:
            frame = ov.spotlight(frame, plan.camera.rect_to_screen(sp["box"], crop), a, accent)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for pu in plan.pulses:
        p = ov.progress(t, pu["t"], PULSE_S)
        if 0 < p < 1:
            ov.pulse(d, plan.camera.rect_to_screen(pu["box"], crop), p, accent)
    for r in plan.ripples:
        p = ov.progress(t, r["t"], RIPPLE_S)
        if 0 < p < 1:
            ov.ripple(d, plan.camera.to_screen(r["pt"], crop), p, accent)
    for sp in plan.spotlights:
        if sp["callout"]:
            a = ov.fade(t, sp["a"] + 0.25, sp["b"], 0.3, 0.3)
            if a > 0:
                ov.callout(layer, plan.camera.rect_to_screen(sp["box"], crop), sp["callout"], a, accent)
    for to in plan.toasts:
        a = ov.fade(t, to["a"], to["b"], 0.3, 0.35)
        if a > 0:
            ov.toast(layer, to["text"], ov.progress(t, to["a"], 0.4), a)
    for bd in plan.badges:
        a = ov.fade(t, bd["a"], bd["b"], 0.2, 0.2)
        if a > 0:
            ov.badge(layer, bd["speed"], a, accent)
    for c in plan.captions:
        a = ov.fade(t, c["a"], c["b"], 0.25, 0.2)
        if a > 0:
            im = ov.caption_image(c["text"], c["label"], accent)
            # 下に置くと操作対象と重なるときだけ上に出す
            top = False
            if c["box"]:
                bx, by, bw, bh = plan.camera.rect_to_screen(c["box"], crop)
                cx0, cy0 = (W - im.width) / 2, H - im.height - 48
                m = 24
                top = bx < cx0 + im.width + m and bx + bw > cx0 - m and by < cy0 + im.height + m and by + bh > cy0 - m
            rise = (1 - ov.ease_out(ov.progress(t, c["a"], 0.3))) * 18
            y = 44 - rise if top else H - im.height - 48 + rise
            ov.paste(layer, im, ((W - im.width) / 2, y), a)

    frame = frame.convert("RGBA")
    frame.alpha_composite(layer)

    for ch in plan.chapters:
        a = ov.fade(t, ch["a"], ch["b"], 0.35, 0.3)
        bg_a = 1.0 if (ch["n"] == 1 and _chapter_follows_intro(plan) and t <= ch["b"] - 0.3) else a
        if bg_a > 0:
            key = ("chbg", ch["n"])
            if key not in cache:
                cache[key] = ov.blurred(frame.convert("RGB")).convert("RGBA")
                cache[("chcard", ch["n"])] = ov.chapter_card((W, H), ch["n"], ch["total"], ch["title"], ch["desc"], accent)
            frame = Image.blend(frame, cache[key], bg_a)
            card = cache[("chcard", ch["n"])]
            rise = (1 - ov.ease_out(ov.progress(t, ch["a"], 0.4))) * 24
            frame.alpha_composite(ov.with_alpha(card, a), (0, int(rise)))
    return frame.convert("RGB")


def _chapter_follows_intro(plan: Plan) -> bool:
    return bool(plan.intro and plan.chapters and plan.chapters[0]["a"] - plan.intro_s < 1.0)


def _intro(reader, raw_start, plan: Plan, t: float, cache) -> Image.Image:
    if "intro" not in cache:
        bg = ov.blurred(reader.get(raw_start).copy(), 0.4)
        card = ov.title_card(bg.size, plan.intro["title"], plan.intro.get("subtitle", ""), plan.accent)
        cache["intro"] = (bg.convert("RGBA"), card, reader.get(raw_start).copy().convert("RGBA"))
    bg, card, first = cache["intro"]
    d = plan.intro["duration"]
    # 最後の 0.5 秒で本編の最初のフレームへ溶ける。直後が章カードなら、ぼかし背景のままつなぐ
    mix = 0.0 if _chapter_follows_intro(plan) else ov.progress(t, d - 0.5, 0.5)
    frame = Image.blend(bg, first, mix)
    a = ov.fade(t, 0, d, 0.4, 0.5)
    rise = (1 - ov.ease_out(ov.progress(t, 0, 0.6))) * 20
    frame.alpha_composite(ov.with_alpha(card, a), (0, int(rise)))
    return frame.convert("RGB")


def _outro(reader, raw_end, plan: Plan, t: float, cache) -> Image.Image:
    if "outro" not in cache:
        last = reader.get(raw_end).copy()
        bg = ov.blurred(last, 0.35)
        card = ov.summary_card(bg.size, plan.outro["title"], plan.outro.get("items", []), plan.outro.get("text", ""), plan.accent)
        cache["outro"] = (bg.convert("RGBA"), card, last.convert("RGBA"))
    bg, card, last = cache["outro"]
    mix = ov.progress(t, 0, 0.5)
    frame = Image.blend(last, bg, mix)
    a = ov.fade(t, 0.2, plan.outro["duration"], 0.5, 0.01)
    frame.alpha_composite(ov.with_alpha(card, a))
    return frame.convert("RGB")


def srt_lines(plan: Plan, srt_time) -> list[str]:
    return [f"{n}\n{srt_time(c['a'])} --> {srt_time(c['b'])}\n{ov.plain(c['text'])}\n" for n, c in enumerate(plan.captions, 1)]

