#!/bin/bash
# 멘션 응답 진입점 — 상시 실행(Socket Mode). weather-mention.service 가 띄우고 되살림.
# 로컬에서는 그냥 실행하고 Ctrl-C 로 끔.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=deploy/_env.sh
. "$ROOT/deploy/_env.sh"
load_env "$ROOT/.env"

export TZ=Asia/Seoul
# -u: 버퍼링을 꺼 journal 에 로그가 바로 남게 함
exec "$ROOT/.venv/bin/python" -u -m src.mention "$@"
