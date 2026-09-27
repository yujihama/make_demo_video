"""見た目の審査（Claude Code）: 完成動画の要所のコマを書き出し、作業中の Claude Code が見て、問題と直し方を JSON で返す。

機械の判定（review.py）では分からない「字幕が大事な所を隠している」「強調が別の所を指している」
「寄りすぎて数字が切れている」「訳が画面と合っていない」などを見る。
直し方（fix）は自己確認ループ（loop.py）がそのまま YAML に反映できる形で返させる。

  bin/demo vision out/<id>/run [--lang en]      審査だけ（build/vision.json）
  bin/demo review out/<id>/run --vision         機械の判定＋見た目の審査
依頼は out/<id>/_handoff/ に書き出される（demo/handoff.py）。審査の手順はスキル demo-video の reference/vision-review.md。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import scene as scene_mod
from .build import TimeMap, build_dir
from .handoff import ask
from .compose import COUNTUP_S, frame_at, make_plan
from .i18n import localize
from .overlays import plain

MAX_FRAMES = 20
FIX_PATHS = ["hold", "caption", "effect.zoom", "effect.spotlight", "effect.ripple", "effect.callout", "style.max_zoom"]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["overall", "summary", "findings"],
    "properties": {
        "overall": {"type": "string", "enum": ["pass", "fail"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["frame", "step", "severity", "category", "problem", "suggestion", "fix"],
                "properties": {
                    "frame": {"type": "integer"},
                    "step": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "category": {"type": "string", "enum": ["caption_occlusion", "readability", "emphasis_target",
                                                            "content_mismatch", "framing", "layout", "language", "other"]},
                    "problem": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "fix": {"anyOf": [{"type": "null"}, {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["path", "value"],
                        "properties": {"path": {"type": "string", "enum": FIX_PATHS}, "value": {"type": "string"}},
                    }]},
                },
            },
        },
    },
}

SYSTEM = """あなたは製品デモ動画の品質を審査する映像ディレクターです。
動画は業務アプリの操作を録画し、後から字幕・ズーム・強調（波紋、スポットライト、吹き出し、数え上げ、キー表示）・章カードを重ねたものです。
渡されたコマ画像を1枚ずつ見て、視聴者の理解を妨げる見た目の問題だけを指摘してください。好みの問題は指摘しません。"""

RUBRIC = """## 審査の観点
1. caption_occlusion: 字幕や吹き出しが、そのコマで見せたい操作対象・結果・数値を隠していないか
2. readability: 文字（字幕・カード・アプリの画面）が読める大きさと濃さか
3. emphasis_target: 波紋・スポットライト・吹き出し・数え上げが、説明している対象を正しく指しているか
4. content_mismatch: 字幕の内容と、そのコマの画面の内容が食い違っていないか
5. framing: カメラの寄りで、見せたい情報（表の列・数値・ボタン）が画面外に切れていないか
6. layout: カードや字幕の文字が枠からはみ出したり、重なったり、途中で切れたりしていないか
7. language: 字幕・カードの文言が指定の言語になっているか（アプリの画面そのものは元の言語のままでよい）

## 重さ
- high: 伝えたいことが伝わらない（数値が隠れて読めない、別の物を強調している、文字が切れている）
- medium: 伝わるが見づらい、誤解しかねない
- low: 直すとよりよい

## 直し方（fix）
自動で直せるものは fix に入れます。step はコマの説明にあるステップ番号です。直せないもの・直し方が決まらないものは fix を null にします。
- hold: そのステップを長く見せる。value は追加するミリ秒（例 "800"）
- caption: 字幕の文を置き換える。value は新しい字幕（指定の言語で、**語** の強調記法を使ってよい）
- effect.zoom: カメラの寄り方。value は "out"（引く）/ "fit"（対象全体が収まる）/ "focus"（寄る）/ "1.2" などの拡大率
- effect.spotlight / effect.ripple: value は "false" で外す
- effect.callout: 吹き出しの文。value は新しい文（指定の言語）
- style.max_zoom: 全体の最大拡大率。value は "1.3" など（step は null）

