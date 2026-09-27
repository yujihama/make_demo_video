"""再現性チェック（P2 の合格判定）: 同じシーンを N 回録画し、同じ動画になっているかを比べる。

判定:
  - 全ステップが成功（例外なし）し、全ステップが data-testid で指定されている
  - 動画長の差 ≤ 0.5 秒
  - 各ステップの操作時刻（動画時刻）の差 ≤ 0.35 秒
  - 各ステップの操作直前・直後フレームの画素差（480x270 グレー、平均絶対差）≤ 3.0
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import scene as scene_mod
from .crv import probe
from .record import record
from .sync import gray_at, offset

TOL_DURATION, TOL_TIMING, TOL_MAD = 0.5, 0.35, 3.0


def to_video_time(manifest: dict) -> dict:
    off = offset(Path(manifest["video"]), manifest["sync_host"])
    manifest["offset"] = off
    for e in manifest["events"]:
        for k in ("start", "act", "end"):
            if k in e:
                e[f"v_{k}"] = round(e[k] + off, 3)
    return manifest


def check_points(m: dict) -> list[tuple[str, float]]:
    """比較点: 各ステップの中央と、ポインタ操作の直前（カーソル到着後で静止している時点）。
    章カードのフェードなど遷移の途中は1フレームのずれで画素差が跳ねるため比較点にしない。"""
    pts = []
    for e in m["events"]:
        label = f"{e['i']}:{e['kind']}"
        pts.append((f"{label}@mid", (e["v_start"] + e["v_end"]) / 2))
        if "act" in e and e["kind"] != "wait_for":
            pts.append((f"{label}@act-0.1", e["v_act"] - 0.1))
    return pts


def mad_best(video: Path, t: float, ref: np.ndarray, frame: float = 0.04) -> float:
    """±1フレームの範囲で最も近いフレームとの平均絶対差。"""
    return min(float(np.abs(gray_at(video, t + d) - ref).mean()) for d in (-frame, 0, frame))


def run(scene_path: Path, out: Path, n: int = 3) -> dict:
    sc = scene_mod.load(scene_path)
    non_testid = [k for _, k, s in scene_mod.steps(sc) if k in ("click", "hover", "upload", "download", "type", "wait_for") and not s.get("testid")]
    runs = []
    for r in range(1, n + 1):
        print(f"== run {r}/{n}", flush=True)
        m = to_video_time(record(scene_path, out / f"r{r}"))
        m["probe"] = probe(Path(m["video"]))
        runs.append(m)
        (out / f"r{r}" / "events.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")

    base = runs[0]
    durations = [m["probe"]["duration"] for m in runs]
    timing_rows, frame_rows = [], []
    for j, e in enumerate(base["events"]):
        ts = [m["events"][j].get("v_act", m["events"][j]["v_start"]) for m in runs]
        timing_rows.append({"step": f"{e['i']}:{e['kind']}", "times": ts, "spread": round(max(ts) - min(ts), 3)})
    pts = [check_points(m) for m in runs]
    for k, (label, t0) in enumerate(pts[0]):
        g0 = gray_at(Path(base["video"]), t0)
        mads = [round(mad_best(Path(m["video"]), pts[i][k][1], g0), 2)
                for i, m in enumerate(runs[1:], start=1)]
        frame_rows.append({"point": label, "mad_vs_r1": mads, "max": max(mads) if mads else 0})

    result = {
        "scene": sc["id"], "runs": n, "durations": durations,
        "duration_spread": round(max(durations) - min(durations), 3),
        "offsets": [m["offset"] for m in runs],
        "timing": timing_rows, "frames": frame_rows,
        "max_timing_spread": max(r["spread"] for r in timing_rows),
        "max_frame_mad": max(r["max"] for r in frame_rows),
        "non_testid_steps": non_testid,
    }
    result["checks"] = {
        "all_steps_ok": all(len(m["events"]) == len(base["events"]) for m in runs),
        "testid_only": not non_testid,
        "duration": result["duration_spread"] <= TOL_DURATION,
        "timing": result["max_timing_spread"] <= TOL_TIMING,
        "frames": result["max_frame_mad"] <= TOL_MAD,
    }
    result["pass"] = all(result["checks"].values())
    (out / "repro.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("-n", type=int, default=3)
    a = ap.parse_args()
    r = run(a.scene, a.out, a.n)
    print(json.dumps({k: r[k] for k in ("durations", "offsets", "max_timing_spread", "max_frame_mad", "checks", "pass")}, ensure_ascii=False))
