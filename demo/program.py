"""通し版: 撮影済みの複数シーンを1本の動画にまとめ、ファイルで配る一式を作る。

録画はしない。各シーンは先に `bin/demo loop`（または make）で撮って合格させておく。
後工程だけを通し版用にやり直す（イントロ・まとめ・章カードを差し替え、全体の中での位置をガイドに出す）。

demos/<id>.yaml（スキーマは demo/program.schema.json）:

  id: audit_agent
  title: 監査エージェント デモ
  subtitle: 取り込みから指摘の確認まで       # 任意。省略時はシーン名を → でつなぐ
  lang: ja
  scenes:
    - scenes/core_audit.yaml                  # 録画は out/<scene id>/loop の合格回を自動で探す
    - {scene: scenes/policy_qa.yaml, run: out/policy_qa/loop/iter2}   # 録画を明示してもよい
  style: {guide: {position: top-right}}       # 任意。各シーンの style.guide を上書き
  translations:                               # 任意。--lang en のときの題名
    en: {title: Audit Agent Demo, subtitle: ...}

出力（out/<id>/program/<id>_<lang>/）:
  <id>_<lang>.mp4  章メタデータ付き（「1. シーン名 | 章名」）。VLC などで章へ飛べる
  player.html      章で区切ったシークバー・目次・サムネイル付きのプレイヤー（mp4 と同じフォルダで開く）
  chapters.json    シーン → 章の2階層の目次（秒）
  subtitles.srt    字幕（映像には焼き込み済み。翻訳・再利用向け）
  program.json     作成結果（各パートの長さ、読み切れない字幕の数など）
  parts/NN/        シーンごとの中間ファイル
と、配布用の out/<id>/program/<id>_<lang>.zip（mp4 と player.html）。
"""
from __future__ import annotations

import base64
import html
import json
import re
import subprocess
import zipfile
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .build import build_rich, prepare, rich_plan, srt_time
from .compose import FPS, part_duration
from .ff import FFMPEG
from .i18n import ui
from .style import scene_style

SCHEMA_PATH = Path(__file__).with_name("program.schema.json")
PLAYER_PATH = Path(__file__).with_name("assets") / "player.html"
FIRST_INTRO_S, SCENE_INTRO_S, FINAL_OUTRO_S = 3.4, 2.6, 4.0


class ProgramError(ValueError):
    pass


def load(path: str | Path) -> dict:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        msg = "\n".join(f"  {'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors)
        raise ProgramError(f"{path}: 通し版の定義が不正です\n{msg}")
    data["scenes"] = [s if isinstance(s, dict) else {"scene": s} for s in data["scenes"]]
    data["_path"] = str(path)
    return data


def find_run(scene_path: str, explicit: str | None = None) -> Path:
    """シーンの録画を探す: 明示 → loop の合格回 → out/<id>/run → loop の最新回。"""
    if explicit:
        run = Path(explicit)
        if not (run / "events.json").exists():
            raise ProgramError(f"{run} に録画（events.json）がありません")
        return run
    sid = yaml.safe_load(Path(scene_path).read_text(encoding="utf-8"))["id"]
    loop = Path("out") / sid / "loop"
    lj = loop / "loop.json"
    if lj.exists():
        r = json.loads(lj.read_text(encoding="utf-8"))
        if r.get("pass") and r.get("history"):
            it = loop / f"iter{r['history'][-1]['iter']}"
            if (it / "events.json").exists():
                return it
    if (Path("out") / sid / "run" / "events.json").exists():
        return Path("out") / sid / "run"
    iters = sorted((p for p in loop.glob("iter*") if (p / "events.json").exists()),
                   key=lambda p: int(re.sub(r"\D", "", p.name) or 0))
    if iters:
        print(f"警告: {sid} は合格した回が見つからないため、最新の {iters[-1]} を使います")
        return iters[-1]
    raise ProgramError(f"{scene_path} の録画がありません。先に `bin/demo loop {scene_path}` で撮ってください")


def _shift_srt(text: str, offset: float, start_no: int) -> tuple[list[str], int]:
    """SRT の各字幕を offset 秒ずらし、番号を start_no から振り直す。"""
    def t2s(x: str) -> float:
        h, m, rest = x.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    out, n = [], start_no
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        a, b = [t2s(x.strip()) for x in lines[1].split("-->")]
        out.append(f"{n}\n{srt_time(a + offset)} --> {srt_time(b + offset)}\n" + "\n".join(lines[2:]) + "\n")
        n += 1
    return out, n


def _thumb(video: Path, t: float) -> str:
    """動画の t 秒のコマを 320x180 の JPEG にして data URI で返す（player.html に埋め込む）。"""
    p = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=320:180", "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                       capture_output=True, check=True)
    return "data:image/jpeg;base64," + base64.b64encode(p.stdout).decode("ascii")