問題が無ければ findings は空、overall は "pass" にします。high が1つでもあれば overall は "fail" です。"""


def _load(run_dir: Path, lang: str | None):
    m = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    src = scene_mod.load(m["scene_path"])
    bdir = build_dir(run_dir, src, lang)
    b = json.loads((bdir / "build.json").read_text(encoding="utf-8"))
    off = b["offset"]
    for e in m["events"]:
        for k in ("start", "act", "end", "type_end"):
            if k in e:
                e[f"v_{k}"] = round(e[k] + off, 3)
    segs = [tuple(s) for s in b["segments"]]
    return m, localize(src, lang), b, bdir, segs


def pick_frames(plan) -> list[dict]:
    """審査するコマ: 字幕が出そろい、カメラが落ち着いた時点と、各演出の見せ場。"""
    shots = []
    if plan.intro:
        shots.append((plan.intro_s * 0.6, None, "intro", plan.intro["title"]))
    for c in plan.chapters:
        shots.append((c["a"] + (c["b"] - c["a"]) * 0.6, c["i"], "chapter_card", c["title"]))
    for c in plan.captions:
        shots.append((c["a"] + (c["b"] - c["a"]) * 0.6, c["i"], "caption", plain(c["text"])))
    for sp in plan.spotlights:
        shots.append((min(sp["b"] - 0.1, sp["a"] + 0.8), sp["i"], "spotlight", sp.get("callout") or ""))
    for cu in plan.countups:
        shots.append((min(cu["b"] - 0.1, cu["a"] + COUNTUP_S + 0.2), cu["i"], "countup", f"{cu['label']} {cu['to']:g}{cu['suffix']}"))
    for k in plan.keys:
        shots.append((k["end"] + 0.2, k["i"], "keystrokes", k["text"]))
    for to in plan.toasts:
        shots.append((to["a"] + 0.8, to["i"], "toast", to["text"]))
    for cp in plan.compares:
        shots.append((cp["a"] + 1.8, cp["i"], "compare_card", cp["title"]))
    if plan.outro:  # まとめカードの中ほど
        shots.append((plan.intro_s + plan.main_s + plan.outro_s * 0.6, None, "outro", plan.outro["title"]))
    shots.sort(key=lambda s: s[0])
    picked = []
    for s in shots:  # 近すぎるコマはまとめる
        if picked and s[0] - picked[-1][0] < 0.35:
            continue
        picked.append(s)
    if len(picked) > MAX_FRAMES:  # 字幕のコマを優先して間引く
        keep = [s for s in picked if s[2] == "caption"]
        rest = [s for s in picked if s[2] != "caption"]
        picked = sorted(keep + rest[: max(0, MAX_FRAMES - len(keep))], key=lambda s: s[0])[:MAX_FRAMES]
    return [{"frame": n, "t": round(t, 2), "step": step, "kind": kind, "expect": text}
            for n, (t, step, kind, text) in enumerate(picked)]


def review_visual(run_dir: str | Path, lang: str | None = None) -> dict:
    run_dir = Path(run_dir)
    m, scene, b, bdir, segs = _load(run_dir, lang)
    tm = TimeMap(segs)
    video = Path(b["source"]) if Path(b["source"]).exists() else run_dir / Path(b["source"]).name
    plan = make_plan(m, scene, tm, segs, *_probe_size(video))
    frames = pick_frames(plan)
    imgs = frame_at(video, plan, tm, b["trim_start"], b["trim_start"] + b["raw_span"], [f["t"] for f in frames])
    vdir = bdir / "vision"
    vdir.mkdir(exist_ok=True)
    paths = []
    for f, im in zip(frames, imgs):
        p = vdir / f"frame_{f['frame']:02d}.jpg"
        im.resize((1280, 720)).save(p, quality=88)
        paths.append(p)
    steps = scene["steps"]
    lines = []
    for f in frames:
        kind = next(iter(steps[f["step"]])) if f["step"] is not None else "-"
        lines.append(f"- コマ {f['frame']}（{f['t']:.1f} 秒, ステップ {f['step'] if f['step'] is not None else '-'}: {kind}, "
                     f"見せ場: {f['kind']}）: {f['expect']}")
    prompt = (f"## 動画\n題名: {scene['title']}\n字幕とカードの言語: {plan.lang}\n\n"
              f"## コマ（画像は番号順に並んでいます）\n" + "\n".join(lines) + "\n\n" + RUBRIC)
    result = ask(f"vision-{m['scene']}-{plan.lang}", SYSTEM, prompt, SCHEMA, paths, workdir=run_dir.parent,
                 labels=[f"{f['t']:.1f}s {f['kind']}" for f in frames])
    for fd in result["findings"]:  # コマ番号からステップを補う
        if fd.get("step") is None and 0 <= fd["frame"] < len(frames):
            fd["step"] = frames[fd["frame"]]["step"]
    report = {"lang": plan.lang, "frames": frames, **result}
    (bdir / "vision.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _probe_size(video: Path):
    from .crv import probe
    info = probe(video)
    return info["width"], info["height"]
