# デモ動画キット（demo-video-kit）

localhost で動く Web アプリのデモ動画を、YAML のシーン定義から撮影・編集・自己確認するツール一式です。
同じ YAML からは何度撮っても同じ動画になります。
操作ログから場面に応じた演出（ズーム・クリックの波紋・スポットライト・強調字幕・章カード・保存通知・早送り表示）を自動で付けます。

- **browser モード**: Playwright でブラウザ内を録画し、描画カーソルを重ねる。軽く、再現性が高い
- **desktop モード**: 仮想画面（Xvfb）全体を録画し、実カーソルで操作する。ダウンロードしたファイルを LibreOffice Calc で開く場面まで1本に撮れる

この構成は「デモ動画 撮影検証ロードマップ」の検証結果に基づいています（[docs/RESULTS.md](docs/RESULTS.md)）。

---

## 1. 動作要件

| 項目 | 要件 |
|---|---|
| OS | Ubuntu 22.04 / 24.04、Debian 12（x86_64）。他の Linux は依存パッケージを手動で入れれば動く |
| 権限 | sudo（apt と Chromium の依存ライブラリ導入に使う） |
| Python | 3.10 以上（OS 標準で可） |
| Docker | サンプルアプリと desktop モードを使う場合。Docker Engine 24 以上と compose v2 プラグイン |
| メモリ | browser モード 2GB 以上、desktop モード 4GB 以上（実測ピーク 約1.1GB） |
| ディスク | browser モード 約1GB、desktop モードは録画イメージ分 約4.5GB 追加 |
| ネットワーク | 導入時のみ（apt・PyPI・Playwright の CDN・Docker Hub / mcr.microsoft.com） |

撮影対象のアプリは、操作する要素に **`data-testid` が付いていること**が条件です。

**確認済みの範囲**（2026-09-27）:
- Ubuntu 24.04 の新規環境で、sudo 権限の一般ユーザーとして `install.sh` → `verify.sh` を実行。browser モードの2シーンが判定まで合格
- desktop モードの録画イメージをホストの uid（1000）で実行し、Calc 表示まで含めて判定合格
- Python 3.10（Ubuntu 22.04 相当）での構文とシーン検証
- 1.1.0 の演出（合成エンジン）を Ubuntu 24.04 で `install.sh` → `verify.sh` まで確認。フォントは Noto Sans CJK を自動で使用、30 秒の動画の合成に約 22 秒
- Debian 12、および実機の Linux ホストから Docker を直接叩く desktop モード（`install.sh --desktop` → `verify.sh --desktop`）は未確認

## 2. 同梱物

```
demo-video-kit/
├── install.sh                 導入スクリプト
├── verify.sh                  動作確認（サンプルアプリで撮影〜判定まで）
├── bin/demo                   実行ラッパー（bin/demo make ... の形で使う）
├── requirements.txt           Python 依存
├── demo/                      ツール本体（ランナー・後工程・判定・自己確認ループ）
│   └── scene.schema.json      シーン YAML のスキーマ
├── recorder/Dockerfile        desktop モード用の録画イメージ
├── scenes/                    シーン定義のサンプル
│   ├── _template.yaml         全項目の説明付きひな形
│   ├── core_audit.yaml        アップロード→実行→結果→ダウンロード（browser）
│   ├── core_audit_desktop.yaml 同上＋Excel を Calc で開く（desktop）
│   └── policy_qa.yaml         文章入力→回答表示（browser）
├── sample-app/                動作確認用の対象アプリ（Docker、localhost:8080）
├── .claude/skills/demo-video/ Claude Code 用スキル
└── docs/RESULTS.md            検証結果
```

## 3. 導入手順

### 3.1 展開と導入

```bash
unzip demo-video-kit.zip
cd demo-video-kit
./install.sh --all        # browser モード + サンプルアプリ + desktop モード
```

用途に合わせて選べます。

| コマンド | 入るもの |
|---|---|
| `./install.sh` | Python 仮想環境（.venv）、Chromium、ffmpeg、日本語フォント |
| `./install.sh --sample` | 上に加えてサンプルアプリを起動（http://localhost:8080） |
| `./install.sh --desktop` | 上に加えて desktop モード用の録画イメージ（`demo-recorder:latest`）を作成 |
| `./install.sh --all` | 全部 |

スクリプトは何度実行しても問題ありません。Docker を sudo なしで使うには、先にユーザーを docker グループに入れてください（`sudo usermod -aG docker $USER` のあと再ログイン）。

### 3.2 動作確認

```bash
./verify.sh              # browser モード（2シーン）
./verify.sh --desktop    # desktop モードも（3シーン）
```

`out/<シーンID>/run/build/final.mp4` ができれば導入は成功です。所要は browser 1シーン 約40秒、desktop 約1分です。

