#!/bin/bash
# 주간 게시 진입점 — 월요일 아침에 한 번 돌고 끝난다(oneshot).
# systemd timer(weather-weekly.timer)가 부른다.
#
# 짝이 되는 run-mention.sh 와는 마지막 줄(실행 모듈)만 다르다:
#   run-weekly.sh   src.post     예약 게시 · 끝나면 종료
#   run-mention.sh  src.mention  멘션 응답 · 24시간 상시
#
# .env 를 읽어 환경변수로 올린 뒤 실행한다 — 비밀값을 유닛 파일에
# 복사해 두지 않으려고 이렇게 한 겹 둔다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=deploy/_env.sh
. "$ROOT/deploy/_env.sh"
load_env "$ROOT/.env"

export TZ=Asia/Seoul
exec "$ROOT/.venv/bin/python" -m src.post "$@"
