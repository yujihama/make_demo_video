"""合成で重ねる演出の描画部品（PIL）。座標はすべて完成動画のピクセル。

  字幕（章ラベル・強調語つき）、クリックの波紋、スポットライト、吹き出し、パルス、
  トースト、早送りバッジ、章カード、イントロ／まとめカード
"""
from __future__ import annotations

import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .fonts import font

INK = (15, 23, 42)
WHITE = (255, 255, 255)
MUTED = (203, 213, 225)
OK_GREEN = (34, 197, 94)

# 強調: **語** を明示指定。指定が無い字幕は数値＋単位（8件、1,850,000円、100万円 など）を自動で強調する
EMPH_MARK = re.compile(r"\*\*(.+?)\*\*")
AUTO_EMPH = re.compile(r"\d[\d,，.]*(?:万|億)?(?:件|円|%|％|秒|分|時間|日|名|人|行|倍|割)?")
NO_LINE_START = set("、。，．・：；？！）」』】〕ー…")


def parse_emphasis(text: str) -> list[tuple[str, bool]]:
    """[(文字列, 強調か)] に分ける。"""
    if "**" in text:
        runs, pos = [], 0
        for m in EMPH_MARK.finditer(text):
            if m.start() > pos:
                runs.append((text[pos:m.start()], False))
            runs.append((m.group(1), True))
            pos = m.end()
        if pos < len(text):
            runs.append((text[pos:], False))
        return runs
    runs, pos = [], 0
    for m in AUTO_EMPH.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False))
        runs.append((m.group(0), True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False))
    return runs


def plain(text: str) -> str:
    return EMPH_MARK.sub(r"\1", text)


def _wrap(runs, fonts, max_w):
    """文字単位で折り返す（行頭禁則つき）。戻り値: 行ごとの [(文字, 強調か)]"""
    chars = [(c, e) for s, e in runs for c in s]
    lines, cur, w = [], [], 0.0
    for c, e in chars:
        cw = fonts[e].getlength(c)
        if cur and w + cw > max_w and c not in NO_LINE_START:
            lines.append(cur)
            cur, w = [], 0.0
        cur.append((c, e))
        w += cw
    if cur:
        lines.append(cur)
    return lines


def rounded(size, radius, fill) -> Image.Image:
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=fill)
    return im


@lru_cache(maxsize=64)
def caption_image(text: str, label: str | None, accent: tuple, max_w: int = 1560, size: int = 38) -> Image.Image:
    """下部（または上部）に出す字幕パネル。左に章ラベル、本文は強調語を強調色の太字で。"""
    fonts = {False: font(size), True: font(size, bold=True)}
    lab_font = font(24, bold=True)
    lab_w = int(lab_font.getlength(label)) + 28 if label else 0
    text_max = max_w - 56 - (lab_w + 18 if label else 0)
    lines = _wrap(parse_emphasis(text), fonts, text_max)
    lh = int(size * 1.45)
    text_w = max(sum(fonts[e].getlength(c) for c, e in ln) for ln in lines)
    W = int(text_w + 56 + (lab_w + 18 if label else 0))
    H = lh * len(lines) + 34
    im = rounded((W, H), 18, (*INK, 222))
    d = ImageDraw.Draw(im)
    x0 = 28
    if label:
        ch = 40
        cy = (H - ch) // 2
        d.rounded_rectangle((x0, cy, x0 + lab_w, cy + ch), 10, fill=(*accent, 255))
        d.text((x0 + 14, cy + ch / 2), label, font=lab_font, fill=INK, anchor="lm")
        x0 += lab_w + 18
    y = 17 + lh / 2
    for ln in lines:
        x = x0
        for c, e in ln:
            d.text((x, y), c, font=fonts[e], fill=(*accent, 255) if e else WHITE, anchor="lm")
            x += fonts[e].getlength(c)
        y += lh
    return im


def with_alpha(im: Image.Image, a: float) -> Image.Image:
    if a >= 0.999:
        return im
    out = im.copy()
    out.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return out


def paste(layer: Image.Image, im: Image.Image, xy, a: float = 1.0) -> None:
    if a <= 0.001:
        return
    layer.alpha_composite(with_alpha(im, a), (int(round(xy[0])), int(round(xy[1]))))


