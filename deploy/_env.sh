#!/bin/bash
# .env 를 환경변수로 올리는 공용 로더 (run-weekly.sh · run-mention.sh).
# 이미 있는 값은 덮어쓰지 않음 — CI Secrets 가 이기고, 한 번만 바꿔 돌릴 수도 있음.
#   REGION=경남 ./deploy/run-weekly.sh --dry-run
# 단순 KEY=값 목록으로 읽음 — 따옴표 제거·변수 확장 없음.
load_env() {
  local envfile="${1:?load_env: .env 경로가 필요합니다}"
  [[ -f "$envfile" ]] || return 0
  local line key
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    key="${line%%=*}"; key="${key//[[:space:]]/}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -n "${!key:-}" ]] && continue
    export "$key=${line#*=}"
  done < "$envfile"
}
