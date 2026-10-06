#!/bin/bash
# start.sh · stop.sh 공용 — 멘션 봇과 타이머를 켜고 끈다.
#
# 두 방식 가운데 그 서버에 맞는 쪽을 쓴다.
#   systemd  유닛이 등록돼 있으면(deploy/DEPLOY.md §3) 그 유닛을 켜고 끈다.
#            권한 없는 서버는 systemd --user, root 서버는 시스템 유닛이다.
#   직접     유닛이 없으면 멘션 봇을 백그라운드 프로세스로 띄우고 PID 파일로 끈다.
#            죽어도 되살리지 않고, 주간 게시·정리 예약도 없다 — 타이머가 하던 일이다.
#
# 부르는 쪽이 ROOT 를 먼저 정해 둔다.

MENTION_UNIT=weather-mention.service
TIMER_UNITS=(weather-weekly.timer weather-cleanup.timer)
PIDFILE="$ROOT/data/mention.pid"
# 직접 띄울 때의 콘솔 출력 — 파이썬이 뜨기도 전에 죽은 경우(.env·venv)를 보는 용도다.
# 앱 로그는 logs/{연}/… 에 따로 쌓인다. 띄울 때마다 비운다.
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

# 대상 이름 → UNITS 배열
units_for() {
  case "${1:-all}" in
    mention) UNITS=("$MENTION_UNIT") ;;
    timers)  UNITS=("${TIMER_UNITS[@]}") ;;
    all)     UNITS=("$MENTION_UNIT" "${TIMER_UNITS[@]}") ;;
    *) echo "대상은 mention · timers · all 가운데 하나입니다: $1" >&2; exit 2 ;;
  esac
}

wants_mention() { [[ " ${UNITS[*]} " == *" $MENTION_UNIT "* ]]; }

# 직접 띄운 멘션 봇의 PID. 떠 있지 않으면 실패를 돌려준다(PID 파일이 낡았어도).
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
  # $! 가 곧 봇의 PID 다 — run-mention.sh 가 exec 으로 파이썬이 된다
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

# 이 스크립트가 관리하지 않는 멘션 봇. 같은 슬랙 앱에 두 연결이 붙으면 한 멘션에 두 번 답한다.
stray_mentions() {
  local own=0
  if [[ "$MODE" == systemd ]]; then
    own=$("${SCTL[@]}" show -p MainPID --value "$MENTION_UNIT" 2>/dev/null || echo 0)
  else
    own=$(direct_pid || echo 0)
  fi
  # 파이썬으로 시작하는 명령줄만 — 셸·편집기 명령줄에 이 글자가 들어 있어도 봇으로 치지 않는다
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
