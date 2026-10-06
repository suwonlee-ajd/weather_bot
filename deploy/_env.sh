#!/bin/bash
# .env 를 환경변수로 올리는 공용 로더. run-weekly.sh 와 run-mention.sh 가 함께 씀.
#
# 이미 환경에 있는 값은 .env 로 덮어쓰지 않음 — CI 에서는 Secrets 가 그대로 이기고,
# 아래처럼 한 번만 다르게 돌려볼 수도 있음.
#   REGION=경남 ./deploy/run-weekly.sh --dry-run
#
# 셸 파일이 아니라 단순 KEY=값 목록으로 다룸 — 따옴표 제거나 변수 확장을 하지 않음.
load_env() {
  local envfile="${1:?load_env: .env 경로가 필요합니다}"
  [[ -f "$envfile" ]] || return 0
  local line key
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    key="${line%%=*}"; key="${key//[[:space:]]/}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -n "${!key:-}" ]] && continue      # 이미 설정돼 있으면 유지
    export "$key=${line#*=}"
  done < "$envfile"
}
