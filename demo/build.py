"""後工程（P4）: 録画 + 操作ログ → 完成動画一式。

  1. 同期マーカーで操作ログを動画時刻に合わせ、マーカーより前を切り落とす
  2. 待ち時間（wait_for の処理待ち）を早送りする。操作の前後は等速のまま残す
  3. 字幕（SRT）と chapters.json を操作ログから作り、時刻を早送り後の時間軸に写す
  4. 字幕を焼き込み、章メタデータ付きの MP4（H.264 / 30fps）を書き出す

出力: final.mp4, subtitles.srt, chapters.json, build.json
"""
from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

from .ff import FFMPEG
from .record import SYNC_MS
from .sync import offset as sync_offset

IDLE_SPEED = 4.0
KEEP_BEFORE, KEEP_AFTER = 0.8, 0.6  # 早送り区間の前後に等速で残す秒数
MIN_IDLE = 1.5
FONT = "BIZ UDGothic" if platform.system() == "Windows" else "Noto Sans CJK JP"


def segments(events: list[dict], start: float, end: float, speed: float) -> list[tuple[float, float, float]]:
    """[(s, e, speed)] を start..end を隙間なく覆うように作る。"""
    idle = []
    for e in events:
        if e["kind"] == "wait_for":
            s, t = e["v_start"] + KEEP_BEFORE, e["v_act"] - KEEP_AFTER
            if t - s >= MIN_IDLE:
                idle.append((s, t))
    segs, cur = [], start
    for s, t in sorted(idle):
        if s > cur:
            segs.append((cur, s, 1.0))
        segs.append((s, t, speed))
        cur = t
    if end > cur:
        segs.append((cur, end, 1.0))
    return [(round(a, 3), round(b, 3), sp) for a, b, sp in segs]


class TimeMap:
    def __init__(self, segs):
        self.segs = segs

    def __call__(self, t: float) -> float:
        out = 0.0
        for s, e, sp in self.segs:
            if t <= s:
                break
            out += (min(t, e) - s) / sp
        return round(out, 3)

    @property
    def duration(self) -> float:
        return round(sum((e - s) / sp for s, e, sp in self.segs), 3)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def build(run_dir: str | Path, out: str | Path | None = None, speed: float = IDLE_SPEED, burn: bool = True) -> dict:
    run_dir = Path(run_dir)
    out = Path(out or run_dir / "build")
    out.mkdir(parents=True, exist_ok=True)
    m = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    video = Path(m["video"])
    if not video.is_absolute() and not video.exists():
        video = run_dir / video.name
    off = m.get("offset")
    if off is None:
        off = sync_offset(video, m["sync_host"])
    for e in m["events"]:
        for k in ("start", "act", "end"):
            if k in e:
                e[f"v_{k}"] = round(e[k] + off, 3)
    start = round(m["sync_host"] + off + SYNC_MS / 1000 + 0.2, 3)   # マーカーの直後から
    end = round(m["events"][-1]["v_end"] + 0.3, 3)
    segs = segments(m["events"], start, end, speed)
    tm = TimeMap(segs)

    # 字幕: キャプション付きステップの開始〜終了（次のキャプションまでに収める）
    caps = [e for e in m["events"] if e.get("caption")]
    lines = []
    for n, e in enumerate(caps, 1):
        a, b = tm(e["v_start"]), tm(e["v_end"])
        if b - a < 1.2:
            b = a + 1.2
        # 操作対象が画面の下寄りなら字幕を上に出して、対象を隠さない
        top = "box" in e and (e["box"][1] + e["box"][3]) > m["viewport"]["height"] * 0.62
        pos = "{\\an8}" if top else ""
        lines.append(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{pos}{e['caption']}\n")
    (out / "subtitles.srt").write_text("\n".join(lines), encoding="utf-8")

    # 章: chapter ステップから次の chapter ステップまで
    chs = [e for e in m["events"] if e["kind"] == "chapter"]
    chapters = []
    for j, e in enumerate(chs):
        st = tm(max(e["v_start"], start))
        en = tm(chs[j + 1]["v_start"]) if j + 1 < len(chs) else tm.duration
        chapters.append({"title": e["title"], "start": st, "end": en})
    (out / "chapters.json").write_text(json.dumps(chapters, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = [";FFMETADATA1"]
    for c in chapters:
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['start'] * 1000)}", f"END={int(c['end'] * 1000)}", f"title={c['title']}"]
    (out / "chapters.ffmeta").write_text("\n".join(meta) + "\n", encoding="utf-8")

    # 映像: 区間ごとに trim → setpts で速度変更 → concat → 30fps → 字幕焼き込み
    parts, labels = [], []
    for k, (s, e, sp) in enumerate(segs):
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=(PTS-STARTPTS)/{sp}[s{k}]")
        labels.append(f"[s{k}]")
    chain = ";".join(parts) + f";{''.join(labels)}concat=n={len(segs)}:v=1:a=0,fps=30,format=yuv420p"
    if burn and lines:
        # libass は SRT を基準 288 ライン換算で描く: FontSize 11 ≒ 1080p で 41px
        style = f"FontName={FONT},FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H60000000,BorderStyle=3,Outline=3,Shadow=0,MarginV=14"
        chain += f",subtitles=subtitles.srt:force_style='{style}'"
    chain += "[v]"
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video.resolve()), "-i", "chapters.ffmeta",
           "-filter_complex", chain, "-map", "[v]", "-map_metadata", "1", "-map_chapters", "1",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-movflags", "+faststart", "final.mp4"]
    subprocess.run(cmd, cwd=out, check=True)

    info = {"source": str(video), "offset": off, "trim_start": start, "segments": segs,
            "idle_speed": speed, "raw_span": round(end - start, 3), "duration": tm.duration,
            "captions": len(lines), "chapters": chapters, "final": str(out / "final.mp4")}
    (out / "build.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info

