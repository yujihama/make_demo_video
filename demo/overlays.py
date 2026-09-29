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
AUTO_EMPH = {
    # 数値の末尾に句読点（8, や 8.）を含めない
    "ja": re.compile(r"\d(?:[\d,，.]*\d)?(?:万|億)?(?:件|円|%|％|秒|分|時間|日|名|人|行|倍|割)?"),
    "en": re.compile(r"(?:JPY\s?|¥|\$)?\d(?:[\d,.]*\d)?(?:\s?(?:%|x|items?|cases?|findings?|issues?|yen|seconds?|minutes?"
                     r"|hours?|days?|rules?|transactions?)\b)?"),
}
NO_LINE_START = set("、。，．・：；？！）」』】〕ー…,.;:!?)")
WORD_CHAR = re.compile(r"[0-9A-Za-z_\-'%$¥.,/]")


def parse_emphasis(text: str, lang: str = "ja") -> list[tuple[str, bool]]:
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
    for m in AUTO_EMPH.get(lang, AUTO_EMPH["en"]).finditer(text):
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
    """折り返す。日本語などは文字単位（行頭禁則つき）、英語などは単語単位。戻り値: 行ごとの [(文字, 強調か)]"""
    chars = [(c, e) for s, e in runs for c in s]
    # 単語（英数字の連なり）は分けない塊にする
    tokens, word = [], []
    for c, e in chars:
        if WORD_CHAR.match(c):
            word.append((c, e))
            continue
        if word:
            tokens.append(word)
            word = []
        tokens.append([(c, e)])
    if word:
        tokens.append(word)
    lines, cur, w = [], [], 0.0
    for tok in tokens:
        tw = sum(fonts[e].getlength(c) for c, e in tok)
        if cur and w + tw > max_w and tok[0][0] not in NO_LINE_START:
            while cur and cur[-1][0] == " ":
                cur.pop()
            lines.append(cur)
            cur, w = [], 0.0
            if tok[0][0] == " ":
                continue
        cur.extend(tok)
        w += tw
    if cur:
        lines.append(cur)
    return lines


def rounded(size, radius, fill) -> Image.Image:
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=fill)
    return im


@lru_cache(maxsize=64)
def caption_image(text: str, label: str | None, accent: tuple, max_w: int = 1560, size: int = 38,
                  lang: str = "ja") -> Image.Image:
    """下部（または上部）に出す字幕パネル。左に章ラベル、本文は強調語を強調色の太字で。"""
    fonts = {False: font(size), True: font(size, bold=True)}
    lab_font = font(24, bold=True)
    lab_w = int(lab_font.getlength(label)) + 28 if label else 0
    text_max = max_w - 56 - (lab_w + 18 if label else 0)
    lines = _wrap(parse_emphasis(text, lang), fonts, text_max)
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


def toast(layer: Image.Image, text: str, p_in: float, a: float, y: int = 120) -> None:
    """右上から滑り込む通知。y はガイドがあるときに下へずらす。"""
    im = toast_image(text)
    W = layer.size[0]
    x = W - im.width - 36 + (1 - ease_out(p_in)) * 60
    paste(layer, im, (x, y), a)


@lru_cache(maxsize=8)
def badge_image(label: str, accent: tuple) -> Image.Image:
    f = font(34, bold=True)
    w = int(f.getlength(label)) + 108
    im = rounded((w, 70), 35, (*INK, 220))
    d = ImageDraw.Draw(im)
    for k in range(2):
        x = 28 + k * 22
        d.polygon([(x, 19), (x + 21, 35), (x, 51)], fill=(*accent, 255))
    d.text((82, 35), label, font=f, fill=WHITE, anchor="lm")
    return im


def badge(layer: Image.Image, label: str, a: float, accent) -> None:
    im = badge_image(label, accent)
    paste(layer, im, (layer.size[0] - im.width - 36, 40), a)


