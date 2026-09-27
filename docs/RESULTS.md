# デモ動画 撮影検証 結果（2026-09-27）

> 検証時の記録です。文中の `out/`・`p1/` などのパスは検証環境のもので、このキットには含まれません。
> 検証は Windows 11 + Docker Desktop で行い、キットは Linux 向けに整えてから Ubuntu で導入確認しています。

対象アプリは Docker で起動した検証用アプリ（`sample-app/`、FastAPI、`http://localhost:8080`）。
画面は「証跡アップロード → 監査実行 → 結果表示 → Excel ダウンロード」と「規程Q&A」の2つ。
撮影環境は Windows 11 + Docker Desktop（20 CPU / 24GB）。

**結論: 全段階が合格判定を満たした。Claude Code でブラウザアプリの動画は撮れる。**
残したアセットは YAML シーン定義 + 決定的ランナー + 後工程 + 自己確認ループ + スキル（`.claude/skills/demo-video`）。

## 段階ごとの判定

| 段階 | 合格判定 | 結果 | 実測 |
|---|---|---|---|
| P0 棚卸し | 各パーツが手元で起動する | 合格（条件付き） | Playwright MCP 0.0.82 / webapp-testing / smooth-cursor 0.1.0 / playwriter 0.7.0 / recast 0.21.0 は起動。demo-review・crv はこの環境に無く、代替を自作 |
| P1 対話で撮る | 動画が出る。アップロード・日本語・ダウンロード | 合格 | 1920x1080 25fps WebM 56.3秒。3点とも動画上で確認。Excel 6件の指摘を保存 |
| P2 スクリプト化 | 同じ動画が3回連続で再現、data-testid で安定 | 合格 | 長さ 27.64/27.56/27.56秒、操作時刻のずれ最大 0.076秒、フレーム差 最大 0.71（閾値 3.0） |
| G1 判断 | ファイル表示のない場面の要件を満たすか | 併用に決定 | 下記 |
| P3 デスクトップ録画 | ブラウザ＋Calc が1本、座標ずれなし、メモリが設計内 | 合格 | 1本の MP4 に両方。カーソル誤差 最大 0.71px。メモリ ピーク 1,062MB（録画コンテナ）+ 38MB（アプリ）で 8GB 設計内。Calc 起動 1.6秒 |
| P4 後工程 | YAML→動画一式が1コマンド | 合格 | `python -m demo make scenes/<id>.yaml` で final.mp4 / subtitles.srt / chapters.json / review.json |
| P5 自己確認ループ | 人が触らず合格に到達 | 合格 | 壊したシーン 2〜3反復（約1.5分）、desktop 版 3反復（約2分）で合格。修正は YAML の1行ずつ |
| P6 アセット化 | 新モジュールは YAML 追加だけで撮れる | 合格 | 規程Q&A を `scenes/policy_qa.yaml` の追加だけで撮影・合格。`demo/` のハッシュ不変 |

## G1 の判断

ブラウザ内の場面は P2 方式、ファイルを開いて見せる場面だけ P3 方式の併用とする。
両方式は同じ YAML・同じ操作ログ・同じ後工程を使うため、懸念していた「台本と後工程の分裂」は起きなかった。

| 観点 | P2（Playwright 録画＋描画カーソル） | P3（Xvfb 画面録画＋実カーソル） |
|---|---|---|
| 環境 | ホストの Chromium のみ | 4.55GB のイメージ、実行時 約1GB |
| 1本の所要（Core） | 約35秒 | 約45秒 |
| カーソル | playwriter の描画カーソル（1.2秒の直線移動） | X の実カーソル（DMZ-Black） |
| ファイル表示 | できない | Calc で開ける（日本語メニュー・データとも表示） |

1本の動画の中では方式を混ぜない（カーソルの見た目が変わる）。

## 既存パーツの採否

| パーツ | 採否 | 理由 |
|---|---|---|
| Playwright MCP 動画機能 | P1 のみ | `browser_start_video` と章カードで撮れた。対話の思考時間がそのまま静止区間になり（56秒中 約40秒）、再現性もない |
| `--save-video` | 使えず | 0.0.82 の CLI から消えている。録画は `browser_start_video` で行う |
| webapp-testing | 型を採用 | sync_playwright + networkidle 待ちの型はそのまま。`with_server.py` は Windows では実行ファイルを絶対パスで渡す必要あり |
| smooth-cursor-playwright | 不採用（比較用に残す） | 軌跡を作るだけで描画しない（オーバーレイは別プロセス）。移動が遅く1回 4.2秒、動画が 28秒→40秒に伸びる |
| playwriter | カーソルを採用 | `ghost-cursor-client.js` を単体でページに注入して使える（MIT）。待ち早送りは自作と同等の結果 |
| playwright-recast | 不採用 | Windows で字幕・カーソル合成が失敗（パス処理）。操作を Playwright API の click からしか拾えず全体 3倍速になる。トレース単体は約5fps で 1.63 のトレースを読めない |
| computer-use-demo | 構成を参考 | Xvfb・xdotool・LibreOffice の組み合わせを流用。WM は openbox、Python はベースイメージのものに簡略化 |

## 途中で見つけて直したこと

- headless shell はファイル選択ボタンが英語 → フル版 Chromium（`channel="chromium"`）に変更
- Playwright の録画は CSS ピクセル寸法で撮られ `device_scale_factor` が効かない → `zoom`（body の CSS zoom）を追加
- アプリの処理時間の揺れ（最大 0.45秒）で再現性が崩れる → `wait_for.duration` でステップ長を固定
- 字幕が操作対象（ダウンロードボタン）を隠す → 対象が画面下寄りなら字幕を上に出す
- Claude デスクトップアプリ配下では %APPDATA% が振り替えられ、Docker のバインドマウントが空になる → 実パスを自動解決

## 未検証・残課題

- 子プロセスの Claude Code（`claude -p`）はこの端末で CLI が未ログインのため起動できなかった。P1 は Claude Code 本体（このセッション）が MCP を1ツールずつ呼んで対話操作した。P5 の `--fixer claude` は実装済みだが未実行で、規則ベースの修正で自走を確認した
- 静止区間の判定は小さなカーソルの動きを数えない。描画カーソルは5秒で自動で隠れるため判定が揺れることがある
- 対象は検証用アプリ。本番の内部監査エージェントでの data-testid の付き具合は未確認
- noVNC での撮影中の目視は、`--network container:` だとポート公開できないため未確認（アプリ側で 6080 を公開すれば可能）

## 主な成果物

- 完成動画: `out/core_audit/loop/iter2/build/final.mp4`（browser）、`out/core_audit_desktop/loop/iter3/build/final.mp4`（desktop）、`out/policy_qa/run/build/final.mp4`（新モジュール）
- P1 の対話録画: `p1/out/p1_core.webm`、操作列 `p1/steps.json`
- 再現性: `out/p2/repro_final/repro.json`、自己確認ループ: `out/*/loop/loop.json`
- コード: `demo/`（ランナー・後工程・判定・ループ）、`recorder/Dockerfile`、`scenes/*.yaml`、`.claude/skills/demo-video/SKILL.md`
