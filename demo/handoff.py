"""Claude Code への受け渡し（見た目の審査・翻訳）。

ツールは Claude を API や CLI で呼ばない。判断が要る作業は、依頼を書き出して止まり、
作業中の Claude Code（スキル demo-video の手順）が画像を見て回答を書く。

  依頼フォルダ: <out>/_handoff/<名前>-<依頼内容のハッシュ>/
    request.md    何をどう判断するか（観点・回答の書き方）
    schema.json   回答の JSON Schema
    image_NN.jpg  見るコマ（審査のとき）
    sheet.jpg     コマの一覧（全体を一目で見るため。番号入り）
    response.json ← Claude Code が書く

回答が置かれたら、同じコマンドをもう一度実行すると取り込まれる。
依頼の中身（指示文・画像）が変われば別のフォルダになるので、古い回答を取り違えることはない。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

EXIT_NEEDS_RESPONSE = 3


class NeedsResponse(RuntimeError):
    """回答（response.json）がまだ無い依頼がある。複数の依頼をまとめて持てる。"""

    def __init__(self, folders: list[Path]):
        self.folders = list(folders)
        lines = "\n".join(f"  - {f}" for f in self.folders)
        super().__init__(
            "Claude Code の判断が必要です。次の依頼フォルダの request.md を読み、画像を確認して、"
            "schema.json に合う response.json を書いてから、同じコマンドをもう一度実行してください"
            "（loop は --resume を付ける）:\n" + lines)

    def __add__(self, other: "NeedsResponse") -> "NeedsResponse":
        return NeedsResponse(self.folders + other.folders)


def ask(name: str, instructions: str, prompt: str, schema: dict, images: list[Path] | None = None,
        workdir: Path = Path("out"), labels: list[str] | None = None) -> dict:
    """回答があれば検証して返す。無ければ依頼を書き出して NeedsResponse を送出する。"""
    images = [Path(p) for p in (images or [])]
    folder = _folder(name, instructions, prompt, schema, images, workdir)
    resp = folder / "response.json"
    if resp.exists():
        data = json.loads(resp.read_text(encoding="utf-8"))
        _check(data, schema, resp)
        return data
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for i, p in enumerate(images):
        dst = folder / f"image_{i:02d}{p.suffix}"
        shutil.copyfile(p, dst)
        names.append(dst.name)
    if images:
        _sheet(images, folder / "sheet.jpg", labels)
    body = [f"# 依頼: {name}\n", instructions.strip() + "\n", prompt.strip() + "\n"]
    if names:
        body.append("## 画像\n\n- 全体: sheet.jpg（番号はコマ番号）\n" + "\n".join(f"- コマ {i}: {n}" for i, n in enumerate(names)) + "\n")
    body.append("## 回答\n\nschema.json に合う JSON を、このフォルダの response.json に UTF-8 で保存する。\n")
    (folder / "request.md").write_text("\n".join(body), encoding="utf-8", newline="\n")
    (folder / "schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    raise NeedsResponse([folder])


def pending(root: Path = Path("out")) -> list[Path]:
    """回答待ちの依頼フォルダ（新しい順）。"""
    found = [p.parent for p in Path(root).glob("**/_handoff/*/request.md") if not (p.parent / "response.json").exists()]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def _folder(name, instructions, prompt, schema, images, workdir) -> Path:
    h = hashlib.sha1()
    for part in (instructions, prompt, json.dumps(schema, sort_keys=True)):
        h.update(part.encode("utf-8"))
    for p in images:
        h.update(p.read_bytes())
    return Path(workdir) / "_handoff" / f"{name}-{h.hexdigest()[:10]}"


def _sheet(images: list[Path], dst: Path, labels: list[str] | None, cols: int = 3, w: int = 640) -> None:
    ims = [Image.open(p).convert("RGB") for p in images]
    h = int(w * ims[0].height / ims[0].width)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 26)), "white")
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        x, y = (i % cols) * w, (i // cols) * (h + 26)
        sheet.paste(im.resize((w, h)), (x, y + 26))
        d.text((x + 6, y + 6), f"#{i}  " + (labels[i] if labels and i < len(labels) else ""), fill="black")
    sheet.save(dst, quality=85)


def _check(data, schema, where) -> None:
    from jsonschema import Draft202012Validator
    errs = list(Draft202012Validator(schema).iter_errors(data))
    if errs:
        raise ValueError(f"{where} がスキーマに合いません: {errs[0].json_path}: {errs[0].message}")
