"""自己確認ループ（P5）: 録画 → 後工程 → 合格判定 → 不合格ならシーン YAML を直して再録画、を合格まで繰り返す。

  bin/demo loop <scene.yaml> [--lang ja,en] [--vision] [--fixer rules|claude] [--max 5]

直すのはシーン YAML だけ（アプリやランナーのコードには触らない）。
  rules  : review.json の失敗項目から決まった規則で YAML を直す（人も LLM も介さない）
  claude : `claude -p` に review.json とシーン YAML を渡し、YAML の編集だけを許可して直させる
各反復の review.json と YAML の差分は <out>/iterN/ に残す。

--lang を複数指定すると、録画は1回のまま言語ごとに後工程と判定を行い、全言語が合格するまで回す。
--vision を付けると Claude の見た目の審査も判定に入れ、その直し方（fix）も反映する。
字幕の文言の直し（caption / effect.callout）は、元の言語ならシーン YAML に、それ以外は翻訳ファイルに入れる。
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import shutil
import subprocess
from pathlib import Path

from . import scene as scene_mod
from . import yamlio
from .build import build, build_dir
from .i18n import scene_lang, translation_path
from .review import review

def _raw_time(b: dict, t_final: float) -> float:
    """完成動画の時刻 → 録画の時刻（早送り区間を逆にたどる）。"""
    acc = 0.0
    for s, e, sp in b["segments"]:
        d = (e - s) / sp
        if t_final <= acc + d:
            return s + (t_final - acc) * sp
        acc += d
    return b["segments"][-1][1]


def rules_fix(scene_path: Path, run_dir: Path, rv: dict, lang: str | None = None, held: dict | None = None) -> list[str]:
    """review の失敗 → YAML の修正（行った修正を文章で返す）。
    held は同じ反復の中でステップに足した hold（言語をまたいで共有し、足し算でなく大きい方を採る）。"""
    doc = yamlio.load(scene_path)
    ev = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    src = scene_mod.load(scene_path)
    b = json.loads((build_dir(run_dir, src, lang) / "build.json").read_text(encoding="utf-8"))
    off = b["offset"]
    tr_doc, tr_path = None, None
    if lang and lang != scene_lang(src):
        tr_path = translation_path(src, lang)
        tr_doc = yamlio.load(tr_path)
    notes = []
    held = {} if held is None else held  # 同じステップへの hold 追加は1回（大きい方）にまとめる

    def add_hold(i: int, ms: int, why: str):
        if held.get(i, 0) >= ms:
            return
        spec = next(iter(doc["steps"][i].values()))
        base = spec.get("hold", 0) - held.get(i, 0)
        spec["hold"] = base + ms
        held[i] = ms
        notes.append(f"steps[{i}] hold {base} → {base + ms}（{why}）")

    for f in rv["failures"] + rv.get("suggested", []):
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
            excess = d["longest"] - (d.get("allowed_here") or d["max"]) + 0.5
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
        elif c == "readability":
            for r in d["short"]:
                ms = int(math.ceil((r["short_s"] + 0.3) * 10) * 100)
                add_hold(r["step"], ms, f"字幕 {r['chars']} 字に {r['need_s']}s 必要、{r['shown_s']}s しか出ていない（{d['lang']}）")
        elif c.startswith("vision:") and f.get("fix"):
            step, fx = f["detail"].get("step"), f["fix"]
            path, value = fx["path"], fx["value"]
            if path == "style.max_zoom":
                doc.setdefault("style", {})["max_zoom"] = float(value)
                notes.append(f"style.max_zoom → {value}（見た目の審査: {f['detail']['problem']}）")
                continue
            if step is None or step >= len(doc["steps"]):
                notes.append(f"{c}: 対象のステップが分からないため直せない（{f['hint']}）")
                continue
            if path == "hold":
                add_hold(step, int(float(value)), f"見た目の審査: {f['detail']['problem']}")
            elif path in ("caption", "effect.callout") and tr_doc is not None:
                entry = tr_doc["steps"][step]
                _set_path(entry, path, value)
                notes.append(f"{tr_path.name} steps[{step}].{path} → {value}（見た目の審査）")
            else:
                spec = next(iter(doc["steps"][step].values()))
                _set_path(spec, path, _typed(value))
                notes.append(f"steps[{step}].{path} → {value}（見た目の審査: {f['detail']['problem']}）")
        else:
            notes.append(f"{c}: 自動修正の規則なし（{f.get('hint')}）")
    if tr_doc is not None:
        yamlio.dump(tr_doc, tr_path)
    yamlio.dump(doc, scene_path)
    return notes


def _typed(v: str):
    low = v.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        return v


def _set_path(d, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value


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


def loop(scene_path: Path, out: Path, fixer: str = "rules", max_iter: int = 5, langs: list[str] | None = None,
         vision: bool = False, backend: str | None = None) -> dict:
    from .__main__ import _record
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    history = []
    reuse: Path | None = None
    tr_files = [translation_path(scene_mod.load(scene_path), lg) for lg in (langs or []) if lg]
    snapshot = lambda: {str(f): f.read_text(encoding="utf-8") for f in [scene_path, *tr_files] if f.exists()}
    for n in range(1, max_iter + 1):
        it = out / f"iter{n}"
        before = snapshot()
        sc = scene_mod.load(scene_path)
        if reuse is not None:
            # 直したのが文言（翻訳ファイル）だけなら撮り直さず、前回の録画で後工程からやり直す
            print(f"== iter {n}: 前回の録画を使って後工程から", flush=True)
            shutil.copytree(reuse, it, ignore=shutil.ignore_patterns("build*", "review*.json"))
        else:
            print(f"== iter {n}: record", flush=True)
            _record(scene_path, it, sc)
        rvs = {}
        for lang in langs or [None]:
            build(it, lang=lang)
            rvs[lang] = review(it, lang, vision=vision, backend=backend)
            rv = rvs[lang]
            print(f"   review[{rv.get('lang')}]: {'PASS' if rv['pass'] else 'FAIL ' + ', '.join(f['check'] for f in rv['failures'])}",
                  flush=True)
        all_pass = all(r["pass"] for r in rvs.values())
        entry = {"iter": n, "pass": all_pass,
                 "failures": [{"lang": r.get("lang"), "check": f["check"], "detail": f["detail"]}
                              for r in rvs.values() for f in r["failures"]]}
        if all_pass:
            history.append(entry)
            break
        notes, held = [], {}
        for lang, rv in rvs.items():
            if not rv["pass"]:
                notes += (rules_fix(scene_path, it, rv, lang, held) if fixer == "rules" else claude_fix(scene_path, it, rv))
        after = snapshot()
        diff = "".join("".join(difflib.unified_diff(before.get(k, "").splitlines(True), after.get(k, "").splitlines(True),
                                                    f"before/{Path(k).name}", f"after/{Path(k).name}")) for k in after)
        (it / "fix.diff").write_text(diff, encoding="utf-8")
        entry["fix"] = notes
        for x in notes:
            print(f"   fix: {x}", flush=True)
        history.append(entry)
        if before == after:
            print("   YAML が変わらなかったため停止", flush=True)
            break
        scene_key = str(scene_path)
        reuse = it if before.get(scene_key) == after.get(scene_key) else None
    result = {"scene": str(scene_path), "fixer": fixer, "iterations": len(history), "pass": history[-1]["pass"], "history": history}
    (out / "loop.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--fixer", choices=["rules", "claude"], default="rules")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--lang")
    ap.add_argument("--vision", action="store_true")
    a = ap.parse_args()
    sc = scene_mod.load(a.scene)
    r = loop(a.scene, a.out or Path("out") / sc["id"] / "loop", a.fixer, a.max,
             a.lang.split(",") if a.lang else None, a.vision)
    print(json.dumps({k: r[k] for k in ("iterations", "pass")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
