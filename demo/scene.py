"""シーン定義（YAML）の読み込みと検証。スキーマは demo/scene.schema.json。"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("scene.schema.json")
DEFAULTS = {
    "viewport": {"width": 1920, "height": 1080},
    "zoom": 1.0,
    "cursor": "ghost",
    "mode": "browser",
    "seed": 42,
    "pace": {"before_action": 400, "after_action": 700},
}


class SceneError(ValueError):
    pass


def load(path: str | Path) -> dict:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        msg = "\n".join(f"  {'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors)
        raise SceneError(f"{path}: シーン定義が不正です\n{msg}")
    scene = {**DEFAULTS, **data, "pace": {**DEFAULTS["pace"], **data.get("pace", {})}}
    scene["_path"] = str(path)
    scene["_base"] = str(path.parent.resolve())
    for step in scene["steps"]:
        kind, spec = next(iter(step.items()))
        if kind == "upload":
            f = Path(spec["file"])
            spec["file"] = str(f if f.is_absolute() else (path.parent / f).resolve())
            if not Path(spec["file"]).exists():
                raise SceneError(f"{path}: upload のファイルがありません: {spec['file']}")
    return scene


def steps(scene: dict):
    """(index, kind, spec) を順に返す。"""
    for i, step in enumerate(scene["steps"]):
        kind, spec = next(iter(step.items()))
        yield i, kind, (spec if isinstance(spec, dict) else {"ms": spec})
