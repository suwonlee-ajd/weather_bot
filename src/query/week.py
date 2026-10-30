"""이번 주 날씨·단풍·첫눈을 슬랙 게시 없이 터미널에 찍는 조회 CLI — 날씨와 진입 인자. 철 소식은 season.

    python -m src.query [지역] [--json]    /    python -m src.query --foliage [산]    /    python -m src.query --snow [지점]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from src.common.config import KST
from src.common.logsetup import setup
from src.common.text import WEEKDAY_KO, day_label, range_text
from src.kma.page import ScrapeError
from src.kma.regions import REGION_HELP, find_region
from src.kma.scrape import scrape_week
from src.query import season


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="기상청 이번 주 예보 조회")
    parser.add_argument("region", nargs="?", default="전국", help=f"지역 ({REGION_HELP})")
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    parser.add_argument("--week-offset", type=int, default=0, help="0=이번 주, 1=다음 주")
    parser.add_argument("--foliage", action="store_true",
                        help="단풍 현황·예상. region 자리에 산 이름을 주면 그 산만")
    parser.add_argument("--snow", action="store_true",
                        help="첫눈 관측·평년. region 자리에 지점 이름을 주면 그 지점만")
    args = parser.parse_args(argv)
    # 결과는 stdout 이라 로그는 기본 WARNING
    setup("query", level=os.environ.get("LOG_LEVEL") or "WARNING")

    if args.foliage:
        return season.show_foliage("" if args.region == "전국" else args.region, args.json)
    if args.snow:
        return season.show_snow("" if args.region == "전국" else args.region, args.json)

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


if __name__ == "__main__":       # python -m src.query 는 __main__.py 가 부름
    sys.exit(main())