### 3.3 手動で導入する場合（apt が使えない環境）

1. ffmpeg（libass と libx264 入り）、日本語フォント（Noto Sans CJK）、Python 3.10 以上を入れる
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. `sudo .venv/bin/python -m playwright install-deps chromium`（ディストリ非対応なら Chromium の依存ライブラリを手動で）
4. `.venv/bin/python -m playwright install chromium`
5. desktop モードを使うなら `docker build -t demo-recorder:latest recorder/`
6. `./install.sh --skip-apt` で残りの確認だけ行える

## 4. 使い方

### 4.1 コマンド

どのフォルダからでも `bin/demo` で呼べます。シーンと出力（`out/`）はカレントフォルダ基準です。
`export PATH="$PWD/bin:$PATH"` しておくと `demo make ...` で使えます。

| やること | コマンド | 出力 |
|---|---|---|
| セレクタ確認（録画なし・数秒） | `bin/demo dryrun scenes/x.yaml` | 失敗したステップ |
| 録画だけ | `bin/demo record scenes/x.yaml` | `out/x/run/raw.*`, `events.json` |
| 後工程だけ | `bin/demo build out/x/run` | `build/final.mp4` ほか |
| 判定だけ | `bin/demo review out/x/run` | `review.json` |
| 録画→後工程→判定 | `bin/demo make scenes/x.yaml` | 上の全部。合格なら終了コード 0 |
| 合格まで自動で直す | `bin/demo loop scenes/x.yaml` | `out/x/loop/iterN/`（review.json と YAML の差分） |
| 再現性の確認 | `bin/demo repro scenes/x.yaml -n 3` | `out/x/repro/repro.json` |

`loop` はシーン YAML を直接書き換えます（コメントと書式は保ちます）。`--fixer claude` を付けると修正を Claude Code（`claude -p`、要ログイン）に任せます。

### 4.2 出力物

| ファイル | 内容 |
|---|---|
| `build/final.mp4` | 完成動画（1920x1080、30fps、H.264、演出・字幕入り、章メタデータ付き） |
| `build/subtitles.srt` | 字幕（焼き込みなしで使いたいとき用） |
| `build/chapters.json` | 章（タイトルと開始・終了秒） |
| `build/build.json` | 後工程の記録（早送り区間、演出ごとの数、合成にかかった秒数） |
| `raw.webm` / `raw.mp4` | 加工前の録画 |
| `events.json` | 操作ログ（各ステップの時刻・対象・字幕） |
| `review.json` | 判定結果と、不合格時の直し方の手掛かり |
| `downloads/` | 撮影中にダウンロードされたファイル |

### 4.3 自分のアプリを撮る

1. アプリを起動し、ブラウザで `http://localhost:<port>` が開けることを確認する
2. 操作する要素の `data-testid` を確認する（ブラウザの開発者ツールなど）
3. `scenes/_template.yaml` をコピーして `scenes/<id>.yaml` を書く
4. `bin/demo dryrun scenes/<id>.yaml` で全ステップが通るか確認する
5. `bin/demo loop scenes/<id>.yaml` で合格まで回す

シーン YAML の全項目は `scenes/_template.yaml` のコメントと `demo/scene.schema.json` にあります。

### 4.4 演出（字幕・効果・強調）

後工程（`build`）が操作ログを読み、ステップの種類に応じて演出を自動で重ねます。演出は録画に焼き込まないため、YAML を直して `bin/demo build out/<id>/run` を実行すれば撮り直さずに作り直せます。

| 場面 | カメラ | 自動で付く演出 |
|---|---|---|
| 冒頭 | 全体（ぼかし） | タイトルカード（シーンの `title` と章の流れ） |
| `chapter` | 全体 | 章カード（STEP n / N、題名、説明、進捗バー） |
| `click` / `upload` / `type` | 対象へ寄る | クリック位置から広がる波紋 |
| `wait_for` | 全体へ引く | 処理待ちを早送りし「早送り ×4」を表示、完了時に対象を光らせる |
| `hover` | 対象全体が収まる程度 | スポットライト（周囲を暗くし枠で囲む）、任意で吹き出し |
| `download` | 対象へ寄る | 波紋と「〇〇.xlsx を保存しました」の通知 |
| `open_download`（desktop） | 全体→データ範囲へ寄る | 実カーソルでセルをなぞる |
| 末尾 | 全体（ぼかし） | まとめカード（章の一覧にチェック） |

**字幕**は左に現在の章名ラベル、本文は強調語を強調色の太字で出します。

