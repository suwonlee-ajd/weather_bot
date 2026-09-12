"""이번 주 날씨를 사람이 읽을 형태로 출력하는 조회 CLI.

주간 게시 봇과 같은 수집 코드(src/kma_scrape.py)를 쓰되, 슬랙 게시 없이 결과만 찍는다.
Claude Code 스킬(.claude/skills/kma-weather)이 이 명령을 부른다.

    python -m src.query            # 이번 주 전국
    python -m src.query 부산        # 지역 지정
    python -m src.query --json     # 기계용 JSON
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

from .config import KST
from .forecast import WEEKDAY_KO, day_label, range_text
from .kma_scrape import REGION_HELP, ScrapeError, find_region, scrape_week

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="기상청 이번 주 예보 조회")
    parser.add_argument("region", nargs="?", default="전국", help=f"지역 ({REGION_HELP})")
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    parser.add_argument("--week-offset", type=int, default=0, help="0=이번 주, 1=다음 주")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    region = find_region(args.region)
    if region is None:
        print(f"알 수 없는 지역입니다: {args.region}\n쓸 수 있는 지역: {REGION_HELP}", file=sys.stderr)
        return 2

    now = dt.datetime.now(tz=KST)
    week_start = now.date() - dt.timedelta(days=now.weekday()) + dt.timedelta(weeks=args.week_offset)

    try:
        scrape = scrape_week(now, week_start, region)
    except ScrapeError as exc:
        print(f"조회 실패: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({
            "region": region.label,
            "week_start": week_start.isoformat(),
            "days": [
                {
                    "date": d.isoformat(),
                    "weekday": WEEKDAY_KO[d.weekday()],
                    "tmin_lo": v.tmin_lo, "tmin_hi": v.tmin_hi,
                    "tmax_lo": v.tmax_lo, "tmax_hi": v.tmax_hi,
                    "sky": v.sky, "pop": v.pop, "source": v.source,
                }
                for d, v in sorted(scrape.days.items())
            ],
            "narratives": [
                {"title": n.title, "url": n.url,
                 "issued_at": n.issued_at.isoformat() if n.issued_at else None,
                 "lines": n.lines}
                for n in scrape.narratives
            ],
        }, ensure_ascii=False, indent=2))
        return 0

    end = week_start + dt.timedelta(days=6)
    print(f"■ {region.label} {week_start:%Y-%m-%d}(월) ~ {end:%m-%d}(일)")
    print("  (기온은 지역 간 분포 범위입니다)\n")
    for offset in range(7):
        date = week_start + dt.timedelta(days=offset)
        v = scrape.days.get(date)
        label = day_label(date)
        if v is None:
            print(f"  {label}  예보 없음")
            continue
        pop = f"  강수 {v.pop}%" if v.pop is not None else ""
        print(
            f"  {label}  아침 {(range_text(v.tmin_lo, v.tmin_hi) or '-'):>10}"
            f"  낮 {(range_text(v.tmax_lo, v.tmax_hi) or '-'):>10}"
            f"  {v.sky or '-':<8}{pop}   [{v.source}]"
        )
    print()
    print(scrape.as_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
