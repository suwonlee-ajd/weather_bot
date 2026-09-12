#!/bin/bash
# systemd timer 에서 부르는 진입점. .env 를 읽어 환경변수로 올린 뒤 봇을 실행한다.
# 비밀값을 유닛 파일에 복사해 두지 않으려고 이렇게 한 겹 둔다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=deploy/_env.sh
. "$ROOT/deploy/_env.sh"
load_env "$ROOT/.env"

export TZ=Asia/Seoul
exec "$ROOT/.venv/bin/python" -m src.post "$@"
