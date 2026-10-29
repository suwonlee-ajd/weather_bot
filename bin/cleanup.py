#!/usr/bin/env python3
"""보존 기간이 지난 산출물·로그를 지움.

    bin/cleanup.py [--dry-run] [--days 30 [--include-logs]]

평소에는 weather-cleanup.timer(매일 04:00)가 부름 — 한 번 돌고 끝나는 실행의 로그는 loguru 가 회전하지 않음.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# .venv 밖에서 불렸으면 .venv 파이썬으로 다시 띄움 — loguru 가 거기에만 있음
_VENV = ROOT / ".venv"
if (_VENV / "bin" / "python").exists() and Path(sys.prefix).resolve() != _VENV.resolve():
    os.execv(_VENV / "bin" / "python", [str(_VENV / "bin" / "python"), __file__, *sys.argv[1:]])
sys.path.insert(0, str(ROOT))

from src.common.logsetup import RETENTION_DAYS, log_dir, setup  # noqa: E402
from src.common.retention import prune_empty_dirs, sweep  # noqa: E402


def _int_env(key: str, default: int) -> int:
    raw = os.environ.get(key, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        print(f"  경고: {key}={raw!r} 를 숫자로 읽을 수 없어 기본값 {default} 을 씁니다")
        return default


def human(size: float) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:,.0f}{unit}"
        size /= 1024.0
    return f"{size:,.1f}GB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="지우지 않고 대상만 보여준다")
    parser.add_argument("--days", type=int, default=None,
                        help="data/ 의 보존 기간을 덮어쓴다. 로그는 --include-logs 를 함께 줘야 한다")
    parser.add_argument("--include-logs", action="store_true",
                        help="--days 를 로그에도 적용한다 (로그는 디버깅 기록이라 기본은 보호)")
    args = parser.parse_args(argv)

    # retention 은 표준 logging 을 씀 — 브리지가 없으면 정리 경고가 어디에도 남지 않음
    setup("cleanup")

    # Config 는 슬랙 토큰을 요구해 환경변수를 직접 읽음 — 이름·기본값은 config.py 와 같게
    data_root = Path(os.environ.get("DATA_DIR") or "data")
    if not data_root.is_absolute():
        data_root = ROOT / data_root

    # 우리가 만든 파일만 패턴으로 좁힘 — 같은 디렉터리라도 카드·일기도는 보존 기간이 다름
    chart_product = os.environ.get("CHART_PRODUCT") or "surf"
    img_root = data_root / (os.environ.get("IMG_DIR") or "img")
    data_targets = [
        (img_root, _int_env("CARD_KEEP_DAYS", 14), False, "weekly-weather-*.png"),
        (img_root, _int_env("CHART_KEEP_DAYS", 30), False, f"{chart_product}_*.png"),
        # 단풍·첫눈 지도는 카드처럼 언제든 다시 만들 수 있음
        (img_root, _int_env("CARD_KEEP_DAYS", 14), False, "foliage-*.png"),
        (img_root, _int_env("CARD_KEEP_DAYS", 14), False, "snow-*.png"),
    ]
    # *.log* — loguru 가 남기는 .log 와 압축된 .log.gz 를 함께 잡음
    log_target = (log_dir(), _int_env("LOG_KEEP_DAYS", RETENTION_DAYS), True, "*.log*")

    if args.days is not None:
        data_targets = [(p, args.days, r, pat) for p, _, r, pat in data_targets]
        if args.include_logs:
            log_target = (log_target[0], args.days, log_target[2], log_target[3])

    total_n = total_bytes = 0
    for path, keep_days, recursive, pattern in [*data_targets, log_target]:
        if not path.is_dir():
            print(f"  {path} — 없음")
            continue
        if keep_days <= 0:
            print(f"  {path} — 보존 기간 없음(0), 건너뜀")
            continue

        # 한 번만 훑음 — 두 번 돌면 그 사이 회전된 파일이 빠져 «지운 용량» 이 작게 나옴
        victims = sweep(path, keep_days, pattern=pattern,
                        recursive=recursive, dry_run=args.dry_run)
        freed = sum(size for _, size in victims)
        if not args.dry_run and victims:
            prune_empty_dirs(path)

        total_n += len(victims)
        total_bytes += freed
        mark = "지울 것" if args.dry_run else "지움"
        print(f"  {path}/{pattern} ({keep_days}일) — {mark} {len(victims)}개 {human(freed)}")
        for p, _ in victims[:5]:
            print(f"      {p.relative_to(path)}")
        if len(victims) > 5:
            print(f"      … 외 {len(victims) - 5}개")

    verb = "지울 수 있음" if args.dry_run else "정리 완료"
    print(f"\n{verb}: {total_n}개 {human(total_bytes)}")
    if args.dry_run and total_n:
        print("실제로 지우려면 --dry-run 없이 다시 실행하세요.")
    if args.days is not None and not args.include_logs:
        print("로그는 --days 의 영향을 받지 않았습니다 (--include-logs 로 포함).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
