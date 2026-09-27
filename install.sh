#!/usr/bin/env bash
# デモ動画キット 導入スクリプト
# 対象: Ubuntu 22.04 / 24.04、Debian 12（x86_64）
#
#   ./install.sh              browser モードに必要なものだけ入れる（Python 仮想環境・Chromium・ffmpeg・日本語フォント）
#   ./install.sh --sample     加えてサンプルアプリを Docker で起動する（http://localhost:8080）
#   ./install.sh --desktop    加えて desktop モード用の録画イメージを作る（約 4.5GB）
#   ./install.sh --all        上の全部
#
# 何度実行しても同じ状態になる（既にあるものは作り直さない）。
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
KIT_DIR="$(pwd)"
WITH_SAMPLE=0
WITH_DESKTOP=0
SKIP_APT=0
PYTHON="${PYTHON:-python3}"
RECORDER_IMAGE="${DEMO_RECORDER_IMAGE:-demo-recorder:latest}"

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

その他のオプション:
  --skip-apt        apt でのパッケージ導入を飛ばす（依存を手動で入れた場合）
  --python <path>   仮想環境を作る Python（既定 python3、3.10 以上）
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sample) WITH_SAMPLE=1 ;;
    --desktop) WITH_DESKTOP=1 ;;
    --all) WITH_SAMPLE=1; WITH_DESKTOP=1 ;;
    --skip-apt) SKIP_APT=1 ;;
    --python) PYTHON="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "不明なオプション: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

SUDO=""
if [[ $EUID -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; else [[ $SKIP_APT == 1 ]] || die "root で実行するか sudo を導入してください（または --skip-apt）"; fi
fi

# --- 1. OS -------------------------------------------------------------------
log "OS を確認"
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  ok "${PRETTY_NAME:-unknown}"
  case " ${ID:-} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*) ;;
    *) warn "Debian/Ubuntu 系ではないため apt 手順を飛ばします。README の「依存パッケージ」を手動で入れてください"; SKIP_APT=1 ;;
  esac
fi
[[ "$(uname -m)" == "x86_64" ]] || warn "x86_64 以外（$(uname -m)）は未検証です"

# --- 2. システムパッケージ ------------------------------------------------------
if [[ $SKIP_APT == 0 ]]; then
  log "システムパッケージを導入（python3-venv, ffmpeg, 日本語フォント）"
  $SUDO apt-get update -qq
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip ffmpeg fonts-noto-cjk fontconfig curl ca-certificates >/dev/null
  ok "apt パッケージ"
fi

# --- 3. Python 仮想環境 --------------------------------------------------------
log "Python 仮想環境を作成（.venv）"
command -v "$PYTHON" >/dev/null || die "$PYTHON が見つかりません"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python 3.10 以上が必要です（現在: $("$PYTHON" -V 2>&1)）。--python で指定できます"
[[ -x .venv/bin/python ]] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
ok "$(.venv/bin/python -V) / playwright $(.venv/bin/python -c 'import importlib.metadata as m; print(m.version("playwright"))')"

# --- 4. Chromium ---------------------------------------------------------------
log "Chromium を導入（Playwright 管理のフル版。ファイル選択ボタン等が日本語になる）"
if [[ $SKIP_APT == 0 ]]; then
  $SUDO "$KIT_DIR/.venv/bin/python" -m playwright install-deps chromium >/dev/null
  ok "Chromium の依存ライブラリ"
fi
.venv/bin/python -m playwright install chromium >/dev/null
ok "Chromium"

# --- 5. ffmpeg / フォント確認 -----------------------------------------------------
log "ffmpeg とフォントを確認"
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || die "ffmpeg / ffprobe がありません"
# grep -q は途中で読むのをやめ、pipefail 下では書き手側の SIGPIPE で失敗扱いになるため、先に変数へ受ける
FILTERS="$(ffmpeg -hide_banner -filters 2>/dev/null)"
ENCODERS="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
grep -q ' subtitles ' <<<"$FILTERS" || die "ffmpeg に subtitles フィルタ（libass）がありません"
grep -q libx264 <<<"$ENCODERS" || die "ffmpeg に libx264 がありません"
FFVER="$(ffmpeg -version 2>/dev/null)"
ok "${FFVER%%Copyright*}（libass・libx264 あり）"
if grep -qi "Noto Sans CJK" <<<"$(fc-list :lang=ja 2>/dev/null)"; then ok "Noto Sans CJK（字幕用）"; else warn "Noto Sans CJK が見つかりません。字幕が別フォントになります"; fi

chmod +x bin/demo verify.sh install.sh

# --- 6. Docker（サンプルアプリ・desktop モード） ------------------------------------
if [[ $WITH_SAMPLE == 1 || $WITH_DESKTOP == 1 ]]; then
  log "Docker を確認"
  command -v docker >/dev/null || die "Docker が必要です（https://docs.docker.com/engine/install/）"
  docker info >/dev/null 2>&1 || die "docker を実行できません。docker グループに追加するか、Docker デーモンを起動してください"
  ok "Docker $(docker version --format '{{.Server.Version}}')"
fi

if [[ $WITH_SAMPLE == 1 ]]; then
  log "サンプルアプリを起動（http://localhost:8080）"
  docker compose version >/dev/null 2>&1 || die "docker compose（v2 プラグイン）が必要です"
  docker compose -f sample-app/compose.yaml up -d --build --wait >/dev/null
  curl -fsS http://localhost:8080/health >/dev/null && ok "サンプルアプリ応答あり"
fi

if [[ $WITH_DESKTOP == 1 ]]; then
  log "desktop モード用の録画イメージを作成（$RECORDER_IMAGE、初回は 10 分ほど）"
  docker build -q -t "$RECORDER_IMAGE" recorder/ >/dev/null
  ok "$RECORDER_IMAGE（$(docker image inspect "$RECORDER_IMAGE" --format '{{.Size}}' | awk '{printf "%.1fGB", $1/1e9}')）"
fi

log "導入が完了しました"
cat <<EOF
  動作確認:      ./verify.sh            （サンプルアプリで撮影・後工程・判定まで）
                 ./verify.sh --desktop  （desktop モードも確認）
  撮影:          bin/demo make scenes/core_audit.yaml
  使い方:        README.md
EOF