- `**語**` で囲んだ部分を強調する（例: `caption: "**ボタン1つ**で監査が始まります"`）
- 囲みが無い字幕は、数値＋単位（`8件`、`1,850,000円`、`100万円` など）を自動で強調する
- 下に出すと操作対象と重なるときだけ、画面上部に出す
- `subtitles.srt` には強調記号を外した文字が入る

**全体の設定**はシーンの `style:` で、**ステップごとの上書き**は `effect:` で行います。

```yaml
style:
  effects: rich          # simple にすると従来の焼き込み字幕だけになる
  accent: "#FFB020"      # 強調色
  max_zoom: 1.6          # カメラの最大拡大率
  caption_label: true    # 字幕の章名ラベル
  speed_badge: true      # 早送り表示
  intro: {subtitle: 3分でわかる監査エージェント}   # false で無し
  outro: {text: 詳しくは担当まで}                   # false で無し

steps:
  - hover:
      testid: findings-table
      effect: {callout: 指摘 6件}          # 吹き出しを足す
  - click:
      testid: run-button
      effect: {zoom: false, ripple: false}  # 寄らない・波紋なし
```

`effect` で指定できるもの: `zoom`（focus / fit / out / 数値 / false）、`ripple`、`spotlight`、`callout`、`pulse`、`toast`。
合成は 1080p で動画の長さとほぼ同じ時間がかかります（30 秒の動画で約 30 秒）。

### 4.5 desktop モードとネットワーク

desktop モード（`mode: desktop`）は録画コンテナの中からアプリに `http://localhost:<port>` でつなぎます。つなぎ方は環境変数で選びます。

| 状況 | 設定 |
|---|---|
| アプリが Docker コンテナで動いている | `export DEMO_APP_CONTAINER=<コンテナ名>`（既定 `audit-demo-app`）。そのコンテナのネットワークに相乗りする |
| アプリがホスト上で直接動いている／複数コンテナ | `export DEMO_NETWORK=host` |
| 録画イメージの名前を変えた | `export DEMO_RECORDER_IMAGE=<イメージ名>` |

録画コンテナはホストのユーザー ID で動くため、`out/` のファイルは自分の所有になります。
録画イメージには x11vnc と noVNC を入れてあります（`demo.desktop --vnc`）が、撮影中の目視は未検証です。

### 4.6 browser と desktop の使い分け

- ブラウザ内で完結する場面は browser。ホストの Chromium だけで動き、3回撮って同じ動画になる
- ダウンロードしたファイルを開いて見せる場面だけ desktop
- 1本の動画の中では方式を混ぜない（カーソルの見た目が変わるため）

## 5. Claude Code から使う

`.claude/skills/demo-video/` はプロジェクトスキルです。このフォルダで Claude Code を起動すると「デモ動画を撮って」「このシーンを合格するまで直して」などで使われます。
別のリポジトリで使うときは、そのリポジトリの `.claude/skills/` にフォルダごとコピーし、`bin/demo` を PATH に通してください。

## 6. トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| `dryrun` で `Timeout ... get_by_test_id` | その `data-testid` が画面にない。アプリ側の属性名を確認する |
| ファイル選択ボタンが英語 | フル版 Chromium でなく headless shell で動いている。`.venv/bin/python -m playwright install chromium` をやり直す |
| 字幕が豆腐（□）になる | 日本語フォントがない。`sudo apt install fonts-noto-cjk` |
| `日本語フォントが見つかりません` | 同上。別のフォントを使うときは `DEMO_FONT` / `DEMO_FONT_BOLD` にファイルを指定 |
| 合成が遅い | `DEMO_X264_PRESET=veryfast` でエンコードを速くできる（画質はわずかに下がる） |
| `ffmpeg に subtitles フィルタがありません` | libass なしの ffmpeg。ディストリ標準の ffmpeg を使う |
| 判定 `steps` が不合格（overrun） | アプリの処理が `wait_for.duration` より長い。`bin/demo loop` で自動で伸ばせる |
| 判定 `freeze` が不合格 | 見せ場の `hold` が長すぎる。3 秒以内を目安に。`loop` で自動で縮められる |
| desktop で `同期マーカーが見つかりません` | アプリに届いていない。`DEMO_APP_CONTAINER` / `DEMO_NETWORK` を確認する |
| desktop で `permission denied`（out/） | 以前 root で作られた `out/` が残っている。`sudo rm -rf out` |
| `docker: permission denied` | docker グループに入っていない。`sudo usermod -aG docker $USER` のあと再ログイン |

## 7. アンインストール

```bash
docker compose -f sample-app/compose.yaml down --rmi local   # サンプルアプリ
docker rmi demo-recorder:latest                               # 録画イメージ
rm -rf .venv out ~/.cache/ms-playwright                       # 仮想環境・出力・Chromium
```

apt で入れた ffmpeg・フォント・Chromium 依存ライブラリは他でも使われうるため残します。
