"""Claude への問い合わせ（翻訳・見た目の審査）。JSON Schema どおりの JSON を返させる。

使う手段は環境変数 DEMO_CLAUDE_BACKEND で選ぶ（既定 auto）:
  api   Anthropic SDK。認証は SDK の既定の順（ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login` のプロファイル）
  cli   Claude Code（`claude -p`）。ログイン済みであること
  file  依頼を <out>/_claude/<名前>/ に書き出し、同じ場所の response.json を読む。
        人や別のエージェントが回答を置いてから同じコマンドをもう一度実行する（オフライン・審査の差し替え用）
  auto  api → cli → file の順で使えるものを使う
モデルは DEMO_CLAUDE_MODEL（既定 claude-opus-5）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

MODEL = os.environ.get("DEMO_CLAUDE_MODEL", "claude-opus-5")


class NeedsResponse(RuntimeError):
    """file 方式で、回答（response.json）がまだ無い。"""

    def __init__(self, folder: Path):
        self.folder = folder
        super().__init__(
            f"Claude への依頼を {folder} に書き出しました。request.md と画像を読んで、"
            f"schema.json に合う JSON を {folder / 'response.json'} に保存し、同じコマンドをもう一度実行してください")


def ask_json(name: str, system: str, prompt: str, schema: dict, images: list[Path] | None = None,
             workdir: Path = Path("out"), backend: str | None = None) -> dict:
    """prompt（と画像）を渡し、schema に合う dict を返す。"""
    images = images or []
    backend = backend or os.environ.get("DEMO_CLAUDE_BACKEND", "auto")
    folder = _request_folder(name, system, prompt, schema, images, workdir)
    if backend in ("file",) or (backend == "auto" and (folder / "response.json").exists()):
        return _via_file(folder, system, prompt, schema, images)
    errors = []
    for b in (["api", "cli"] if backend == "auto" else [backend]):
        try:
            return _via_api(system, prompt, schema, images) if b == "api" else _via_cli(system, prompt, schema, images)
        except _Unavailable as e:
            errors.append(f"{b}: {e}")
    if backend == "auto":
        return _via_file(folder, system, prompt, schema, images, note=errors)
    raise RuntimeError("Claude を呼び出せません: " + " / ".join(errors))


class _Unavailable(RuntimeError):
    pass


def _request_folder(name, system, prompt, schema, images, workdir) -> Path:
    h = hashlib.sha1()
    for part in (system, prompt, json.dumps(schema, sort_keys=True)):
        h.update(part.encode("utf-8"))
    for p in images:
        h.update(Path(p).read_bytes())
    return Path(workdir) / "_claude" / f"{name}-{h.hexdigest()[:10]}"


# --- api -----------------------------------------------------------------------------------
def _via_api(system, prompt, schema, images) -> dict:
    try:
        import anthropic
    except ImportError as e:
        raise _Unavailable("anthropic が入っていません（pip install anthropic）") from e
    content = []
    for p in images:
        media = "image/jpeg" if str(p).lower().endswith((".jpg", ".jpeg")) else "image/png"
        content.append({"type": "image", "source": {"type": "base64", "media_type": media,
                                                    "data": base64.standard_b64encode(Path(p).read_bytes()).decode()}})
    content.append({"type": "text", "text": prompt})
    try:
        client = anthropic.Anthropic()
        # 安全側の判定で断られた場合はサーバー側で既定の代替モデルに回す（fallbacks: "default"）
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError as e:
        raise _Unavailable("認証できません（ANTHROPIC_API_KEY か `ant auth login`）") from e
    except anthropic.APIConnectionError as e:
        raise _Unavailable(f"接続できません: {e}") from e
    except TypeError as e:  # 認証情報が見つからないとき SDK は構築時に TypeError を出す
        raise _Unavailable(str(e)) from e
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Claude が応答を断りました: {getattr(resp.stop_details, 'explanation', '')}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("応答が長すぎて途中で切れました")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


# --- cli -----------------------------------------------------------------------------------
def _via_cli(system, prompt, schema, images) -> dict:
    exe = shutil.which("claude")  # Windows では claude.cmd などの実体パスで呼ぶ
    if not exe:
        raise _Unavailable("claude コマンドがありません")
    try:
        st = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, encoding="utf-8")
    except OSError as e:
        raise _Unavailable(f"claude を起動できません: {e}") from e
    if '"loggedIn": true' not in st.stdout:
        raise _Unavailable("claude がログインしていません（claude /login）")
    files = "\n".join(f"- {Path(p).resolve().as_posix()}" for p in images)
    full = (f"{system}\n\n{prompt}\n\n" + (f"次の画像ファイルを Read ツールで開いて確認してください:\n{files}\n\n" if images else "")
            + "回答は次の JSON Schema に合う JSON だけを出力してください（前後に文章やコードブロックを付けない）:\n"
            + json.dumps(schema, ensure_ascii=False))
    r = subprocess.run([exe, "-p", full, "--allowedTools", "Read", "--output-format", "json", "--max-turns", "20"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"claude -p が失敗しました: {(r.stdout + r.stderr)[-400:]}")
    result = json.loads(r.stdout).get("result", "")
    return _extract_json(result)


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError(f"JSON が返りませんでした: {text[:200]}")
    return json.loads(m.group(0))


# --- file ----------------------------------------------------------------------------------
def _via_file(folder: Path, system, prompt, schema, images, note=None) -> dict:
    resp = folder / "response.json"
    if resp.exists():
        data = json.loads(resp.read_text(encoding="utf-8"))
        _check_schema(data, schema, resp)
        return data
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for i, p in enumerate(images):
        dst = folder / f"image_{i:02d}{Path(p).suffix}"
        shutil.copyfile(p, dst)
        names.append(dst.name)
    body = [f"# 依頼\n\n## system\n\n{system}\n\n## prompt\n\n{prompt}\n"]
    if names:
        body.append("## 画像\n\n" + "\n".join(f"- {n}" for n in names) + "\n")
    body.append("## 回答\n\nschema.json に合う JSON を response.json として保存する。\n")
    if note:
        body.append("## 自動で呼べなかった理由\n\n" + "\n".join(f"- {x}" for x in note) + "\n")
    (folder / "request.md").write_text("\n".join(body), encoding="utf-8")
    (folder / "schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=1), encoding="utf-8")
    raise NeedsResponse(folder)


def _check_schema(data, schema, where):
    from jsonschema import Draft202012Validator
    errs = list(Draft202012Validator(schema).iter_errors(data))
    if errs:
        raise ValueError(f"{where} がスキーマに合いません: {errs[0].message}")
