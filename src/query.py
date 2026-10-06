"""이번 주 날씨를 사람이 읽을 형태로 출력하는 조회 CLI.

주간 게시 봇과 같은 수집 코드(src/kma_scrape.py)를 쓰되, 슬랙 게시 없이 결과만 찍음.

    python -m src.query            # 이번 주 전국
    python -m src.query 부산        # 지역 지정
    python -m src.query --json     # 기계용 JSON
    python -m src.query --foliage  # 단풍 현황·예상 (9월 둘째 주 ~ 11월 둘째 주)
    python -m src.query --foliage 설악산
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from .config import KST
from .foliage import (
    CRITERIA_TEXT, KINDS, NOT_STARTED_TEXT, OUTLOOK_SOURCE, SEASON_TEXT, STAGES,
    FoliageError, fetch_snapshot, in_season, next_season,
)
from .forecast import WEEKDAY_KO, day_label, range_text, short_date
from .kma_scrape import REGION_HELP, ScrapeError, find_region, scrape_week
from .logsetup import setup
from .mountains import MOUNTAINS, find_mountain
from .render_foliage import sources


def _foliage(name: str, as_json: bool) -> int:
    today = dt.datetime.now(tz=KST).date()
    if not in_season(today):
        start, end = next_season(today)
        print(f"단풍은 {SEASON_TEXT}에만 다룹니다. 다음 기간: {start} ~ {end}", file=sys.stderr)
        return 3
    picked = MOUNTAINS
    if name:
        m = find_mountain(name)
        if m is None:
            print(f"기상청이 단풍을 관측하는 {len(MOUNTAINS)}곳에 없습니다: {name}\n"
                  + " · ".join(x.name for x in MOUNTAINS), file=sys.stderr)
            return 2
        picked = (m,)
    try:
        snap = fetch_snapshot(today)
    except FoliageError as exc:
        print(f"조회 실패: {exc}", file=sys.stderr)
        return 1

    if as_json:
        def when(kind, m):
            day, observed = snap.when(kind, m.name)
            return {"date": day.isoformat(), "observed": observed} if day else None
        o = snap.outlook
        print(json.dumps({
            "as_of": today.isoformat(),
            "in_service": snap.status.in_service,
            "outlook": {"source": OUTLOOK_SOURCE, "published": o.published and o.published.isoformat(),
                        "url": o.url} if o else None,
            "outlook_error": snap.outlook_error or None,
            "mountains": [{"name": m.name, "stage": STAGES[snap.stage(m.name)],
                           **{kind: when(kind, m) for kind in KINDS}} for m in picked],
        }, ensure_ascii=False, indent=2))
        return 0

    def cell(kind, m):
        day, observed = snap.when(kind, m.name)
        return f"{short_date(day)} {'관측' if observed else '예상'}" if day else "-"

    print(f"■ 단풍 {today:%m/%d} 기준 — {sources(snap)}")
    if not snap.status.in_service:
        print(f"  {NOT_STARTED_TEXT}")
    print(f"  ({CRITERIA_TEXT} · '관측' 은 기상청, '예상' 은 {OUTLOOK_SOURCE})\n")
    for m in picked:
        print(f"  {m.name}  {STAGES[snap.stage(m.name)]:<4}"
              f"  첫단풍 {cell('first', m):<10}  절정 {cell('peak', m)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="기상청 이번 주 예보 조회")
    parser.add_argument("region", nargs="?", default="전국", help=f"지역 ({REGION_HELP})")
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    parser.add_argument("--week-offset", type=int, default=0, help="0=이번 주, 1=다음 주")
    parser.add_argument("--foliage", action="store_true",
                        help="단풍 현황·예상. region 자리에 산 이름을 주면 그 산만")
    args = parser.parse_args(argv)
    # 로그 설정(src/logsetup.py)을 따름. 결과는 stdout 이라 기본은 WARNING 으로 조용히 둠 — LOG_LEVEL=DEBUG 로 엶
    setup("query", level=os.environ.get("LOG_LEVEL") or "WARNING")

    if args.foliage:
        return _foliage("" if args.region == "전국" else args.region, args.json)

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