# --- 操作の強調 -----------------------------------------------------------------
def ripple(d: ImageDraw.ImageDraw, pt, p: float, accent) -> None:
    """クリック位置から広がる2重の波紋。p は 0→1 の進み具合。"""
    for lag in (0.0, 0.18):
        q = (p - lag) / (1 - lag)
        if not 0 <= q <= 1:
            continue
        r = 20 + 80 * (1 - (1 - q) ** 2)
        a = int(235 * (1 - q))
        d.ellipse((pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r), outline=(*accent, a), width=max(3, int(8 * (1 - q)) + 3))
    if p < 0.35:
        r = 22 * (1 - p)
        d.ellipse((pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r), fill=(*accent, int(140 * (1 - p / 0.35))))


def spotlight(frame: Image.Image, rect, a: float, accent, dim: float = 0.5) -> Image.Image:
    """rect の外側を暗くし、縁を強調色で囲む。"""
    if a <= 0.001:
        return frame
    x, y, w, h = rect
    pad = 14
    box = (x - pad, y - pad, x + w + pad, y + h + pad)
    mask = Image.new("L", frame.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, 16, fill=255)
    dark = ImageEnhance.Brightness(frame).enhance(1 - dim * a)
    out = Image.composite(frame, dark, mask)
    d = ImageDraw.Draw(out, "RGBA")
    d.rounded_rectangle(box, 16, outline=(*accent, int(255 * a)), width=4)
    return out


def pulse(d: ImageDraw.ImageDraw, rect, p: float, accent) -> None:
    """処理完了時に対象を光らせる（枠が外へ広がって消える）。"""
    x, y, w, h = rect
    for k in range(2):
        q = min(1.0, max(0.0, p * 1.4 - k * 0.3))
        if q <= 0 or q >= 1:
            continue
        g = 6 + 22 * q
        d.rounded_rectangle((x - g, y - g, x + w + g, y + h + g), 14 + g / 2, outline=(*accent, int(220 * (1 - q))), width=4)


@lru_cache(maxsize=32)
def callout_image(text: str, accent: tuple) -> Image.Image:
    f = font(30, bold=True)
    w = int(f.getlength(text)) + 44
    im = rounded((w, 60), 14, (*accent, 250))
    ImageDraw.Draw(im).text((22, 30), text, font=f, fill=INK, anchor="lm")
    return im


def callout(layer: Image.Image, rect, text: str, a: float, accent) -> None:
    """スポットライトの対象に添える吹き出し。右→上→下の順で置ける場所を選ぶ。"""
    im = callout_image(text, accent)
    W, H = layer.size
    x, y, w, h = rect
    d = ImageDraw.Draw(layer)
    col = (*accent, int(250 * a))
    if x + w + 40 + im.width < W - 20:
        px, py = x + w + 40, y + min(h / 2, 90) - 30
        d.polygon([(px - 18, py + 30), (px + 2, py + 18), (px + 2, py + 42)], fill=col)
    elif y - 90 > 20:
        px, py = min(max(x + w / 2 - im.width / 2, 20), W - im.width - 20), y - 90
        d.polygon([(x + w / 2, y - 12), (x + w / 2 - 14, py + 58), (x + w / 2 + 14, py + 58)], fill=col)
    else:
        px, py = min(max(x + w / 2 - im.width / 2, 20), W - im.width - 20), y + h + 30
        d.polygon([(x + w / 2, y + h + 12), (x + w / 2 - 14, py + 2), (x + w / 2 + 14, py + 2)], fill=col)
    paste(layer, im, (px, py), a)


@lru_cache(maxsize=16)
def toast_image(text: str) -> Image.Image:
    f = font(28, bold=True)
    w = int(f.getlength(text)) + 110
    im = rounded((w, 76), 16, (*WHITE, 245))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, 75), 16, outline=(226, 232, 240, 255), width=2)
    cx, cy = 42, 38
    d.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), fill=(*OK_GREEN, 255))
    d.line([(cx - 9, cy), (cx - 2, cy + 8), (cx + 10, cy - 7)], fill=WHITE, width=5, joint="curve")
    d.text((74, cy), text, font=f, fill=INK, anchor="lm")
    return im


