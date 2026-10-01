#!/bin/bash
# 날씨 봇을 끈다.
#
#   bin/stop.sh               전부 — 멘션 봇과 타이머(주간 게시 · 정리)
#   bin/stop.sh mention       멘션 봇만
#   bin/stop.sh timers        타이머만 — 이번 주 게시를 건너뛸 때
#
# systemd 유닛이 등록된 서버면 그 유닛을 끄고, 없으면 bin/start.sh 가 직접 띄운 봇을 끈다.
# 유닛은 끄기만 하고 disable 하지 않는다 — 재부팅하면 enable 된 유닛은 다시 켜진다.
# 아예 끄려면: systemctl --user disable --now <유닛>  (root 서버는 sudo systemctl)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=bin/_service.sh
. "$ROOT/bin/_service.sh"

target=all
for arg in "$@"; do
  case "$arg" in
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) target="$arg" ;;
  esac
done

detect_mode
units_for "$target"

if [[ "$MODE" == direct ]]; then
  wants_mention && direct_stop
else
  for unit in "${UNITS[@]}"; do
    "${SCTL[@]}" stop "$unit"
    echo "  $unit — 끔"
  done
fi

stray=$(stray_mentions)
if [[ -n "$stray" ]] && wants_mention; then
  echo "참고: 이 스크립트 밖에서 띄운 멘션 봇이 아직 떠 있습니다 (PID $(echo $stray)). 그대로 둡니다." >&2
fi

show_status
