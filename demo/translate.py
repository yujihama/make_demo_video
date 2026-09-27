"""多言語版の翻訳ファイルを作る（Claude で翻訳）。

  bin/demo translate scenes/<id>.yaml --lang en [--force]

`scenes/<id>.<lang>.yaml` を作る。既にあれば、元の文言が変わったステップだけ訳し直し、
人が直した訳（元の文言が変わっていないもの）はそのまま残す。--force で全部訳し直す。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import scene as scene_mod
from . import yamlio
from .claude_io import ask_json
from .i18n import _set, scene_lang, scene_texts, src_hash, translation_path

LANG_NAMES = {"ja": "日本語", "en": "英語", "zh": "中国語（簡体字）", "ko": "韓国語", "fr": "フランス語", "de": "ドイツ語", "es": "スペイン語"}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "text"],
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}}}}},
}

SYSTEM = "あなたは製品デモ動画の字幕翻訳者です。短く、自然で、画面を見ながら読み切れる字幕にします。"


def translate(scene_path: str | Path, lang: str, force: bool = False, backend: str | None = None) -> Path:
    scene = scene_mod.load(scene_path)
    base = scene_lang(scene)
    if lang == base:
        raise ValueError(f"{lang} はこのシーンの元の言語です")
    out = translation_path(scene, lang)
    old = yaml.safe_load(out.read_text(encoding="utf-8")) if out.exists() and not force else {}
    old_steps = (old or {}).get("steps") or []
    texts = scene_texts(scene)

    # 訳す対象: 見出し（題名・イントロ・まとめ）と、元の文言が変わったステップ
    items, keep = [], {}
    for key, text in texts["head"].items():
        prev = _head_value(old, key)
        if prev and (old.get("_head_src") or {}).get(key) == src_hash({(key,): text}):
            keep[key] = prev
        else:
            items.append({"id": f"head:{key}", "text": text})
    for i, (kind, tx) in enumerate(texts["steps"]):
        if not tx:
            continue
        prev = old_steps[i] if i < len(old_steps) else None
        if prev and prev.get("_src") == src_hash(tx) and prev.get("kind") == kind:
            continue
        for path, text in tx.items():
            items.append({"id": f"step:{i}:{'/'.join(path)}", "text": text})

    got = {}
    if items:
        got = {it["id"]: it["text"] for it in ask_json(
            f"translate-{scene['id']}-{lang}", SYSTEM, _prompt(scene, base, lang, items), SCHEMA,
            workdir=Path("out"), backend=backend)["items"]}
        missing = [it["id"] for it in items if it["id"] not in got]
        if missing:
            raise RuntimeError(f"訳が返ってこなかった項目があります: {missing}")

    doc = {"lang": lang, "source_lang": base, "_head_src": {}}
    for key, text in texts["head"].items():
        value = keep.get(key) or got[f"head:{key}"]
        doc["_head_src"][key] = src_hash({(key,): text})
        if key == "title":
            doc["title"] = value
        else:
            _, card, field = key.split(".")
            doc.setdefault("style", {}).setdefault(card, {})[field] = value
    steps = []
    for i, (kind, tx) in enumerate(texts["steps"]):
        if not tx:
            steps.append(None)
            continue
        prev = old_steps[i] if i < len(old_steps) else None
        if prev and prev.get("_src") == src_hash(tx) and prev.get("kind") == kind:
            steps.append(prev)
            continue
        entry = {"kind": kind, "_src": src_hash(tx)}
        for path in tx:
            _set(entry, path, got[f"step:{i}:{'/'.join(path)}"])
        steps.append(entry)
    doc["steps"] = steps
    header = (f"# {Path(scene['_path']).name} の {LANG_NAMES.get(lang, lang)} 訳（bin/demo translate で作成）。\n"
              "# 訳は人が直してよい。_src は元の文言のハッシュなので消さない。\n")
    yamlio.dump(doc, out, header)
    return out


def _head_value(old: dict, key: str):
    if not old:
        return None
    if key == "title":
        return old.get("title")
    _, card, field = key.split(".")
    return ((old.get("style") or {}).get(card) or {}).get(field)


def _prompt(scene: dict, base: str, lang: str, items: list[dict]) -> str:
    src, dst = LANG_NAMES.get(base, base), LANG_NAMES.get(lang, lang)
    lines = "\n".join(f"- id: {it['id']}\n  text: {it['text']}" for it in items)
    return f"""業務アプリのデモ動画「{scene['title']}」の字幕・カードの文言を{src}から{dst}に訳してください。

## 決まり
- 字幕は短く。{dst}で読み切れる長さにする（元の意味を落とさない範囲で言い換えてよい）
- **語** の強調記法は残し、訳文でも同じ意味の語を囲む
- 数値・単位・金額・ファイル名・製品名は変えない（例: 8件 → 8 transactions / 1,850,000円 → JPY 1,850,000）
- アプリの画面は{src}のまま映る。ボタン名などは画面の文字をそのまま引用せず、意味で訳す
- 章の題名（id が title で終わるもの）は名詞句で短く
- id は変えずに、すべての項目を返す

## 訳す文言
{lines}
"""
