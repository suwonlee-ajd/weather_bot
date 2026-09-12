"""보존 기간이 지난 산출물·로그를 지운다.

    bin/cleanup.py                설정대로 정리
    bin/cleanup.py --dry-run      지우지 않고 대상만 보여준다
    bin/cleanup.py --days 30      data/ 의 보존 기간을 덮어쓴다 (로그는 그대로)
    bin/cleanup.py --days 30 --include-logs   로그까지 함께 덮어쓴다

평소에는 부를 일이 없다. 주간 게시가 dry-run 으로 돌 때 data/ 를 스스로
치우고, logs/ 는 loguru 가 회전하며 치운다. 이 스크립트가 필요한 때는 —

  * 봇을 한참 안 돌려 정리가 밀렸을 때
  * 보존 기간을 줄인 직후, 다음 실행을 기다리지 않고 바로 반영하고 싶을 때
  * cron 이나 systemd timer 로 정리만 따로 돌리고 싶을 때

지우기 전에 무엇이 지워지는지 보려면 --dry-run 을 먼저 쓴다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.logsetup import RETENTION_DAYS, log_dir, setup  # noqa: E402
from src.retention import prune_empty_dirs, sweep  # noqa: E402


def _int_env(key: str, default: int) -> int:
    """빈 값·오타를 기본값으로 되돌린다 — 정리 도구가 숫자 파싱으로 죽으면 안 된다."""
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

    # 정리 중 발생한 OSError 가 로그 파일에도 남아야 한다. retention 모듈은 표준
    # logging 을 쓰므로 브리지를 깔지 않으면 경고가 어디에도 남지 않는다.
    setup("cleanup")

    # Config 는 슬랙 토큰을 필수로 요구한다. 정리에 토큰이 필요할 이유가 없으므로
    # 환경변수를 직접 읽되, 이름과 기본값은 config.py 와 같게 맞춘다.
    data_root = Path(os.environ.get("DATA_DIR") or "data")
    if not data_root.is_absolute():
        data_root = ROOT / data_root

    # pattern 으로 좁히는 이유는 data/ 와 logs/ 가 사용자도 열어 보는 자리라서
    # 우리가 만들지 않은 파일까지 지우면 안 되기 때문이다. 같은 디렉터리를
    # 패턴만 달리해 두 번 훑는다 — 카드와 일기도는 보존 기간이 다르다.
    chart_product = os.environ.get("CHART_PRODUCT") or "surf"
    img_root = data_root / (os.environ.get("IMG_DIR") or "img")
    data_targets = [
        (img_root, _int_env("CARD_KEEP_DAYS", 14), False, "weekly-weather-*.png"),
        (img_root, _int_env("CHART_KEEP_DAYS", 30), False, f"{chart_product}_*.png"),
    ]
    # 로그 보존 기본값은 logsetup 이 loguru 에 넘기는 값과 같은 숫자에서 온다.
    # loguru 가 회전시킨 파일은 .log 와 .log.gz 두 꼴이다.
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

        # 한 번만 훑는다. 두 번 돌면 그 사이 회전된 파일이 집계에서 빠져
        # «지운 용량» 이 실제보다 작게 나온다.
        victims = sweep(path, keep_days, pattern=pattern,
                        recursive=recursive, dry_run=args.dry_run)
        freed = sum(size for _, size in victims)
        if not args.dry_run and victims:
            prune_empty_dirs(path)

        total_n += len(victims)
        total_bytes += freed
        mark = "지울 것" if args.dry_run else "지움"
        # 같은 디렉터리가 패턴만 달리해 두 번 나오므로 패턴을 함께 찍는다
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
