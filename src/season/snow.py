"""첫눈 — 기상청 계절관측 24곳의 첫눈 날짜와 1991~2020 평년. 첫눈은 관측만 있고 예상은 없음.

출처는 기상자료개방포털 계절관측 조회 화면(HTML 표) — 키 없이 열리는 곳은 여기뿐(API허브는 인증키가 필요함).
"""
from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field

from src.common.cache import get_or_set
from src.season import sources as shared
from src.season.stations import BY_NAME, STATIONS, Station

URL = "https://data.kma.go.kr/data/seasonObs/seasonObsDataList.do"
SNOW_ELEMENT = "DB006403"     # 계절관측 요소 코드 — 서리 DB006401 · 얼음 DB006402
HEADLINE = "서울"              # 주간 게시의 철 기간과 «아직» 의 기준

STATUS_TTL_SEC = 3600         # 관측 당일 반영됨
STATUS_RETRY_SEC = 120        # 짧게 — 지역 날씨 답마다 붙여, 점검 중이면 답마다 기다림


class SnowError(RuntimeError):
    pass


def season_year(day: dt.date) -> int:
    """계절관측의 «년도» — 그해 가을부터 이듬해 봄까지. 부산 2025년의 첫눈은 2026-02-07."""
    return day.year if day.month >= 8 else day.year - 1


def _in_year(day: dt.date, year: int) -> bool:
    return dt.date(year, 8, 1) <= day < dt.date(year + 1, 8, 1)


def normal_of(station: Station, year: int) -> dt.date | None:
    if station.normal is None:
        return None
    month, day = station.normal
    return dt.date(year if month >= 8 else year + 1, month, day)


def gap_days(station: Station, day: dt.date) -> int | None:
    """평년과의 차이 — 늦으면 양수."""
    normal = normal_of(station, season_year(day))
    return (day - normal).days if normal else None


@dataclass
class Status:
    year: int                                                  # 시즌 연도(season_year)
    first: dict[str, dt.date] = field(default_factory=dict)    # 올 시즌 첫눈
    last: dict[str, dt.date] = field(default_factory=dict)     # 지난 시즌 첫눈

    def signature(self) -> tuple:
        return self.year, tuple(sorted(self.first.items()))


# 지점마다 «지점: 서울» 머리 뒤에 표 하나. caption 은 지점과 무관한 고정 문구라 머리로 짝지음
_BLOCK = re.compile(r"<dt>\s*<b>\s*지점\s*</b>\s*</dt>\s*<dd>\s*([^<]+?)\s*</dd>.*?<table[^>]*>(.*?)</table>",
                    re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def parse_status(text: str, year: int) -> Status:
    """년도 | 시작 | 시작(평비) | 끝 | 끝(평비). 시작일이 그 년도 시즌 밖인 행(안동 2026년의 1/10)은 버림."""
    blocks = _BLOCK.findall(text)
    if not any(html.unescape(name) in BY_NAME for name, _ in blocks):
        raise SnowError("기상청 계절관측 응답에서 지점 표를 찾지 못했습니다 (형식 변경 의심)")
    status = Status(year)
    for name, table in blocks:
        name = html.unescape(name)
        for row in _ROW.findall(table):
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in _CELL.findall(row)]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            try:
                start = dt.date.fromisoformat(cells[1])
            except ValueError:
                continue
            row_year = int(cells[0])
            if not _in_year(start, row_year):
                continue
            if row_year == year:
                status.first[name] = start
            elif row_year == year - 1:
                status.last[name] = start
    return status


def fetch_status(today: dt.date) -> Status:
    year = season_year(today)

    def load() -> Status:
        resp = shared.get(URL, error=SnowError, params={
            "pgmNo": "648", "stnIds": ",".join(f"_{s.stn}" for s in STATIONS),
            "elementCds": SNOW_ELEMENT, "startDt": str(year - 1), "endDt": str(year),
        })
        return parse_status(resp.text, year)

    return get_or_set(("snow-status", today), STATUS_TTL_SEC, load,
                      errors=(SnowError,), error_ttl=STATUS_RETRY_SEC)


def _first_monday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=-first.weekday() % 7)


def in_weekly_season(week_start: dt.date) -> bool:
    """11월 첫째 월요일 ~ 1월 말. 서울이 관측된 뒤 언제 끝낼지는 weekly_open 이 정함."""
    year = season_year(week_start)
    return _first_monday(year, 11) <= week_start < dt.date(year + 1, 2, 1)


def weekly_open(status: Status, week_start: dt.date) -> bool:
    """서울 첫눈을 그다음 월요일 게시에서 한 번 알리고 끝냄."""
    seen = status.first.get(HEADLINE)
    return seen is None or seen >= week_start - dt.timedelta(days=7)


def in_note_season(day: dt.date) -> bool:
    """지역 날씨 답에 한 줄을 붙이는 기간 — 11월 ~ 1월."""
    return day.month in (11, 12, 1)
