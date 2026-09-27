---
name: demo-video
description: localhost で動く Web アプリのデモ動画を、YAML のシーン定義から決定的に撮影・編集・自己確認する。「デモ動画を撮って」「この画面の操作動画を作って」「シーンを追加して撮り直して」「動画が合格するまで直して」と言われたとき、または scenes/*.yaml を追加・修正するときに使う。
---

# デモ動画スキル

シーン定義（`scenes/<id>.yaml`）を書くと、同じ操作・同じ間合いの動画が何度でも撮れる。
ツール本体（`demo/`）は触らない。直すのは常に YAML。

## 前提

- キットが導入済み（`install.sh` 実行済み）で、`bin/demo` が使えること。PATH に無ければキットのフォルダの `bin/demo` を使う
- 対象アプリが起動していて `http://localhost:<port>` で開けること
- 画面要素に `data-testid` が付いていること。付いていない要素は撮れない（アプリ側に足してもらう）
- desktop モードは録画イメージ `demo-recorder:latest` が必要（`install.sh --desktop`）

## コマンド

| やること | コマンド | 出力 |
|---|---|---|
| セレクタ確認（録画なし・数秒） | `bin/demo dryrun scenes/<id>.yaml` | 失敗したステップと testid |
| 録画→後工程→判定 | `bin/demo make scenes/<id>.yaml` | `out/<id>/run/build/final.mp4`, `review.json` |
| 合格まで自動で直す | `bin/demo loop scenes/<id>.yaml` | `out/<id>/loop/iterN/`（review.json と fix.diff） |
| 再現性の確認 | `bin/demo repro scenes/<id>.yaml -n 3` | `out/<id>/repro/repro.json` |
| 英語版などを作る | `bin/demo translate scenes/<id>.yaml --lang en` → `bin/demo make scenes/<id>.yaml --lang ja,en` | `build-en/final.mp4` |
| Claude の見た目の審査込みで直す | `bin/demo loop scenes/<id>.yaml --lang ja,en --vision` | `build*/vision.json` |
| 画面確認用の一覧画像 | `.venv/bin/python -m demo.crv <final.mp4>` | コンタクトシート PNG |

## 新しい画面を撮る手順

1. 画面を開き、操作する要素の `data-testid` を確認する（HTML を読むか、Playwright で `page.locator('[data-testid]')` を列挙）
2. `scenes/_template.yaml` をコピーして `scenes/<id>.yaml` を書く。スキーマは `demo/scene.schema.json`
3. `bin/demo dryrun` で全ステップが通ることを確認する。通らなければ testid を直す
4. `bin/demo loop scenes/<id>.yaml` で合格まで回す。止まったら `review.json` の hint を読んで YAML を直す
5. コンタクトシートで字幕・章・カーソルを目で確認し、`final.mp4` を渡す

## YAML を直すときの目安

- `wait_for.duration` を付けるとアプリの処理時間の揺れを吸収でき、毎回同じ動画になる。付けないと再現性が落ちる
- 判定 `steps` の overrun → `wait_for.duration` を overrun_ms + 500 以上に伸ばす
- 判定 `freeze` → 該当ステップの `hold` を縮める（見せ場は 3 秒以内）
- `caption` は字幕になる。操作対象が画面下寄りなら自動で上に出る
- `name` を付けたステップはその時点の画面が保存され、`review.expect_text` で照合される

## 演出（字幕・効果・強調）

演出は後工程で操作ログから自動で付く。撮り直さずに `bin/demo build out/<id>/run` で作り直せる。

- ステップの種類で自動: クリック系は寄って波紋、`wait_for` は引いて早送り表示＋完了パルス、`hover` はスポットライト、`download` は保存通知、`chapter` は進捗つき章カード。冒頭にタイトル、末尾にまとめ
- 字幕の強調は `**語**`。無ければ数値＋単位を自動で強調。数字や固有の機能名など「見てほしい語」を1字幕に1〜2個まで
- 見せ場（結果の表など）の `hover` には `effect: {callout: 短い一言}` か `effect: {countup: {to: 6, label: 指摘, suffix: 件}}` を付けると伝わりやすい
- 導入効果は `compare` ステップ（導入前後の比較カード）で最後に見せる
- 演出が過剰な場面は `effect: {zoom: false, ripple: false}` などで個別に外す。全体をやめるなら `style: {effects: simple}`
- 仕上がりはコンタクトシート（`.venv/bin/python -m demo.crv <final.mp4> --frames 15`）で、字幕が操作対象を隠していないか、寄りすぎて文脈が切れていないかを見る

## 読み切れる字幕・多言語版・見た目の審査

- 判定は字幕ごとに「表示秒数 ≥ 文字数 ÷ 読む速さ + 0.4 秒」を見る（ja 7 字/秒、en 15 字/秒）。`loop` が足りない分だけ `hold` を伸ばす。字幕を短くできるなら、そのほうが動画は締まる
- 多言語版は録画1回で作れる。翻訳ファイル `scenes/<id>.<lang>.yaml` は人が直してよい（`_src` は消さない）。元の字幕を直したら `translate` をもう一度
- `--vision` は要所のコマを Claude に見せ、隠れ・読みにくさ・強調の的外れ・寄りすぎ・はみ出し・言語違いを指摘させる。high があれば不合格。直し方（hold / caption / effect / style.max_zoom）は `loop` がそのまま反映する
- Claude を呼べない環境（終了コード 3）では、`out/<id>/_claude/…/request.md` と画像を読んで `schema.json` どおりの `response.json` を置き、同じコマンドをもう一度実行する。Claude Code のセッション自身が審査者・翻訳者になってよい

## browser と desktop の使い分け

- ブラウザ内で完結する場面は browser（既定）
- ダウンロードしたファイルを Calc で開いて見せる場面だけ `mode: desktop` と `open_download` ステップ
- desktop でアプリに届かないときは `DEMO_APP_CONTAINER`（アプリのコンテナ名）か `DEMO_NETWORK=host` を設定する
- 1本の動画の中では方式を混ぜない
