#!/bin/bash
# 멘션 응답 진입점 — 24시간 상시 실행(Socket Mode).
# 서버에서는 systemd(weather-mention.service)가 띄우고, 죽으면 되살린다.
#
# 짝이 되는 run-weekly.sh 와는 마지막 줄(실행 모듈)만 다르다:
#   run-weekly.sh   src.post     예약 게시 · 끝나면 종료
#   run-mention.sh  src.mention  멘션 응답 · 24시간 상시
#
# python 에 -u 를 붙이는 이유 — 상시 프로세스라 출력이 journal 로 갈 때
# 블록 버퍼링되면 로그가 한참 뒤에야 보인다. 실시간으로 봐야 하므로 끈다.
#
# 로컬에서 잠깐 볼 때는 그냥 실행하고 Ctrl-C 로 끄면 된다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=deploy/_env.sh
. "$ROOT/deploy/_env.sh"
load_env "$ROOT/.env"

export TZ=Asia/Seoul
exec "$ROOT/.venv/bin/python" -u -m src.mention "$@"