def toast(layer: Image.Image, text: str, p_in: float, a: float) -> None:
    """右上から滑り込む通知。"""
    im = toast_image(text)
    W = layer.size[0]
    x = W - im.width - 36 + (1 - ease_out(p_in)) * 60
    paste(layer, im, (x, 120), a)


@lru_cache(maxsize=8)
def badge_image(speed: float, accent: tuple) -> Image.Image:
    f = font(34, bold=True)
    label = f"早送り ×{speed:g}"
    w = int(f.getlength(label)) + 108
    im = rounded((w, 70), 35, (*INK, 220))
    d = ImageDraw.Draw(im)
    for k in range(2):
        x = 28 + k * 22
        d.polygon([(x, 19), (x + 21, 35), (x, 51)], fill=(*accent, 255))
    d.text((82, 35), label, font=f, fill=WHITE, anchor="lm")
    return im


def badge(layer: Image.Image, speed: float, a: float, accent) -> None:
    im = badge_image(speed, accent)
    paste(layer, im, (layer.size[0] - im.width - 36, 40), a)


# --- カード -------------------------------------------------------------------
def blurred(frame: Image.Image, darken: float = 0.45) -> Image.Image:
    small = frame.resize((frame.width // 4, frame.height // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(6))
    return ImageEnhance.Brightness(small.resize(frame.size, Image.BILINEAR)).enhance(darken)


def chapter_card(size, n: int, total: int, title: str, desc: str, accent) -> Image.Image:
    """章カード: STEP n / N、題名、説明、進捗バー。"""
    W, H = size
    cw, ch = 1100, 380
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    card = rounded((cw, ch), 28, (*INK, 238))
    d = ImageDraw.Draw(card)
    d.text((70, 78), f"STEP {n} / {total}", font=font(30, bold=True), fill=(*accent, 255), anchor="lm")
    d.text((70, 160), title, font=font(72, bold=True), fill=WHITE, anchor="lm")
    if desc:
        d.text((70, 245), desc, font=font(34), fill=MUTED, anchor="lm")
    seg_w = (cw - 140 - 12 * (total - 1)) / total
    for k in range(total):
        x = 70 + k * (seg_w + 12)
        fill = (*accent, 255) if k < n else (71, 85, 105, 255)
        d.rounded_rectangle((x, 314, x + seg_w, 324), 5, fill=fill)
    im.alpha_composite(card, ((W - cw) // 2, (H - ch) // 2))
    return im


def title_card(size, title: str, subtitle: str, accent) -> Image.Image:
    W, H = size
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((W / 2 - 60, H / 2 - 120, W / 2 + 60, H / 2 - 112), 4, fill=(*accent, 255))
    d.text((W / 2, H / 2 - 30), title, font=font(84, bold=True), fill=WHITE, anchor="mm")
    if subtitle:
        d.text((W / 2, H / 2 + 60), subtitle, font=font(38), fill=MUTED, anchor="mm")
    return im


def summary_card(size, title: str, items: list[str], text: str, accent) -> Image.Image:
    """まとめ: 章の一覧にチェックを付けて並べる。"""
    W, H = size
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    top = H / 2 - (70 + 76 * len(items) + (80 if text else 0)) / 2
    d.text((W / 2, top), title, font=font(64, bold=True), fill=WHITE, anchor="mt")
    f = font(40)
    widest = max((f.getlength(s) for s in items), default=0)
    x = W / 2 - (widest + 70) / 2
    y = top + 130
    for s in items:
        d.ellipse((x, y - 20, x + 40, y + 20), fill=(*accent, 255))
        d.line([(x + 10, y), (x + 18, y + 9), (x + 31, y - 9)], fill=INK, width=5, joint="curve")
        d.text((x + 66, y), s, font=f, fill=WHITE, anchor="lm")
        y += 76
    if text:
        d.text((W / 2, y + 30), text, font=font(34), fill=MUTED, anchor="mt")
    return im


def ease_out(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def fade(t: float, a: float, b: float, fin: float = 0.25, fout: float = 0.25) -> float:
    """区間 [a, b] で、入り fin 秒・出 fout 秒のフェードを付けた不透明度。"""
    if t < a or t > b:
        return 0.0
    return max(0.0, min(1.0, (t - a) / fin if fin else 1.0, (b - t) / fout if fout else 1.0))


def progress(t: float, a: float, d: float) -> float:
    return min(1.0, max(0.0, (t - a) / d))


