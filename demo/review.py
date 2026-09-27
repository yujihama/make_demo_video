"""合格判定（P5, demo-review 代替）: 完成動画一式を機械的に確認し、review.json に結果と直し方の手掛かりを出す。

判定項目（シーン YAML の review で閾値を上書きできる）:
  steps       全ステップが実行され、wait_for の超過（overrun）がない
  format      1920x1080 / 25fps 以上 / H.264
  duration    min_duration ≤ 長さ ≤ max_duration
  black       黒画面（0.5 秒以上）がない
  freeze      静止区間の最長 ≤ max_freeze
  captions    字幕の本数 = caption 付きステップ数
  chapters    章の本数 = chapter ステップ数
  expect_text 名前付きステップの時点で画面に期待文字列があり、その時点の動画フレームが実画面と一致する
  cursor      （desktop）実カーソルの位置誤差 ≤ 2px
  readability 字幕ごとに、表示秒数 ≥ 文字数 / 読む速さ（言語別。ja 7 字/秒、en 15 字/秒）+ 0.4 秒
  vision      （--vision のとき）Claude Code が要所のコマを見て、high の指摘が無い

言語を指定すると build-<lang>/ を判定し、結果は review-<lang>.json に出す（元の言語は review.json）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from . import crv
from . import scene as scene_mod
from .build import build_dir
from .i18n import localize, scene_lang
from .sync import gray_at

MATCH_MAD = 6.0


def review_path(run_dir: Path, sc: dict | None, lang: str | None) -> Path:
    base = scene_lang(sc) if sc else "ja"
    return Path(run_dir) / ("review.json" if not lang or lang == base else f"review-{lang}.json")


def review(run_dir: str | Path, lang: str | None = None, vision: bool = False) -> dict:
    run_dir = Path(run_dir)
    m = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    src = scene_mod.load(m["scene_path"]) if Path(m["scene_path"]).exists() else None
    bdir = build_dir(run_dir, src, lang)
    b = json.loads((bdir / "build.json").read_text(encoding="utf-8"))
    sc = localize(src, lang) if src else {"steps": [], "review": {}}
    crit = {"min_duration": 5, "max_duration": 180, "max_freeze": 5, "expect_text": [], **sc.get("review", {})}
    final = Path(b["final"])
    info = crv.probe(final)
    det = crv.detect(final)
    checks, failures = {}, []

    def check(name, ok, detail, hint=None):
        checks[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append({"check": name, "detail": detail, "hint": hint})

    n_steps = len(sc["steps"])
    overruns = [e for e in m["events"] if e.get("overrun_ms")]
    check("steps", len(m["events"]) == n_steps and not overruns,
          {"executed": len(m["events"]), "defined": n_steps, "overruns": [(e["i"], e["overrun_ms"]) for e in overruns]},
          "wait_for の duration を overrun_ms 以上に伸ばす" if overruns else "失敗したステップの testid を確認する")
    check("format", info["width"] == 1920 and info["height"] == 1080 and info["fps"] >= 25 and info["codec"] == "h264",
          {k: info[k] for k in ("width", "height", "fps", "codec")})
    check("duration", crit["min_duration"] <= info["duration"] <= crit["max_duration"],
          {"duration": info["duration"], "min": crit["min_duration"], "max": crit["max_duration"]},
          "hold / pace / chapter.duration を調整する")
    check("black", not det["black"], det["black"])
    # 静止の判定は本編だけ（イントロ・まとめのカードは意図した静止なので除く）
    lo = b.get("lead", 0.0)
    hi = lo + b.get("main_duration", info["duration"])
    spans = [(max(s, lo), min(e if e is not None else info["duration"], hi)) for s, e in det["freeze"]]
    det["freeze"] = [(round(s, 3), round(e, 3)) for s, e in spans if e > s]
    freezes = [round(e - s, 2) for s, e in det["freeze"]]
    # 字幕が出ている間の静止は「読んでいる時間」なので、その字幕の表示秒数 + 0.5 秒までは許す
    caps = b.get("readability", [])

    def allowed(s, e):
        over = [c["shown_s"] for c in caps if c["a"] < e and c["b"] > s]
        return max([crit["max_freeze"]] + [x + 0.5 for x in over])

    excess = [(round(f - allowed(s, e), 2), f, (s, e)) for f, (s, e) in zip(freezes, det["freeze"])]
    worst = max(excess, default=(0, 0, None))
    longest, where = worst[1], worst[2]
    check("freeze", worst[0] <= 0, {"longest": longest, "at": where, "max": crit["max_freeze"],
                                    "allowed_here": round(allowed(*where), 2) if where else None},
          f"final の {where} 付近の静止が長い。該当ステップの hold を減らすか、待ちなら wait_for の duration を短くする")
    n_caps = sum(1 for _, _, s in scene_mod.steps(sc) if s.get("caption")) if sc["steps"] else b["captions"]
    check("captions", b["captions"] == n_caps, {"srt": b["captions"], "steps": n_caps})
    n_ch = sum(1 for _, k, _ in scene_mod.steps(sc) if k == "chapter") if sc["steps"] else len(b["chapters"])
    check("chapters", len(b["chapters"]) == n_ch, {"chapters": len(b["chapters"]), "steps": n_ch})

    # 期待文字列: DOM テキストで状態を確認し、同時刻の動画フレームが実画面スクリーンショットと一致するかを見る
    off = b["offset"]
    by_name = {e["name"]: e for e in m["events"] if e.get("name")}
    calib = m.get("calibration", {}).get("offset", (0, 0))
    for exp in crit["expect_text"]:
        e = by_name.get(exp["after"])
        if not e:
            check(f"expect_text:{exp['after']}", False, "該当する name のステップがない", "review.expect_text.after を steps の name に合わせる")
            continue
        text_ok = exp["text"] in e.get("snap_text", "")
        snap = run_dir / "snaps" / f"{exp['after']}.png"
        mad = None
        if snap.exists():
            ref = Image.open(snap).convert("L")
            t = e["snap_at"] + off
            source = Path(b["source"]) if Path(b["source"]).exists() else run_dir / Path(b["source"]).name
            frame = gray_at(source, t, 1920, 1080)
            x0, y0 = int(calib[0]), int(calib[1])
            crop = frame[y0:y0 + ref.height, x0:x0 + ref.width]
            r = np.asarray(ref, dtype=float)[: crop.shape[0], : crop.shape[1]]
            small = lambda a: np.asarray(Image.fromarray(a.astype(np.uint8)).resize((480, 270)), dtype=float)
            mad = round(float(np.abs(small(crop) - small(r)).mean()), 2)
        check(f"expect_text:{exp['after']}", text_ok and (mad is None or mad <= MATCH_MAD),
              {"text": exp["text"], "in_dom": text_ok, "frame_vs_screen_mad": mad},
              "期待文字列が画面に出ていない。直前の wait_for / hold が足りないか、text が違う")
    if m.get("mode") == "desktop":
        err = m.get("max_cursor_err_px")
        check("cursor", err is not None and err <= 2.0, {"max_err_px": err, "calibration": m.get("calibration")})

    # 読み切れる字幕: 表示秒数が「文字数 / 読む速さ + 反応時間」に足りているか
    short = [r for r in b.get("readability", []) if not r["ok"]]
    check("readability", not short, {"lang": b.get("lang"), "short": short},
          "字幕が速すぎて読み切れない。該当ステップの hold を short_s 秒以上伸ばすか、字幕を短くする")

    vis, suggested = None, []
    if vision:
        from .vision import review_visual
        vis = review_visual(run_dir, lang)
        bad = [f for f in vis["findings"] if f["severity"] in ("high", "medium")]
        for f in bad:
            failures.append({"check": f"vision:{f['category']}", "detail": {k: f[k] for k in ("frame", "step", "severity", "problem")},
                             "hint": f["suggestion"], "fix": f.get("fix"), "severity": f["severity"]})
        ok = vis["overall"] == "pass" and not any(f["severity"] == "high" for f in vis["findings"])
        checks["vision"] = {"ok": ok, "detail": {"summary": vis["summary"], "findings": len(vis["findings"]),
                                                 "high": sum(f["severity"] == "high" for f in vis["findings"])}}
        if ok:  # medium だけなら合格扱い。直し方は suggested として残し、ループが他の理由で回るときに一緒に反映する
            suggested = [f for f in failures if f["check"].startswith("vision:") and f.get("severity") == "medium"]
            failures = [f for f in failures if f not in suggested]

    result = {"lang": b.get("lang"), "final": str(final), "probe": info, "checks": checks,
              "failures": failures, "pass": not failures, "suggested": suggested, "vision": vis}
    review_path(run_dir, src, lang).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
