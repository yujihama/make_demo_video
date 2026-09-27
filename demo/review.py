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
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from . import crv
from . import scene as scene_mod
from .sync import gray_at

MATCH_MAD = 6.0


def review(run_dir: str | Path) -> dict:
    run_dir = Path(run_dir)
    m = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    b = json.loads((run_dir / "build" / "build.json").read_text(encoding="utf-8"))
    sc = scene_mod.load(m["scene_path"]) if Path(m["scene_path"]).exists() else {"steps": [], "review": {}}
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
    end = info["duration"]
    freezes = [round((e if e is not None else end) - s, 2) for s, e in det["freeze"]]
    longest = max(freezes, default=0)
    where = det["freeze"][freezes.index(longest)] if freezes else None
    check("freeze", longest <= crit["max_freeze"], {"longest": longest, "at": where, "max": crit["max_freeze"]},
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
            frame = gray_at(Path(b["source"]), t, 1920, 1080)
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

    result = {"final": str(final), "probe": info, "checks": checks, "failures": failures, "pass": not failures}
    (run_dir / "review.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