def render(program_path: str | Path, lang: str | None = None, make_zip: bool = True) -> dict:
    prog = load(program_path)
    base = prog.get("lang", "ja")
    lang = lang or base
    tr = (prog.get("translations") or {}).get(lang, {}) if lang != base else {}
    title = tr.get("title") or prog["title"]
    name = f"{prog['id']}_{lang}"
    root = Path("out") / prog["id"] / "program"
    out = root / name
    (out / "parts").mkdir(parents=True, exist_ok=True)

    pres = []
    for item in prog["scenes"]:
        run = find_run(item["scene"], item.get("run"))
        pre = prepare(run, lang)
        if pre["scene"] is None:
            raise ProgramError(f"{run}: シーン定義（{pre['m']['scene_path']}）が見つかりません")
        if Path(pre["m"]["scene_path"]).resolve() != Path(item["scene"]).resolve():
            print(f"警告: {run} は {pre['m']['scene_path']} の録画です（通し版の指定は {item['scene']}）")
        if scene_style(pre["scene"])["effects"] != "rich":
            raise ProgramError(f"{item['scene']}: 通し版は style.effects: rich のシーンだけをつなげます")
        pres.append(pre)

    N = len(pres)
    scene_titles = [p["scene"]["title"] for p in pres]
    uio = pres[0]["scene"].get("_ui", {})
    subtitle = tr.get("subtitle") or prog.get("subtitle") or ui(lang, "arrow", uio).join(scene_titles)

    def overrides(i: int) -> dict:
        st = scene_style(pres[i]["scene"])
        own = st["intro"] if isinstance(st["intro"], dict) else {}
        if i == 0:  # 最初のカードは通し版の題名と、シーンの並び
            intro = {**own, "title": title, "subtitle": subtitle, "eyebrow": "", "duration": FIRST_INTRO_S}
        else:
            intro = {**own, "eyebrow": ui(lang, "scene_of", uio, n=i + 1, total=N), "duration": SCENE_INTRO_S}
        outro = ({"title": ui(lang, "summary", uio), "text": title, "items": scene_titles, "duration": FINAL_OUTRO_S}
                 if i == N - 1 else False)
        prefix = f"{ui(lang, 'scene', uio)} {i + 1} · " if N > 1 else ""
        return {"intro": intro, "outro": outro, "step_prefix": prefix}

    # 1回目: 各パートの長さと章の位置を求める（映像は作らない）
    plans = [rich_plan(p, overrides(i)) for i, p in enumerate(pres)]
    durs = [round(part_duration(pl) * FPS) / FPS for pl in plans]   # 実際に書き出すコマ数に合わせる
    offsets = [round(sum(durs[:i]), 3) for i in range(N)]
    total = round(sum(durs), 3)
    ticks = []
    for i, pl in enumerate(plans):
        if i > 0:
            ticks.append((offsets[i], "scene"))
        ticks += [(offsets[i] + c["a"], "chapter") for c in pl.chapters[1:]]
    guide = (prog.get("style") or {}).get("guide")

    # 2回目: ガイドに全体の中での位置を渡してパートごとに描く
    parts, results = [], []
    for i, pre in enumerate(pres):
        program = {"offset": offsets[i], "total": total, "ticks": ticks, "scene_no": i + 1, "scene_total": N,
                   "guide": guide if isinstance(guide, dict) else ({"breadcrumb": False, "progress_bar": False}
                                                                  if guide is False else None)}
        part_dir = out / "parts" / f"{i + 1:02d}"
        part_dir.mkdir(parents=True, exist_ok=True)
        print(f"== パート {i + 1}/{N}: {scene_titles[i]}（{pre['run_dir']}）", flush=True)
        results.append(build_rich(pre, part_dir, overrides(i), program))
        parts.append(part_dir / "final.mp4")

    # 目次（シーン → 章）。各シーンの最初の章はシーンの先頭（イントロ込み）から
    toc, flat = [], []
    for i, (pl, r) in enumerate(zip(plans, results)):
        s0, s1 = offsets[i], round(offsets[i] + durs[i], 3)
        chs = []
        for j, c in enumerate(pl.chapters):
            a = s0 if j == 0 else round(s0 + c["a"], 3)
            b = round(s0 + pl.chapters[j + 1]["a"], 3) if j + 1 < len(pl.chapters) else s1
            peek = min(s0 + c["b"] + 0.4, b - 0.2)  # 章カードが消えた直後の画面をサムネイルに
            chs.append({"title": c["title"], "start": a, "end": b, "peek": round(peek, 3)})
        toc.append({"no": i + 1, "title": scene_titles[i], "start": s0, "end": s1, "chapters": chs})
        flat += [{"title": f"{i + 1}. {scene_titles[i]} | {c['title']}", "start": c["start"], "end": c["end"]}
                 for c in chs]

    # つなぐ: 各パートは同じ設定（H.264 / 30fps / 同じ解像度）で書き出しているので再エンコードしない
    mp4 = out / f"{name}.mp4"
    (out / "parts" / "list.txt").write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    meta = [";FFMETADATA1", f"title={title}"]
    for c in flat:
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['start'] * 1000)}", f"END={int(c['end'] * 1000)}",
                 f"title={c['title']}"]
    (out / "parts" / "program.ffmeta").write_text("\n".join(meta) + "\n", encoding="utf-8")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(out / "parts" / "list.txt"), "-i", str(out / "parts" / "program.ffmeta"),
                    "-map", "0:v", "-map_metadata", "1", "-map_chapters", "1", "-c", "copy",
                    "-movflags", "+faststart", str(mp4)], check=True)

    srt, n = [], 1
    for i in range(N):
        lines, n = _shift_srt((out / "parts" / f"{i + 1:02d}" / "subtitles.srt").read_text(encoding="utf-8"), offsets[i], n)
        srt += lines
    (out / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")

    for sc in toc:
        for c in sc["chapters"]:
            c["thumb"] = _thumb(mp4, c.pop("peek"))
    (out / "chapters.json").write_text(json.dumps([{**sc, "chapters": [{k: v for k, v in c.items() if k != "thumb"}
                                                                        for c in sc["chapters"]]} for sc in toc],
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    write_player(out / "player.html", mp4.name, title, subtitle, lang, uio, toc, total,
                 "#{:02X}{:02X}{:02X}".format(*plans[0].accent))

    unread = 0
    for i, r in enumerate(results):
        for x in r.get("readability") or []:
            if not x["ok"]:
                unread += 1
                print(f"警告: {prog['scenes'][i]['scene']}（{lang}）steps[{x['step']}] の字幕が {x['short_s']} 秒足りません。"
                      f"字幕を短くするか、そのシーンを `bin/demo loop --lang {lang}` で直してください")
    info = {"id": prog["id"], "lang": lang, "title": title, "duration": total, "scenes": len(toc),
            "chapters": len(flat), "readability_issues": unread, "final": str(mp4), "player": str(out / "player.html"),
            "parts": [{"scene": it["scene"], "run": str(p["run_dir"]), "offset": offsets[i], "duration": durs[i]}
                      for i, (it, p) in enumerate(zip(prog["scenes"], pres))]}
    if make_zip:
        z = root / f"{name}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:  # mp4 は圧縮済みなので格納だけ
            zf.write(mp4, f"{name}/{mp4.name}")
            zf.write(out / "player.html", f"{name}/player.html")
        info["zip"] = str(z)
    (out / "program.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


PLAYER_UI = {
    "ja": {"contents": "目次", "open_hint": "動画ファイル {file} をこの HTML と同じフォルダに置いて開いてください（zip は展開してから）",
           "keys": "Space 再生/停止 ・ ←→ 5秒 ・ [ ] 前/次の章 ・ F 全画面", "prev": "前の章", "next": "次の章",
           "play": "再生", "pause": "一時停止", "full": "全画面"},
    "en": {"contents": "Contents", "open_hint": "Put the video file {file} in the same folder as this HTML (extract the zip first)",
           "keys": "Space play/pause · ←→ 5s · [ ] prev/next chapter · F fullscreen", "prev": "Previous chapter",
           "next": "Next chapter", "play": "Play", "pause": "Pause", "full": "Fullscreen"},
    "zh": {"contents": "目录", "open_hint": "请将视频文件 {file} 与本 HTML 放在同一文件夹中打开（请先解压 zip）",
           "keys": "空格 播放/暂停 · ←→ 5秒 · [ ] 上/下一章 · F 全屏", "prev": "上一章", "next": "下一章",
           "play": "播放", "pause": "暂停", "full": "全屏"},
    "ko": {"contents": "목차", "open_hint": "동영상 파일 {file}을 이 HTML과 같은 폴더에 두고 여세요 (zip은 먼저 압축 해제)",
           "keys": "Space 재생/정지 · ←→ 5초 · [ ] 이전/다음 장 · F 전체 화면", "prev": "이전 장", "next": "다음 장",
           "play": "재생", "pause": "일시 정지", "full": "전체 화면"},
}


def write_player(path: Path, video_name: str, title: str, subtitle: str, lang: str, uio: dict, toc: list,
                 total: float, accent: str) -> None:
    strings = {**PLAYER_UI.get(lang, PLAYER_UI["en"]), "scene": ui(lang, "scene", uio)}
    strings["open_hint"] = strings["open_hint"].format(file=video_name)
    data = {"video": video_name, "total": total, "toc": toc, "ui": strings}
    page = PLAYER_PATH.read_text(encoding="utf-8")
    page = (page.replace("__LANG__", html.escape(lang)).replace("__TITLE__", html.escape(title))
                .replace("__SUBTITLE__", html.escape(subtitle)).replace("__ACCENT__", accent)
                .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
    path.write_text(page, encoding="utf-8")
