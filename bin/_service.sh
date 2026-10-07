#!/bin/bash
# start.sh · stop.sh 공용 — 멘션 봇과 타이머를 켜고 끔. 부르는 쪽이 ROOT 를 먼저 정함.
#   systemd  유닛이 등록돼 있으면 그 유닛(--user, root 서버는 시스템 유닛). deploy/DEPLOY.md §3
#   직접     유닛이 없으면 멘션 봇만 백그라운드로 띄우고 PID 파일로 끔 — 되살림·예약 없음

MENTION_UNIT=weather-mention.service
TIMER_UNITS=(weather-weekly.timer weather-cleanup.timer)
PIDFILE="$ROOT/data/mention.pid"
# 직접 띄울 때의 콘솔 출력 — 파이썬이 뜨기 전 실패(.env·venv) 확인용, 띄울 때마다 비움
CONSOLE="$ROOT/logs/weather-mention.console.log"

detect_mode() {
  if systemctl --user cat "$MENTION_UNIT" >/dev/null 2>&1; then
    MODE=systemd; SCTL=(systemctl --user); JCTL=(journalctl --user)
  elif systemctl cat "$MENTION_UNIT" >/dev/null 2>&1; then
    MODE=systemd; SCTL=(sudo systemctl); JCTL=(sudo journalctl)
  else
    MODE=direct
  fi
}

units_for() {
  case "${1:-all}" in
    mention) UNITS=("$MENTION_UNIT") ;;
    timers)  UNITS=("${TIMER_UNITS[@]}") ;;
    all)     UNITS=("$MENTION_UNIT" "${TIMER_UNITS[@]}") ;;
    *) echo "대상은 mention · timers · all 가운데 하나입니다: $1" >&2; exit 2 ;;
  esac
}

wants_mention() { [[ " ${UNITS[*]} " == *" $MENTION_UNIT "* ]]; }

# 직접 띄운 멘션 봇의 PID — 떠 있지 않으면(낡은 PID 파일 포함) 실패
direct_pid() {
  local pid
  [[ -f "$PIDFILE" ]] || return 1
  pid=$(<"$PIDFILE")
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  ps -p "$pid" -o args= 2>/dev/null | grep -q 'src\.mention' || return 1
  echo "$pid"
}

direct_start() {
  local pid
  if pid=$(direct_pid); then
    if ! ${restart:-false}; then
      echo "  멘션 봇 — 이미 떠 있음 (PID $pid)"
      return 0
    fi
    direct_stop
  fi
  mkdir -p "$(dirname "$PIDFILE")" "$(dirname "$CONSOLE")"
  # run-mention.sh 가 exec 하므로 $! 가 곧 봇의 PID 임
  nohup "$ROOT/deploy/run-mention.sh" >"$CONSOLE" 2>&1 </dev/null &
  echo $! >"$PIDFILE"
  sleep 3
  if ! pid=$(direct_pid); then
    echo "멘션 봇이 떠 있지 않습니다. 콘솔 출력 ($CONSOLE):" >&2
    tail -n 20 "$CONSOLE" >&2 || true
    rm -f "$PIDFILE"
    exit 1
  fi
  echo "  멘션 봇 — 켬 (PID $pid)"
}

direct_stop() {
  local pid
  if ! pid=$(direct_pid); then
    rm -f "$PIDFILE"
    echo "  멘션 봇 — 떠 있지 않음"
    return 0
  fi
  kill "$pid"
  for _ in $(seq 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid"
  rm -f "$PIDFILE"
  echo "  멘션 봇 — 끔 (PID $pid)"
}

# 이 스크립트 밖에서 띄운 멘션 봇 — 같은 앱에 연결이 둘이면 한 멘션에 두 번 답함
stray_mentions() {
  local own=0
  if [[ "$MODE" == systemd ]]; then
    own=$("${SCTL[@]}" show -p MainPID --value "$MENTION_UNIT" 2>/dev/null || echo 0)
  else
    own=$(direct_pid || echo 0)
  fi
  # 파이썬 명령줄만 — 셸·편집기 명령줄에 든 같은 글자는 봇이 아님
  pgrep -f -- '^[^ ]*python[0-9.]* .*-m src\.mention' | grep -vx "${own:-0}" || true
}

show_status() {
  echo
  if [[ "$MODE" == direct ]]; then
    local pid
    if pid=$(direct_pid); then
      echo "  멘션 봇  떠 있음 (PID $pid) · 콘솔 $CONSOLE"
    else
      echo "  멘션 봇  꺼짐"
    fi
    echo "  타이머   systemd 유닛이 없어 주간 게시·정리는 예약되지 않습니다 (deploy/DEPLOY.md §3)"
    return 0
  fi
  local unit
  for unit in "$MENTION_UNIT" "${TIMER_UNITS[@]}"; do
    printf '  %-24s %-10s %s\n' "$unit" \
      "$("${SCTL[@]}" is-active "$unit" 2>/dev/null || true)" \
      "$("${SCTL[@]}" is-enabled "$unit" 2>/dev/null || true)"
  done
  echo
  "${SCTL[@]}" --no-pager list-timers 'weather-*' 2>/dev/null | sed -n '1,3p' || true
}
