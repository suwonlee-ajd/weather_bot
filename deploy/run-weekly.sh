#!/bin/bash
# 주간 게시 진입점 — 월요일 아침 한 번 돌고 끝남. weather-weekly.timer 가 부름.
# .env 를 여기서 읽어 비밀값을 유닛 파일에 복사하지 않음.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=deploy/_env.sh
. "$ROOT/deploy/_env.sh"
load_env "$ROOT/.env"

export TZ=Asia/Seoul
exec "$ROOT/.venv/bin/python" -m src.weekly "$@"
