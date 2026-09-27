"""デモ動画ツールの入口。

  bin/demo dryrun    <scene.yaml>                      録画せず最速で操作を通し、セレクタを確認
  bin/demo record    <scene.yaml>                      録画（raw + events.json）。mode: desktop は Docker で実行
  bin/demo build     <run_dir> [--lang en]             後工程（final.mp4 / subtitles.srt / chapters.json）
  bin/demo review    <run_dir> [--lang en] [--vision]  合格判定（review.json）。--vision で Claude の見た目の審査も
  bin/demo make      <scene.yaml> [--lang ja,en] [--vision]   record → build → review を1コマンドで
  bin/demo loop      <scene.yaml> [--lang ja,en] [--vision] [--fixer rules|claude] [--max N]
                                                       合格するまで YAML を直して撮り直す
  bin/demo repro     <scene.yaml> [-n 3]               同じシーンを N 回撮って再現性を確認（browser モード）
  bin/demo translate <scene.yaml> --lang en [--force]  翻訳ファイル scenes/<id>.en.yaml を作る（Claude）
  bin/demo vision    <run_dir> [--lang en]             Claude の見た目の審査だけ

--lang はカンマ区切りで複数指定できる（録画は1回、後工程と判定を言語ごとに行う）。省略時はシーンの言語。
出力先の既定は out/<scene id>/<cmd>/。言語ごとの完成動画は build/（元の言語）と build-<lang>/。
Claude を呼ぶ手段は DEMO_CLAUDE_BACKEND（auto / api / cli / file）で選ぶ（demo/claude_io.py）。
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


def _langs(v: str | None) -> list[str | None]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else [None]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("dryrun", "record", "make"):
        s = sub.add_parser(name)
        s.add_argument("scene", type=Path)
        s.add_argument("--out", type=Path)
        s.add_argument("--headed", action="store_true")
        s.add_argument("--trace", action="store_true")
        if name == "make":
            s.add_argument("--lang")
            s.add_argument("--vision", action="store_true")
    for name in ("build", "review", "vision"):
        s = sub.add_parser(name)
        s.add_argument("run_dir", type=Path)
        s.add_argument("--lang")
        if name == "review":
            s.add_argument("--vision", action="store_true")
    s = sub.add_parser("loop")
    s.add_argument("scene", type=Path)
    s.add_argument("--out", type=Path)
    s.add_argument("--fixer", choices=["rules", "claude"], default="rules")
    s.add_argument("--max", type=int, default=5)
    s.add_argument("--lang")
    s.add_argument("--vision", action="store_true")
    s = sub.add_parser("repro")
    s.add_argument("scene", type=Path)
    s.add_argument("--out", type=Path)
    s.add_argument("-n", type=int, default=3)
    s = sub.add_parser("translate")
    s.add_argument("scene", type=Path)
    s.add_argument("--lang", required=True)
    s.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    from .claude_io import NeedsResponse
    try:
        return _run(a)
    except NeedsResponse as e:
        print(str(e), file=sys.stderr)
        return 3


def _run(a) -> int:
    from . import scene as scene_mod

    if a.cmd == "translate":
        from .translate import translate
        for lang in _langs(a.lang):
            print(f"翻訳ファイルを作成しました: {translate(a.scene, lang, a.force)}")
        return 0
    if a.cmd == "build":
        from .build import build
        for lang in _langs(a.lang):
            info = build(a.run_dir, lang=lang)
            print(json.dumps({k: info.get(k) for k in ("lang", "duration", "captions", "final")}, ensure_ascii=False))
        return 0
    if a.cmd == "review":
        from .review import review
        ok = True
        for lang in _langs(a.lang):
            r = review(a.run_dir, lang, vision=a.vision)
            ok &= r["pass"]
            print(json.dumps({"lang": r["lang"], "pass": r["pass"], "failures": r["failures"]}, ensure_ascii=False, indent=1))
        return 0 if ok else 1
    if a.cmd == "vision":
        from .vision import review_visual
        for lang in _langs(a.lang):
            v = review_visual(a.run_dir, lang)
            print(json.dumps({k: v[k] for k in ("lang", "overall", "summary", "findings")}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd in ("loop", "repro"):
        sc = scene_mod.load(a.scene)
        if a.cmd == "loop":
            from .loop import loop
            langs = [x for x in _langs(a.lang) if x] or None
            r = loop(a.scene, a.out or Path("out") / sc["id"] / "loop", a.fixer, a.max, langs, a.vision)
            print(json.dumps({k: r[k] for k in ("iterations", "pass")}, ensure_ascii=False))
        else:
            from .repro import run as repro
            r = repro(a.scene, a.out or Path("out") / sc["id"] / "repro", a.n)
            print(json.dumps({k: r[k] for k in ("durations", "max_timing_spread", "max_frame_mad", "checks", "pass")},
                             ensure_ascii=False))
        return 0 if r["pass"] else 1

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
    ok = True
    for lang in _langs(a.lang):
        info = build(out, lang=lang)
        r = review(out, lang, vision=a.vision)
        ok &= r["pass"]
        print(json.dumps({"lang": info.get("lang"), "final": info["final"], "duration": info["duration"],
                          "pass": r["pass"], "failures": r["failures"]}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
