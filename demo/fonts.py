"""合成（字幕・カード・吹き出し）に使う日本語フォントの解決。

Linux は fontconfig（fc-match）で Noto Sans CJK JP を探し、Windows は既知のファイルを順に探す。
環境変数 DEMO_FONT / DEMO_FONT_BOLD でファイルを直接指定できる。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

WINDOWS = {
    False: ["BIZ-UDGothicR.ttc", "YuGothM.ttc", "NotoSansJP-VF.ttf", "meiryo.ttc", "msgothic.ttc"],
    True: ["BIZ-UDGothicB.ttc", "YuGothB.ttc", "NotoSansJP-VF.ttf", "meiryob.ttc", "msgothic.ttc"],
}
LINUX_PATTERN = {False: "Noto Sans CJK JP:style=Regular", True: "Noto Sans CJK JP:style=Bold"}


@lru_cache(maxsize=None)
def font_path(bold: bool = False) -> tuple[str, int]:
    """(フォントファイル, .ttc 内の番号)。"""
    env = os.environ.get("DEMO_FONT_BOLD" if bold else "DEMO_FONT")
    if env and Path(env).exists():
        return env, 0
    if os.name == "nt":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in WINDOWS[bold]:
            if (fonts / name).exists():
                return str(fonts / name), 0
    if shutil.which("fc-match"):
        out = subprocess.run(["fc-match", "-f", "%{file}|%{index}", LINUX_PATTERN[bold]], capture_output=True, text=True).stdout
        file, _, index = out.partition("|")
        if file and Path(file).exists() and "CJK" in file:
            return file, int(index or 0)
    for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",):
        if Path(p).exists():
            return p, 0
    raise RuntimeError("日本語フォントが見つかりません（Linux: apt install fonts-noto-cjk / DEMO_FONT で指定）")


@lru_cache(maxsize=None)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path, index = font_path(bold)
    return ImageFont.truetype(path, size, index=index)
