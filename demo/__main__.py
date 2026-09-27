"""デモ動画ツールの入口。

  python -m demo dryrun <scene.yaml>            録画せず最速で操作を通し、セレクタを確認
  python -m demo record <scene.yaml>            録画（raw + events.json）。mode: desktop は Docker で実行
  python -m demo build  <run_dir>               後工程（final.mp4 / subtitles.srt / chapters.json）
  python -m demo review <run_dir>               合格判定（review.json）
  python -m demo make   <scene.yaml>            record → build → review を1コマンドで
  python -m demo loop   <scene.yaml> [--fixer rules|claude] [--max N]   合格するまで YAML を直して撮り直す
  python -m demo repro  <scene.yaml> [-n 3]     同じシーンを N 回撮って再現性を確認（browser モード）
出力先の既定は out/<scene id>/<cmd>/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _record(scene_path: Path, out: Path, sc: dict, headed: bool = False, trace: bool = False) -> None:
    if sc["mode"] == "desktop":
        from .docker_run import record_desktop
        if record_desktop(scene_path, out) != 0:
            raise SystemExit("desktop 録画に失敗しました")
    else:
        from .record import record
        record(scene_path, out, headless=not headed, trace=trace)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("dryrun", "record", "make"):
        s = sub.add_parser(name)
        s.add_argument("scene", type=Path)
        s.add_argument("--out", type=Path)
        s.add_argument("--headed", action="store_true")
        s.add_argument("--trace", action="store_true")
    for name in ("build", "review"):
        s = sub.add_parser(name)
        s.add_argument("run_dir", type=Path)
    s = sub.add_parser("loop")
    s.add_argument("scene", type=Path)
    s.add_argument("--out", type=Path)
    s.add_argument("--fixer", choices=["rules", "claude"], default="rules")
    s.add_argument("--max", type=int, default=5)
    s = sub.add_parser("repro")
    s.add_argument("scene", type=Path)
    s.add_argument("--out", type=Path)
    s.add_argument("-n", type=int, default=3)
    a = ap.parse_args(argv)

    if a.cmd in ("loop", "repro"):
        from . import scene as scene_mod
        sc = scene_mod.load(a.scene)
        if a.cmd == "loop":
            from .loop import loop
            r = loop(a.scene, a.out or Path("out") / sc["id"] / "loop", a.fixer, a.max)
            print(json.dumps({k: r[k] for k in ("iterations", "pass")}, ensure_ascii=False))
        else:
            from .repro import run as repro
            r = repro(a.scene, a.out or Path("out") / sc["id"] / "repro", a.n)
            print(json.dumps({k: r[k] for k in ("durations", "max_timing_spread", "max_frame_mad", "checks", "pass")}, ensure_ascii=False))
        return 0 if r["pass"] else 1

    if a.cmd == "build":
        from .build import build
        info = build(a.run_dir)
        print(json.dumps({k: info[k] for k in ("duration", "raw_span", "captions", "final")}, ensure_ascii=False))
        return 0
    if a.cmd == "review":
        from .review import review
        r = review(a.run_dir)
        print(json.dumps({"pass": r["pass"], "failures": r["failures"]}, ensure_ascii=False, indent=1))
        return 0 if r["pass"] else 1

    from . import scene as scene_mod
    sc = scene_mod.load(a.scene)
    out = a.out or Path("out") / sc["id"] / ("dryrun" if a.cmd == "dryrun" else "run")

    if a.cmd == "dryrun":
        from .record import record
        m = record(a.scene, out, dry=True, headless=not a.headed)
        print(f"dryrun OK: {len(m['events'])} steps, {m['ended'] - m['started']:.1f}s")
        return 0

    _record(a.scene, out, sc, a.headed, a.trace)
    print(f"recorded -> {out}")
    if a.cmd == "record":
        return 0
    from .build import build
    from .review import review
    info = build(out)
    r = review(out)
    print(json.dumps({"final": info["final"], "duration": info["duration"], "pass": r["pass"], "failures": r["failures"]},
                     ensure_ascii=False, indent=1))
    return 0 if r["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
