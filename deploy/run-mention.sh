#!/bin/bash
# 멘션 봇 진입점. run.sh 와 같은 모양으로, .env 를 올린 뒤 포그라운드로 실행한다.
#
# 프로세스 수명은 이 스크립트가 관리하지 않는다 — 서버는 systemd
# (deploy/weather-mention.service). 로컬 확인은 이 스크립트를 직접 실행한다.
# 가 맡는다. 로컬에서 잠깐 볼 때는 그냥 실행하고 Ctrl-C 로 끄면 된다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=deploy/_env.sh
. "$ROOT/deploy/_env.sh"
load_env "$ROOT/.env"

export TZ=Asia/Seoul
exec "$ROOT/.venv/bin/python" -u -m src.mention "$@"
