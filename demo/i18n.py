"""多言語版: 翻訳ファイルの読み込み、演出の定型文言、言語ごとの読む速さ。

翻訳は `scenes/<id>.<lang>.yaml` に置く（`bin/demo translate` で作れる。人が直してもよい）。
録画は言語によらず1回で、後工程（build）だけを言語ごとに行う。

  lang: en
  source_lang: ja
  title: ...                       # シーンの題名
  style: {intro: {...}, outro: {...}}
  ui: {summary: Summary}           # 定型文言の上書き（任意）
  steps:                           # シーンの steps と同じ順・同じ数。文言の無いステップは null
    - {kind: chapter, _src: 1a2b3c4d, title: ..., description: ...}
    - {kind: upload, _src: ..., caption: ...}

`_src` は翻訳元の文言のハッシュ。元の YAML を直したのに翻訳を更新していないと警告を出す。
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import yaml

DEFAULT_LANG = "ja"

UI = {
    "ja": {"step": "STEP {n} / {total}", "summary": "まとめ", "saved": "{name} を保存しました",
           "fast": "早送り ×{speed}", "typing": "入力", "arrow": " → "},
    "en": {"step": "STEP {n} / {total}", "summary": "Summary", "saved": "Saved {name}",
           "fast": "Fast-forward ×{speed}", "typing": "Typing", "arrow": " → "},
    "zh": {"step": "步骤 {n} / {total}", "summary": "总结", "saved": "已保存 {name}",
           "fast": "快进 ×{speed}", "typing": "输入", "arrow": " → "},
    "ko": {"step": "STEP {n} / {total}", "summary": "요약", "saved": "{name} 저장됨",
           "fast": "빨리 감기 ×{speed}", "typing": "입력", "arrow": " → "},
}

# 字幕を読み切るのに必要な速さ（1秒あたりの文字数）。字幕の表示時間 ≥ 文字数 / CPS + 反応時間
CPS = {"ja": 7.0, "zh": 7.0, "ko": 9.0, "en": 15.0}
REACTION_S = 0.4

# ステップごとに翻訳する文言の置き場所（スペック内のキーのパス）
STEP_TEXT_PATHS = {
    "chapter": [("title",), ("description",)],
    "compare": [("title",), ("before", "label"), ("before", "value"), ("before", "note"),
                ("after", "label"), ("after", "value"), ("after", "note")],
}
COMMON_TEXT_PATHS = [("caption",), ("effect", "callout"), ("effect", "toast"),
                     ("effect", "countup", "label"), ("effect", "countup", "suffix")]


def ui(lang: str, key: str, overrides: dict | None = None, **kw) -> str:
    s = (overrides or {}).get(key) or UI.get(lang, UI["en"]).get(key) or UI["en"][key]
    return s.format(**kw)


def cps(lang: str) -> float:
    return CPS.get(lang, 14.0)


def scene_lang(scene: dict) -> str:
    return scene.get("lang", DEFAULT_LANG)


# --- 文言の取り出しと差し替え ---------------------------------------------------------
def _get(d, path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d if isinstance(d, str) else None


def _set(d, path, value):
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def step_texts(kind: str, spec) -> dict[tuple, str]:
    if not isinstance(spec, dict):
        return {}
    out = {}
    for path in STEP_TEXT_PATHS.get(kind, []) + COMMON_TEXT_PATHS:
        v = _get(spec, path)
        if v and not (path == ("effect", "toast") and v in ("auto",)):
            out[path] = v
    return out


def scene_texts(scene: dict) -> dict:
    """翻訳の対象になる文言をすべて取り出す（translate が使う）。"""
    style = scene.get("style") or {}
    head = {"title": scene["title"]}
    for card in ("intro", "outro"):
        if isinstance(style.get(card), dict):
            for k in ("title", "subtitle", "text"):
                if style[card].get(k):
                    head[f"style.{card}.{k}"] = style[card][k]
    steps = []
    for step in scene["steps"]:
        kind, spec = next(iter(step.items()))
        steps.append((kind, step_texts(kind, spec)))
    return {"head": head, "steps": steps}


def src_hash(texts: dict) -> str:
    raw = json.dumps({"/".join(k): v for k, v in sorted(texts.items())}, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def translation_path(scene: dict, lang: str) -> Path:
    p = Path(scene["_path"])
    return p.with_name(f"{p.stem}.{lang}.yaml")


def localize(scene: dict, lang: str | None) -> dict:
    """シーンを指定言語に差し替えたコピーを返す。元の言語ならそのまま。"""
    base = scene_lang(scene)
    lang = lang or base
    sc = copy.deepcopy(scene)
    sc["_lang"] = lang
    sc["_ui"] = {}
    if lang == base:
        return sc
    path = translation_path(scene, lang)
    if not path.exists():
        raise FileNotFoundError(f"{path} がありません。先に `bin/demo translate {scene['_path']} --lang {lang}` で作ってください")
    tr = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    steps = tr.get("steps") or []
    if len(steps) != len(sc["steps"]):
        raise ValueError(f"{path}: ステップ数がシーンと合いません（{len(steps)} ≠ {len(sc['steps'])}）。translate で作り直してください")
    sc["title"] = tr.get("title") or sc["title"]
    for card in ("intro", "outro"):
        t = (tr.get("style") or {}).get(card)
        if isinstance(t, dict):
            st = sc.setdefault("style", {})
            cur = st.get(card)
            st[card] = {**(cur if isinstance(cur, dict) else {}), **t} if cur is not False else False
    sc["_ui"] = tr.get("ui") or {}
    stale = []
    for i, (step, t) in enumerate(zip(sc["steps"], steps)):
        kind, spec = next(iter(step.items()))
        if not t:
            continue
        if t.get("kind") and t["kind"] != kind:
            raise ValueError(f"{path}: steps[{i}] の種類がシーンと合いません（{t['kind']} ≠ {kind}）")
        if t.get("_src") and t["_src"] != src_hash(step_texts(kind, scene["steps"][i][kind])):
            stale.append(i)
        for key, value in t.items():
            if key in ("kind", "_src") or not isinstance(spec, dict):
                continue
            _merge_text(spec, key, value)
    if stale:
        print(f"警告: {path.name} の steps {stale} は元の文言が変わっています。translate で更新してください", file=sys.stderr)
    return sc


def _merge_text(spec: dict, key: str, value) -> None:
    if isinstance(value, dict):
        sub = spec.setdefault(key, {})
        if isinstance(sub, dict):
            for k, v in value.items():
                _merge_text(sub, k, v)
    elif isinstance(value, str):
        spec[key] = value
