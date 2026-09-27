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

## browser と desktop の使い分け

- ブラウザ内で完結する場面は browser（既定）
- ダウンロードしたファイルを Calc で開いて見せる場面だけ `mode: desktop` と `open_download` ステップ
- desktop でアプリに届かないときは `DEMO_APP_CONTAINER`（アプリのコンテナ名）か `DEMO_NETWORK=host` を設定する
- 1本の動画の中では方式を混ぜない
