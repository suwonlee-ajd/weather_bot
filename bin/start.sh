#!/bin/bash
# 날씨 봇을 켠다 — 멘션 봇(상시)과 타이머(주간 게시 · 정리).
#
#   bin/start.sh              전부
#   bin/start.sh mention      멘션 봇만
#   bin/start.sh timers       타이머만
#   bin/start.sh -r           이미 떠 있는 멘션 봇도 다시 띄운다 — 코드를 갱신한 뒤 반영할 때
#
# systemd 유닛이 등록된 서버면 그 유닛을 켜고, 없으면 멘션 봇을 백그라운드로 직접 띄운다
# (bin/_service.sh). 직접 띄운 봇은 죽어도 되살아나지 않고, 타이머도 없다.
# disable 해 둔 타이머는 켜지 않는다 — 주간 게시를 GitHub Actions 가 맡는 서버에서
# weather-weekly.timer 까지 켜면 같은 주에 두 번 올라간다(deploy/DEPLOY.md §4).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=bin/_service.sh
. "$ROOT/bin/_service.sh"

restart=false
target=all
for arg in "$@"; do
  case "$arg" in
    -r|--restart) restart=true ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) target="$arg" ;;
  esac
done

detect_mode
units_for "$target"

stray=$(stray_mentions)
if [[ -n "$stray" ]]; then
  echo "경고: 이 스크립트 밖에서 띄운 멘션 봇이 있습니다 (PID $(echo $stray)). 한 멘션에 두 번 답하게 되니 먼저 끄세요." >&2
fi

if [[ "$MODE" == direct ]]; then
  wants_mention && direct_start
  show_status
  exit 0
fi

for unit in "${UNITS[@]}"; do
  if [[ "$unit" == *.timer ]] && ! "${SCTL[@]}" is-enabled --quiet "$unit"; then
    echo "  $unit — disable 상태라 켜지 않습니다"
    continue
  fi
  if $restart && [[ "$unit" == *.service ]]; then
    "${SCTL[@]}" restart "$unit"
    echo "  $unit — 다시 띄움"
  else
    "${SCTL[@]}" start "$unit"
    echo "  $unit — 켬"
  fi
done

# 멘션 봇은 떠 있다가 곧바로 죽을 수 있다(.env 누락, venv 경로). 잠깐 지켜본다.
if wants_mention; then
  sleep 3
  if ! "${SCTL[@]}" is-active --quiet "$MENTION_UNIT"; then
    echo "멘션 봇이 떠 있지 않습니다. 최근 기록:" >&2
    "${JCTL[@]}" -u "$MENTION_UNIT" -n 20 --no-pager >&2 || true
    exit 1
  fi
fi

show_status
