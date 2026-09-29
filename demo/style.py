"""演出の既定値と「場面に応じた」自動ルール。

ステップの種類から演出を自動で決め、YAML の各ステップの `effect:` で上書きできる。

| ステップ | カメラ | 演出 |
|---|---|---|
| chapter | 全体 | 章カード（STEP n / N と進捗バー、背景ぼかし） |
| click / upload | 対象へズームイン | クリックの波紋 |
| type | 対象へズームイン | 波紋 ＋ キー表示（入力中の文字を左下に出す） |
| download | 対象へズームイン | 波紋 ＋ 保存トースト（ファイル名入り） |
| wait_for | 全体へ引く | 早送りバッジ、完了時に対象を光らせる（パルス） |
| hover | 対象が収まる程度に寄る | スポットライト（周囲を暗く）＋ 任意の吹き出し |
| open_download | 窓が出たらデータ範囲へ寄る | なし（実カーソルでセルをなぞる） |
| compare | 全体 | 導入前後の比較カード（導入後の側が遅れて滑り込む） |

数え上げ（`effect: {countup: {to: 6, label: 指摘, suffix: 件}}`）はどのステップにも付けられる。
"""
from __future__ import annotations

import copy

DEFAULT_STYLE = {
    "effects": "rich",          # rich（合成で演出）| simple（従来の焼き込み字幕のみ）
    "accent": "#FFB020",        # 強調色（字幕の強調語、波紋、枠、進捗）
    "max_zoom": 1.6,            # カメラの最大拡大率
    "caption_label": True,      # 字幕の左に現在の章名を出す
    "speed_badge": True,        # 早送り中に「早送り ×N」を出す
    "intro": True,              # 冒頭のタイトルカード（true / false / {title, subtitle, duration}）
    "outro": True,              # 末尾のまとめカード（true / false / {title, text, duration}）
    "reading_cps": None,        # 字幕を読む速さ（字/秒）。None は言語ごとの既定（ja 7, en 15）
    # 常時ガイド: 右上のパンくず（[シーン n/N] シーン名 › 章名）と、下端の進行バー（章・シーンの区切り目盛り付き）
    "guide": {"breadcrumb": True, "progress_bar": True, "position": "top-right"},
}

AUTO_EFFECT = {
    "chapter": {"zoom": "out"},
    "click": {"zoom": "focus", "ripple": True},
    "upload": {"zoom": "focus", "ripple": True},
    "type": {"zoom": "focus", "ripple": True, "keys": True},
    "download": {"zoom": "focus", "ripple": True, "toast": "auto"},
    "wait_for": {"zoom": "out", "pulse": True},
    "hover": {"zoom": "fit", "spotlight": True},
    "open_download": {"zoom": "fit"},
    "compare": {"zoom": "out"},
    "pause": {},
}


def scene_style(scene: dict) -> dict:
    st = copy.deepcopy(DEFAULT_STYLE)
    user = dict(scene.get("style") or {})
    guide = user.pop("guide", None)
    st.update(user)
    if guide is False:
        st["guide"] = {"breadcrumb": False, "progress_bar": False, "position": "top-right"}
    elif isinstance(guide, dict):
        st["guide"].update(guide)
    return st


def step_effects(scene: dict) -> list[dict]:
    """ステップ順に、自動ルールと YAML の effect を合わせた演出指定を返す。"""
    out = []
    for step in scene["steps"]:
        kind, spec = next(iter(step.items()))
        eff = dict(AUTO_EFFECT.get(kind, {}))
        if isinstance(spec, dict) and isinstance(spec.get("effect"), dict):
            eff.update(spec["effect"])
        if eff.get("zoom") is False:
            eff["zoom"] = "out"
        out.append(eff)
    return out


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
