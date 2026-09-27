"""自己確認ループ（P5）: 録画 → 後工程 → 合格判定 → 不合格ならシーン YAML を直して再録画、を合格まで繰り返す。

  bin/demo loop <scene.yaml> [--lang ja,en] [--vision] [--max 5] [--resume]

直すのはシーン YAML と翻訳ファイルだけ（アプリやランナーのコードには触らない）。
review.json の失敗項目から決まった規則で直す（rules_fix）。規則で直せないものは止まり、
Claude Code がスキル demo-video の手順に沿って YAML を直す。

--lang を複数指定すると、録画は1回のまま言語ごとに後工程と判定を行い、全言語が合格するまで回す。
--vision を付けると Claude Code の見た目の審査も判定に入れ、その直し方（fix）も反映する。
  審査の依頼を書き出した時点で止まる（終了コード 3）。Claude Code が回答を書いたら --resume で続きから回す。
字幕の文言の直し（caption / effect.callout）は、元の言語ならシーン YAML に、それ以外は翻訳ファイルに入れる。
各反復の review*.json と YAML の差分は <out>/iterN/ に、途中の状態は <out>/state.json に残す。
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import shutil
from pathlib import Path

from . import scene as scene_mod
from . import yamlio
from .build import build, build_dir
from .handoff import NeedsResponse
from .i18n import refresh_src, scene_lang, translation_path
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
    notes, tr_touched = [], []
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
                tr_touched.append(step)
                notes.append(f"{tr_path.name} steps[{step}].{path} → {value}（見た目の審査）")
            else:
                spec = next(iter(doc["steps"][step].values()))
                _set_path(spec, path, _typed(value))
                notes.append(f"steps[{step}].{path} → {value}（見た目の審査: {f['detail']['problem']}）")
        else:
            notes.append(f"{c}: 自動修正の規則なし（{f.get('hint')}）")
    if tr_doc is not None:
        # 審査で直した訳は、今の原文（同じ回に原文も直していればその新しい原文）に対応した訳として記録する
        refresh_src(tr_doc, scene_mod.load(scene_path), tr_touched)
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


def loop(scene_path: Path, out: Path, max_iter: int = 5, langs: list[str] | None = None,
         vision: bool = False, resume: bool = False) -> dict:
    from .__main__ import _record
    state_file = out / "state.json"
    tr_files = [translation_path(scene_mod.load(scene_path), lg) for lg in (langs or []) if lg]
    snapshot = lambda: {str(f): f.read_text(encoding="utf-8") for f in [scene_path, *tr_files] if f.exists()}
    state = json.loads(state_file.read_text(encoding="utf-8")) if resume and state_file.exists() else None
    if state is None:
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        state = {"n": 1, "history": [], "reuse": None, "before": None}
    else:
        print(f"== 途中から再開（iter {state['n']}）", flush=True)
    history = state["history"]
    n = state["n"]
    while n <= max_iter:
        it = out / f"iter{n}"
        before = state["before"] or snapshot()
        sc = scene_mod.load(scene_path)
        if (it / "events.json").exists():
            print(f"== iter {n}: 録画済み（後工程と判定から）", flush=True)
        elif state["reuse"]:
            # 直したのが文言（翻訳ファイル）だけなら撮り直さず、前回の録画で後工程からやり直す
            print(f"== iter {n}: 前回の録画を使って後工程から", flush=True)
            shutil.copytree(state["reuse"], it, ignore=shutil.ignore_patterns("build*", "review*.json"))
        else:
            print(f"== iter {n}: record", flush=True)
            _record(scene_path, it, sc)
        rvs, waiting = {}, None
        for lang in langs or [None]:
            build(it, lang=lang)
            try:
                rvs[lang] = review(it, lang, vision=vision)
            except NeedsResponse as e:  # 他の言語の依頼も書き出してからまとめて止まる
                waiting = e if waiting is None else waiting + e
                continue
            rv = rvs[lang]
            print(f"   review[{rv.get('lang')}]: {'PASS' if rv['pass'] else 'FAIL ' + ', '.join(f['check'] for f in rv['failures'])}",
                  flush=True)
        if waiting is not None:
            state.update({"n": n, "history": history, "before": before})
            state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
            raise waiting
        all_pass = all(r["pass"] for r in rvs.values())
        entry = {"iter": n, "pass": all_pass,
                 "failures": [{"lang": r.get("lang"), "check": f["check"], "detail": f["detail"]}
                              for r in rvs.values() for f in r["failures"]]}
        history.append(entry)
        # 合格でも、見た目の審査に medium の直し方があれば反映してもう一度確かめる（最後の回を除く）
        suggested = any(r.get("suggested") for r in rvs.values())
        if all_pass and (not suggested or n >= max_iter):
            break
        notes, held = [], {}
        base = scene_lang(scene_mod.load(scene_path))
        # 原文の言語を先に直す（訳の _src を新しい原文で記録するため）
        for lang, rv in sorted(rvs.items(), key=lambda kv: kv[0] not in (None, base)):
            if not rv["pass"] or rv.get("suggested"):
                notes += rules_fix(scene_path, it, rv, lang, held)
        after = snapshot()
        diff = "".join("".join(difflib.unified_diff(before.get(k, "").splitlines(True), after.get(k, "").splitlines(True),
                                                    f"before/{Path(k).name}", f"after/{Path(k).name}")) for k in after)
        (it / "fix.diff").write_text(diff, encoding="utf-8")
        entry["fix"] = notes
        for x in notes:
            print(f"   fix: {x}", flush=True)
        if before == after:
            print("   規則では直せないため停止。review*.json の hint を見て YAML を直してください", flush=True)
            break
        scene_key = str(scene_path)
        state["reuse"] = str(it) if before.get(scene_key) == after.get(scene_key) else None
        state["before"] = None
        n += 1
    result = {"scene": str(scene_path), "iterations": len(history), "pass": bool(history and history[-1]["pass"]),
              "history": history}
    (out / "loop.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    state_file.unlink(missing_ok=True)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--lang")
    ap.add_argument("--vision", action="store_true")
    a = ap.parse_args()
    sc = scene_mod.load(a.scene)
    r = loop(a.scene, a.out or Path("out") / sc["id"] / "loop", a.max, a.lang.split(",") if a.lang else None, a.vision)
    print(json.dumps({k: r[k] for k in ("iterations", "pass")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
