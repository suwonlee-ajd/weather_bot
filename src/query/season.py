"""철 소식 조회 — 단풍 현황·예상, 첫눈 관측·평년."""
from __future__ import annotations

import datetime as dt
import json
import sys

from src.common.config import KST
from src.common.text import short_date
from src.season.foliage import data as foliage
from src.season.foliage.data import (
    CRITERIA_TEXT,
    KINDS,
    NOT_STARTED_TEXT,
    SEASON_TEXT,
    STAGES,
    FoliageError,
    in_season,
    next_season,
)
from src.season.foliage.mountains import MOUNTAINS, find_mountain
from src.season.foliage.text import sources
from src.season.snow import data as snow
from src.season.snow import stations
from src.season.snow.text import SOURCES as SNOW_SOURCES
from src.season.snow.text import season_text, station_text
from src.season.sources import OUTLOOK_SOURCE


def show_foliage(name: str, as_json: bool) -> int:
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
        snap = foliage.fetch_snapshot(today)
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


def show_snow(name: str, as_json: bool) -> int:
    today = dt.datetime.now(tz=KST).date()
    picked = stations.STATIONS
    if name:
        st = stations.find_station(name)
        if st is None:
            print(f"기상청이 첫눈을 관측하는 {len(stations.STATIONS)}곳에 없습니다: {name}\n"
                  + " · ".join(s.name for s in stations.STATIONS), file=sys.stderr)
            return 2
        picked = (st,)
    try:
        status = snow.fetch_status(today)
    except snow.SnowError as exc:
        print(f"조회 실패: {exc}", file=sys.stderr)
        return 1

    if as_json:
        def day(d):
            return d.isoformat() if d else None
        print(json.dumps({
            "as_of": today.isoformat(), "season": status.year,
            "stations": [{"name": s.name, "stn": s.stn, "first": day(status.first.get(s.name)),
                          "normal": day(snow.normal_of(s, status.year)), "last": day(status.last.get(s.name))}
                         for s in picked],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"■ 첫눈 {today:%m/%d} 기준 · {season_text(status)} — {SNOW_SOURCES}\n")
    for s in picked:
        print(f"  {station_text(s, status, bold=lambda n: n)}")
    return 0
