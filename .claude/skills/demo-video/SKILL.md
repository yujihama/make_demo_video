---
name: demo-video
description: localhost で動く Web アプリのデモ動画を、YAML のシーン定義から決定的に撮影・編集・自己確認する。見た目の審査と字幕の翻訳は Claude Code 自身が行う。「デモ動画を撮って」「この画面の操作動画を作って」「シーンを追加して撮り直して」「動画が合格するまで直して」「動画を確認・審査して」「英語版を作って」と言われたとき、`bin/demo` が終了コード 3（Claude Code の判断待ち）で止まったとき、または scenes/*.yaml を追加・修正するときに使う。
---

# デモ動画スキル

シーン定義（`scenes/<id>.yaml`）を書くと、同じ操作・同じ間合いの動画が何度でも撮れる。
ツール本体（`demo/`）は触らない。直すのは常に YAML（シーンと翻訳ファイル）。

**判断が要る作業はあなた（Claude Code）が行う。** ツールは Claude を API や CLI で呼ばない。
見た目の審査と翻訳は、ツールが依頼を `out/**/_handoff/<名前>-<ハッシュ>/` に書き出して終了コード 3 で止まるので、
あなたが画像を見て `response.json` を書き、同じコマンドを再実行する。

## 前提

- キットが導入済み（`install.sh` 実行済み）で、`bin/demo` が使えること。PATH に無ければキットのフォルダの `bin/demo` を使う
- 対象アプリが起動していて `http://localhost:<port>` で開けること
- 画面要素に `data-testid` が付いていること。付いていない要素は撮れない（アプリ側に足してもらう）
- desktop モードは録画イメージ `demo-recorder:latest` が必要（`install.sh --desktop`）

## コマンド

| やること | コマンド | 出力 |
|---|---|---|
| セレクタ確認（録画なし・数秒） | `bin/demo dryrun scenes/<id>.yaml` | 失敗したステップと testid |
| 録画→後工程→判定 | `bin/demo make scenes/<id>.yaml [--lang ja,en] [--vision]` | `out/<id>/run/build*/final.mp4`, `review*.json` |
| 合格まで直す | `bin/demo loop scenes/<id>.yaml [--lang ja,en] [--vision]` | `out/<id>/loop/iterN/`（review*.json と fix.diff） |
| 止まったループの続き | 上と同じコマンドに `--resume` | |
| 判定だけやり直す | `bin/demo review out/<id>/run [--lang en] [--vision]` | `review*.json` |
| 翻訳ファイルを作る | `bin/demo translate scenes/<id>.yaml --lang en` | `scenes/<id>.en.yaml` |
| 回答待ちの依頼を探す | `bin/demo pending` | 依頼フォルダの一覧（無ければ終了コード 0） |
| 再現性の確認 | `bin/demo repro scenes/<id>.yaml -n 3` | `out/<id>/repro/repro.json` |
| 画面確認用の一覧画像 | `.venv/bin/python -m demo.crv <final.mp4> --frames 15` | コンタクトシート PNG |

## 基本の流れ

1. 画面を開き、操作する要素の `data-testid` を確認する（HTML を読むか、Playwright で `page.locator('[data-testid]')` を列挙）
2. `scenes/_template.yaml` をコピーして `scenes/<id>.yaml` を書く。スキーマは `demo/scene.schema.json`
3. `bin/demo dryrun scenes/<id>.yaml` で全ステップが通ることを確認する。通らなければ testid を直す
4. 多言語版が要るなら `bin/demo translate scenes/<id>.yaml --lang en` → 終了コード 3 → [reference/translate.md](reference/translate.md) の手順で訳を書く → 同じコマンドを再実行
5. `bin/demo loop scenes/<id>.yaml --lang ja,en --vision` で回す
   - 終了コード 3 で止まったら、[reference/vision-review.md](reference/vision-review.md) の手順で表示された依頼フォルダをすべて審査し、`--resume` を付けて同じコマンドを再実行する
   - 規則で直せない失敗が残って止まったら、`review*.json` の `hint` と審査の `suggestion` を読んで YAML を直し、`--resume` を付けずにもう一度 `loop` を回す
6. 合格したら `out/<id>/loop/iterN/build*/final.mp4` を渡す。最終回の `vision.json` の要約と、残った low の指摘を一緒に伝える

## 終了コード 3（Claude Code の判断待ち）への対応

- 表示された依頼フォルダ（`bin/demo pending` でも一覧できる）の `request.md` を最初に読む。何を判断し、どの形式で答えるかが書いてある
- 依頼名が `vision-…` なら見た目の審査 → [reference/vision-review.md](reference/vision-review.md)
- 依頼名が `translate-…` なら翻訳 → [reference/translate.md](reference/translate.md)
- 回答は `schema.json` に合う JSON を `response.json` として同じフォルダに UTF-8 で書く。形が合わなければ再実行時にエラーで止まるので、直して再実行する
- 回答を書いたら、止まったコマンドを再実行する（`loop` は `--resume`）。依頼の中身が変わると別フォルダになるので、古い回答が混ざることはない
- 依頼が複数（言語ごとなど）あるときは、全部に回答してから再実行する

## YAML を直すときの目安

- `wait_for.duration` を付けるとアプリの処理時間の揺れを吸収でき、毎回同じ動画になる。付けないと再現性が落ちる
- 判定 `steps` の overrun → `wait_for.duration` を overrun_ms + 500 以上に伸ばす
- 判定 `freeze` → 該当ステップの `hold` を縮める（見せ場は 3 秒以内。字幕が出ている間は字幕の表示秒数 + 0.5 秒まで許される）
- 判定 `readability` → 字幕に対して表示が短い。`loop` が `hold` を伸ばす。字幕を短くできるなら、そのほうが動画は締まる（ja 7 字/秒、en 15 字/秒）
- `caption` は字幕になる。`**語**` で強調（1字幕に1〜2個まで）。操作対象と重なるときだけ自動で上に出る
- `name` を付けたステップはその時点の画面が保存され、`review.expect_text` で照合される

## 演出（字幕・効果・強調）

演出は後工程で操作ログから自動で付く。撮り直さずに `bin/demo build out/<id>/run` で作り直せる。

- ステップの種類で自動: クリック系は寄って波紋、`type` はキー表示、`wait_for` は引いて早送り表示＋完了パルス、`hover` はスポットライト、`download` は保存通知、`chapter` は進捗つき章カード。冒頭にタイトル、末尾にまとめ
- 見せ場（結果の表など）の `hover` には `effect: {callout: 短い一言}` か `effect: {countup: {to: 6, label: 指摘, suffix: 件}}` を付けると伝わりやすい
- 導入効果は `compare` ステップ（導入前後の比較カード）で最後に見せる
- 演出が過剰な場面は `effect: {zoom: false, ripple: false}` などで個別に外す。全体をやめるなら `style: {effects: simple}`

## browser と desktop の使い分け

- ブラウザ内で完結する場面は browser（既定）
- ダウンロードしたファイルを Calc で開いて見せる場面だけ `mode: desktop` と `open_download` ステップ
- desktop でアプリに届かないときは `DEMO_APP_CONTAINER`（アプリのコンテナ名）か `DEMO_NETWORK=host` を設定する
- 1本の動画の中では方式を混ぜない
