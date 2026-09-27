"""コメントと書式を保ったまま YAML を読み書きする（ループの自動修正と翻訳ファイルで共通の書式にする）。"""
from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML


def rt() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 200
    y.allow_unicode = True
    y.indent(mapping=2, sequence=4, offset=2)  # 既存 YAML の書式（"  - key:"）を崩さない
    return y


def load(path: Path):
    return rt().load(Path(path).read_text(encoding="utf-8"))


def dump(doc, path: Path, header: str = "") -> None:
    with Path(path).open("w", encoding="utf-8", newline="\n") as fh:  # Windows でも LF で書く
        if header:
            fh.write(header)
        rt().dump(doc, fh)
