#!/usr/bin/env bash
# 動作確認: サンプルアプリに対して セレクタ確認 → 撮影 → 後工程 → 判定 を通す。
#   ./verify.sh            browser モード（Core シーン・規程Q&A）
#   ./verify.sh --desktop  加えて desktop モード（ブラウザ＋Calc）
# 完成動画ができれば導入は成功。判定（review）が不合格でも、原因は表示して導入の失敗とは扱わない。
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
DESKTOP=0
[[ "${1:-}" == "--desktop" ]] && DESKTOP=1
APP_URL="${APP_URL:-http://localhost:8080}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }

curl -fsS "$APP_URL/health" >/dev/null 2>&1 || {
  red "サンプルアプリが応答しません（$APP_URL）。./install.sh --sample を実行してください"
  exit 1
}

scenes=(scenes/core_audit.yaml scenes/policy_qa.yaml)
[[ $DESKTOP == 1 ]] && scenes+=(scenes/core_audit_desktop.yaml)

echo "== dryrun（録画なしでセレクタを確認）"
bin/demo dryrun scenes/core_audit.yaml || { red "dryrun に失敗しました"; exit 1; }

failed=0
for s in "${scenes[@]}"; do
  id=$(basename "$s" .yaml)
  echo; echo "== make $s"
  langs=""
  [[ "$id" == "core_audit" ]] && langs="--lang ja,en"   # 多言語版（英語）も確認する
  bin/demo make "$s" $langs 2>&1 | grep -vE '^\s*\[|xkbcomp|keysym|^>'
  code=${PIPESTATUS[0]}
  final="out/$id/run/build/final.mp4"
  if [[ -s "$final" ]]; then
    if [[ $code == 0 ]]; then green "   OK  $final（判定 合格）"; else
      green "   OK  $final（撮影・後工程は成功）"
      echo "       判定は不合格: out/$id/run/review*.json を確認。bin/demo loop $s $langs で自動修正できます"
    fi
    [[ -n "$langs" && -s "out/$id/run/build-en/final.mp4" ]] && green "   OK  out/$id/run/build-en/final.mp4（英語版）"
  else
    red "   NG  $s の完成動画ができませんでした"; failed=1
  fi
done

if [[ $failed == 0 ]]; then
  echo; echo "== program demos/audit_agent.yaml（通し版）"
  if bin/demo program demos/audit_agent.yaml --lang ja,en && [[ -s out/audit_agent/program/audit_agent_ja/audit_agent_ja.mp4 ]]; then
    green "   OK  out/audit_agent/program/audit_agent_ja.zip（通し版 mp4 ＋ player.html）"
    green "   OK  out/audit_agent/program/audit_agent_en.zip（英語版）"
  else
    red "   NG  通し版を作れませんでした"; failed=1
  fi
fi

echo
if [[ $failed == 0 ]]; then green "動作確認が完了しました。完成動画は out/<シーンID>/run/build/final.mp4 です"; else red "失敗したシーンがあります"; fi
exit $failed