# --- カード -------------------------------------------------------------------
def blurred(frame: Image.Image, darken: float = 0.45) -> Image.Image:
    small = frame.resize((frame.width // 4, frame.height // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(6))
    return ImageEnhance.Brightness(small.resize(frame.size, Image.BILINEAR)).enhance(darken)


def chapter_card(size, n: int, total: int, title: str, desc: str, accent, step_label: str | None = None) -> Image.Image:
    """章カード: STEP n / N、題名、説明、進捗バー。"""
    W, H = size
    cw, ch = 1100, 380
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    card = rounded((cw, ch), 28, (*INK, 238))
    d = ImageDraw.Draw(card)
    d.text((70, 78), step_label or f"STEP {n} / {total}", font=font(30, bold=True), fill=(*accent, 255), anchor="lm")
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


def title_card(size, title: str, subtitle: str, accent, eyebrow: str = "") -> Image.Image:
    """題名カード。eyebrow は題名の上の小見出し（通し版の「シーン 2 / 2」など）。"""
    W, H = size
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((W / 2 - 60, H / 2 - 120, W / 2 + 60, H / 2 - 112), 4, fill=(*accent, 255))
    if eyebrow:
        d.text((W / 2, H / 2 - 160), eyebrow, font=font(34, bold=True), fill=(*accent, 255), anchor="mm")
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


# --- 視線誘導 -----------------------------------------------------------------------
def _keyboard_icon(d: ImageDraw.ImageDraw, x, y, col) -> None:
    d.rounded_rectangle((x, y, x + 46, y + 30), 6, outline=col, width=3)
    for r in range(2):
        for c in range(5):
            d.rectangle((x + 6 + c * 8, y + 7 + r * 8, x + 10 + c * 8, y + 10 + r * 8), fill=col)
    d.rectangle((x + 12, y + 22, x + 34, y + 25), fill=col)


def keystrokes(layer: Image.Image, label: str, typed: str, caret: bool, a: float, accent) -> None:
    """入力中の文字を左下に表示する（キー表示）。"""
    f = font(34, bold=True)
    lab_f = font(22, bold=True)
    text = typed + ("|" if caret else " ")
    w = int(max(f.getlength(text), 120) + lab_f.getlength(label) + 150)
    im = rounded((w, 78), 18, (*INK, 225))
    d = ImageDraw.Draw(im)
    _keyboard_icon(d, 22, 24, (*accent, 255))
    lx = 84
    d.text((lx, 39), label, font=lab_f, fill=MUTED, anchor="lm")
    d.text((lx + lab_f.getlength(label) + 18, 39), text, font=f, fill=WHITE, anchor="lm")
    paste(layer, im, (44, layer.size[1] - im.height - 150), a)


def format_number(v: float, decimals: int) -> str:
    return f"{v:,.{decimals}f}"


@lru_cache(maxsize=64)
def countup_image(label: str, number: str, suffix: str, accent: tuple) -> Image.Image:
    lab_f, num_f, suf_f = font(28, bold=True), font(64, bold=True), font(34, bold=True)
    w = int(max(lab_f.getlength(label), num_f.getlength(number) + suf_f.getlength(suffix) + 8)) + 64
    im = rounded((w, 150), 20, (*accent, 250))
    d = ImageDraw.Draw(im)
    d.text((32, 36), label, font=lab_f, fill=INK, anchor="lm")
    nw = num_f.getlength(number)
    d.text((32, 100), number, font=num_f, fill=INK, anchor="lm")
    d.text((32 + nw + 8, 108), suffix, font=suf_f, fill=INK, anchor="lm")
    return im


def countup(layer: Image.Image, rect, label: str, value: float, suffix: str, decimals: int, a: float, accent) -> None:
    """数値を数え上げて見せる大きな吹き出し。置き場所は callout と同じ考え方（右→上→下）。"""
    im = countup_image(label, format_number(value, decimals), suffix, accent)
    W, H = layer.size
    if rect is None:
        paste(layer, im, (W - im.width - 60, 200), a)
        return
    x, y, w, h = rect
    if x + w + 40 + im.width < W - 20:
        px, py = x + w + 40, max(20, y + min(h / 2, 120) - im.height / 2)
    elif y - im.height - 30 > 20:
        px, py = min(max(x + w / 2 - im.width / 2, 20), W - im.width - 20), y - im.height - 30
    else:
        px, py = min(max(x + w / 2 - im.width / 2, 20), W - im.width - 20), min(y + h + 30, H - im.height - 20)
    paste(layer, im, (px, py), a)


def compare_card(size, title: str, before: dict, after: dict, p_after: float, accent) -> Image.Image:
    """導入前と導入後を左右に並べるカード。導入後の側は p_after に合わせて滑り込む。"""
    W, H = size
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((W / 2, H / 2 - 250), title, font=font(56, bold=True), fill=WHITE, anchor="mm")
    pw, ph, gap = 620, 330, 150
    y0 = H / 2 - 170

    def panel(data, fill, ink, head_col):
        card = rounded((pw, ph), 24, fill)
        c = ImageDraw.Draw(card)
        c.text((44, 58), data.get("label", ""), font=font(32, bold=True), fill=head_col, anchor="lm")
        c.text((44, 160), data.get("value", ""), font=font(92, bold=True), fill=ink, anchor="lm")
        if data.get("note"):
            c.text((44, 262), data["note"], font=font(28), fill=ink, anchor="lm")
        return card

    left = panel(before, (51, 65, 85, 235), (226, 232, 240, 255), (148, 163, 184, 255))
    im.alpha_composite(left, (int(W / 2 - gap / 2 - pw), int(y0)))
    ax = W / 2
    d.polygon([(ax - 34, y0 + ph / 2 - 30), (ax + 30, y0 + ph / 2), (ax - 34, y0 + ph / 2 + 30)], fill=(*accent, 255))
    if p_after > 0:
        right = panel(after, (*accent, 250), (*INK, 255), (*INK, 255))
        slide = (1 - ease_out(p_after)) * 60
        im.alpha_composite(with_alpha(right, min(1.0, p_after * 1.5)), (int(W / 2 + gap / 2 + slide), int(y0)))
    return im


# --- 常時ガイド（通し版の中で今どこかを示す） ------------------------------------------
GUIDE_MARGIN = 28


def chevron(d: ImageDraw.ImageDraw, x: float, y: float, col, size: int = 9) -> None:
    """区切りの「›」。フォントに無いことがあるので図形で描く。"""
    d.line([(x, y - size), (x + size * 0.75, y), (x, y + size)], fill=col, width=3, joint="curve")


@lru_cache(maxsize=64)
def breadcrumb_image(scene_chip: str | None, scene_title: str, chapter_title: str | None, fast: str | None,
                     accent: tuple) -> Image.Image:
    """右上のパンくず: [1/2] シーン名 › 章名。早送り中は先頭に「▶▶ 早送り ×4」を入れる。"""
    f, fb, fs = font(26), font(26, bold=True), font(20, bold=True)
    items = []  # (種類, 文字, 幅)
    if fast:
        items.append(("fast", fast, fs.getlength(fast) + 58))
    if scene_chip:
        items.append(("chip", scene_chip, fs.getlength(scene_chip) + 20))
    items.append(("scene", scene_title, (fb if not chapter_title else f).getlength(scene_title)))
    if chapter_title:
        items.append(("sep", "", 12))
        items.append(("chapter", chapter_title, fb.getlength(chapter_title)))
    gap = 16
    w = int(sum(x[2] for x in items) + gap * (len(items) - 1) + 44)
    h = 54
    im = rounded((w, h), h // 2, (*INK, 210))
    d = ImageDraw.Draw(im)
    x, cy = 22, h / 2
    for kind, text, iw in items:
        if kind == "fast":
            d.rounded_rectangle((x - 6, cy - 16, x + iw - 6, cy + 16), 16, fill=(*accent, 255))
            for k in range(2):
                tx = x + 8 + k * 13
                d.polygon([(tx, cy - 8), (tx + 12, cy), (tx, cy + 8)], fill=INK)
            d.text((x + 40, cy), text, font=fs, fill=INK, anchor="lm")
        elif kind == "chip":
            d.rounded_rectangle((x, cy - 15, x + iw, cy + 15), 8, fill=(*accent, 255))
            d.text((x + iw / 2, cy), text, font=fs, fill=INK, anchor="mm")
        elif kind == "scene":
            d.text((x, cy), text, font=f if chapter_title else fb, fill=MUTED if chapter_title else WHITE, anchor="lm")
        elif kind == "sep":
            chevron(d, x + 2, cy, (148, 163, 184, 255))
        else:
            d.text((x, cy), text, font=fb, fill=WHITE, anchor="lm")
        x += iw + gap
    return im


def breadcrumb_rect(im: Image.Image, W: int, position: str = "top-right") -> tuple[int, int, int, int]:
    x = W - im.width - GUIDE_MARGIN if position == "top-right" else GUIDE_MARGIN
    return (x, GUIDE_MARGIN, im.width, im.height)


def progress_bar(layer: Image.Image, g: float, total: float, ticks, accent, a: float = 1.0) -> None:
    """画面の最下部に、通し版全体の進み具合を細いバーで描く。章の区切りは細い目盛り、シーンの区切りは太く高い目盛り。"""
    if a <= 0.001 or total <= 0:
        return
    W, H = layer.size
    d = ImageDraw.Draw(layer)
    y = H - 8
    d.rectangle((0, y, W, H), fill=(*INK, int(170 * a)))
    d.rectangle((0, y, int(W * min(1.0, max(0.0, g / total))), H), fill=(*accent, int(255 * a)))
    for tg, kind in ticks:
        x = W * tg / total
        if 1 < x < W - 1:
            if kind == "scene":
                d.rectangle((x - 2, y - 8, x + 2, H), fill=(255, 255, 255, int(235 * a)))
            else:
                d.rectangle((x - 1, y, x + 1, H), fill=(255, 255, 255, int(200 * a)))


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


