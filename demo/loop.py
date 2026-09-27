"""自己確認ループ（P5）: 録画 → 後工程 → 合格判定 → 不合格ならシーン YAML を直して再録画、を合格まで繰り返す。

  python -m demo.loop <scene.yaml> [--fixer rules|claude] [--max 5]

直すのはシーン YAML だけ（アプリやランナーのコードには触らない）。
  rules  : review.json の失敗項目から決まった規則で YAML を直す（人も LLM も介さない）
  claude : `claude -p` に review.json とシーン YAML を渡し、YAML の編集だけを許可して直させる
各反復の review.json と YAML の差分は <out>/iterN/ に残す。
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import shutil
import subprocess
from pathlib import Path

from ruamel.yaml import YAML

from . import scene as scene_mod
from .build import build
from .review import review

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 200
yaml.indent(mapping=2, sequence=4, offset=2)  # 既存 YAML の書式（"  - key:"）を崩さない


def _raw_time(b: dict, t_final: float) -> float:
    """完成動画の時刻 → 録画の時刻（早送り区間を逆にたどる）。"""
    acc = 0.0
    for s, e, sp in b["segments"]:
        d = (e - s) / sp
        if t_final <= acc + d:
            return s + (t_final - acc) * sp
        acc += d
    return b["segments"][-1][1]


def rules_fix(scene_path: Path, run_dir: Path, rv: dict) -> list[str]:
    """review の失敗 → YAML の修正（行った修正を文章で返す）。"""
    doc = yaml.load(scene_path.read_text(encoding="utf-8"))
    ev = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    b = json.loads((run_dir / "build" / "build.json").read_text(encoding="utf-8"))
    off = b["offset"]
    notes = []
    for f in rv["failures"]:
        c, d = f["check"], f["detail"]
        if c == "steps":
            for i, over in d.get("overruns", []):
                spec = next(iter(doc["steps"][i].values()))
                new = int(math.ceil((spec["duration"] + over + 500) / 500) * 500)
                notes.append(f"steps[{i}] wait_for.duration {spec['duration']} → {new}（処理が {over}ms 超過）")
                spec["duration"] = new
        elif c == "freeze" and d.get("at"):
            s, e = d["at"]
            e = e if e is not None else rv["probe"]["duration"]
            t_raw = _raw_time(b, (s + e) / 2 - b.get("lead", 0.0))
            excess = d["longest"] - d["max"] + 0.5
            step = next((x for x in ev["events"] if x["start"] + off <= t_raw <= x["end"] + off), ev["events"][-1])
            spec = next(iter(doc["steps"][step["i"]].values()))
            if isinstance(spec, dict) and spec.get("hold", 0) > 0:
                new = max(0, int(spec["hold"] - excess * 1000) // 100 * 100)
                notes.append(f"steps[{step['i']}] {step['kind']}.hold {spec['hold']} → {new}（静止 {d['longest']}s > {d['max']}s）")
                spec["hold"] = new
            elif isinstance(spec, dict) and "duration" in spec and step["kind"] == "wait_for":
                new = max(500, int(spec["duration"] - excess * 1000) // 100 * 100)
                notes.append(f"steps[{step['i']}] wait_for.duration {spec['duration']} → {new}（静止 {d['longest']}s）")
                spec["duration"] = new
            else:
                pace = doc.setdefault("pace", {})
                cur = pace.get("after_action", 700)
                pace["after_action"] = max(200, cur - 300)
                notes.append(f"pace.after_action {cur} → {pace['after_action']}（静止 {d['longest']}s, steps[{step['i']}] に hold なし）")
        elif c == "duration" and d["duration"] > d["max"]:
            ratio = d["max"] / d["duration"] * 0.95
            for st in doc["steps"]:
                spec = next(iter(st.values()))
                if isinstance(spec, dict) and spec.get("hold"):
                    spec["hold"] = int(spec["hold"] * ratio) // 100 * 100
            notes.append(f"全ステップの hold を {ratio:.2f} 倍（長さ {d['duration']}s > {d['max']}s）")
        elif c.startswith("expect_text:"):
            name = c.split(":", 1)[1]
            for st in doc["steps"]:
                spec = next(iter(st.values()))
                if isinstance(spec, dict) and spec.get("name") == name:
                    spec["hold"] = spec.get("hold", 0) + 500
                    notes.append(f"{name} の hold を +500ms（期待文字列が映っていない）")
        else:
            notes.append(f"{c}: 自動修正の規則なし（{f.get('hint')}）")
    with scene_path.open("w", encoding="utf-8") as fh:
        yaml.dump(doc, fh)
    return notes


CLAUDE_PROMPT = """デモ動画の自己確認で不合格になりました。シーン定義 {scene} だけを編集して、次の録画で合格するように直してください。
- 変更してよいのは hold / duration / pace / chapter.duration / caption の値だけです。ステップの追加・削除・testid の変更はしないでください。
- review.json の hint を手掛かりにし、変更は最小限にしてください。
- 編集が終わったら、変えた項目を1行ずつ出力してください。

review.json の失敗項目:
{failures}
"""


def claude_fix(scene_path: Path, run_dir: Path, rv: dict) -> list[str]:
    prompt = CLAUDE_PROMPT.format(scene=scene_path.as_posix(), failures=json.dumps(rv["failures"], ensure_ascii=False, indent=1))
    r = subprocess.run(["claude", "-p", prompt, "--allowedTools", f"Read,Edit({scene_path.as_posix()})",
                        "--permission-mode", "acceptEdits", "--max-turns", "8"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"claude -p が失敗しました: {(r.stdout + r.stderr).strip()[:300]}")
    return [line for line in r.stdout.splitlines() if line.strip()]


def loop(scene_path: Path, out: Path, fixer: str = "rules", max_iter: int = 5) -> dict:
    from .__main__ import _record
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    history = []
    for n in range(1, max_iter + 1):
        it = out / f"iter{n}"
        before = scene_path.read_text(encoding="utf-8")
        sc = scene_mod.load(scene_path)
        print(f"== iter {n}: record", flush=True)
        _record(scene_path, it, sc)
        build(it)
        rv = review(it)
        entry = {"iter": n, "pass": rv["pass"], "failures": [{"check": f["check"], "detail": f["detail"]} for f in rv["failures"]]}
        print(f"   review: {'PASS' if rv['pass'] else 'FAIL ' + ', '.join(f['check'] for f in rv['failures'])}", flush=True)
        if rv["pass"]:
            history.append(entry)
            break
        notes = (rules_fix if fixer == "rules" else claude_fix)(scene_path, it, rv)
        after = scene_path.read_text(encoding="utf-8")
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "before", "after"))
        (it / "fix.diff").write_text(diff, encoding="utf-8")
        entry["fix"] = notes
        for x in notes:
            print(f"   fix: {x}", flush=True)
        history.append(entry)
        if before == after:
            print("   YAML が変わらなかったため停止", flush=True)
            break
    result = {"scene": str(scene_path), "fixer": fixer, "iterations": len(history), "pass": history[-1]["pass"], "history": history}
    (out / "loop.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--fixer", choices=["rules", "claude"], default="rules")
    ap.add_argument("--max", type=int, default=5)
    a = ap.parse_args()
    sc = scene_mod.load(a.scene)
    r = loop(a.scene, a.out or Path("out") / sc["id"] / "loop", a.fixer, a.max)
    print(json.dumps({k: r[k] for k in ("iterations", "pass")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
