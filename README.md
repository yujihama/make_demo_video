# デモ動画キット（demo-video-kit）

localhost で動く Web アプリのデモ動画を、YAML のシーン定義から撮影・編集・自己確認するツール一式です。
同じ YAML からは何度撮っても同じ動画になります。字幕・章・待ち時間の早送りは自動で付きます。

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
| `build/final.mp4` | 完成動画（1920x1080、30fps、H.264、字幕焼き込み、章メタデータ付き） |
| `build/subtitles.srt` | 字幕（焼き込みなしで使いたいとき用） |
| `build/chapters.json` | 章（タイトルと開始・終了秒） |
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

### 4.4 desktop モードとネットワーク

desktop モード（`mode: desktop`）は録画コンテナの中からアプリに `http://localhost:<port>` でつなぎます。つなぎ方は環境変数で選びます。

| 状況 | 設定 |
|---|---|
| アプリが Docker コンテナで動いている | `export DEMO_APP_CONTAINER=<コンテナ名>`（既定 `audit-demo-app`）。そのコンテナのネットワークに相乗りする |
| アプリがホスト上で直接動いている／複数コンテナ | `export DEMO_NETWORK=host` |
| 録画イメージの名前を変えた | `export DEMO_RECORDER_IMAGE=<イメージ名>` |

録画コンテナはホストのユーザー ID で動くため、`out/` のファイルは自分の所有になります。
録画イメージには x11vnc と noVNC を入れてあります（`demo.desktop --vnc`）が、撮影中の目視は未検証です。

### 4.5 browser と desktop の使い分け

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
