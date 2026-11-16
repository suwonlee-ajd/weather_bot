"""첫눈 — 기상청 계절관측 24곳의 첫눈 날짜와 1991~2020 평년. 첫눈은 관측만 있고 예상은 없음.

출처는 기상자료개방포털 계절관측 조회 화면(HTML 표) — 키 없이 열리는 곳은 여기뿐(API허브는 인증키가 필요함).
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from src.common.cache import get_or_set
from src.season import sources as shared
from src.season.snow.stations import BY_NAME, STATIONS, Station

log = logging.getLogger(__name__)

URL = "https://data.kma.go.kr/data/seasonObs/seasonObsDataList.do"
PGM_NO = "648"               # 계절관측 자료조회 화면
PAGE = f"{URL}?pgmNo={PGM_NO}"
SNOW_ELEMENT = "DB006403"     # 계절관측 요소 코드 — 서리 DB006401 · 얼음 DB006402
HEADLINE = "서울"              # «아직» 의 기준
RECENT_DAYS = 7               # 관측을 «새 소식» 으로 치는 날수 — 주간 게시 한 번, 그 뒤로 되풀이하면 잔소리

STATUS_TTL_SEC = 3600         # 관측 당일 반영됨
STATUS_RETRY_SEC = 120        # 짧게 — 점검이 끝나면 첫눈 답이 곧 돌아오게
# 멘션은 짧게 — 날씨 답마다 붙는 덧말이라 포털이 멈추면 답이 늦어짐. 주간 게시는 기다려도 됨
TIMEOUT_SEC = 5.0
WEEKLY_TIMEOUT_SEC = 20.0


class SnowError(RuntimeError):
    pass


def season_year(day: dt.date) -> int:
    """계절관측의 «년도» — 그해 가을부터 이듬해 봄까지. 부산 2025년의 첫눈은 2026-02-07."""
    return day.year if day.month >= 8 else day.year - 1


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
        """지도에 그리는 것 전부 — 올해와 지난겨울."""
        return self.year, tuple(sorted(self.first.items())), tuple(sorted(self.last.items()))


def _is_station_head(tag) -> bool:
    return tag.name == "dt" and tag.get_text(strip=True) == "지점"


def _tables(text: str) -> dict[str, object]:
    """지점마다 «지점: 서울» 머리 뒤에 표 하나. caption 은 지점과 무관한 고정 문구라 머리로 짝지음.

    표마다 가장 가까운 앞 머리를 봄 — 표가 빠진 지점이 다음 지점의 표를 집지 않고, 머리와 표 사이에
    다른 칸이 끼어도 읽힘.
    """
    out = {}
    for table in BeautifulSoup(text, "lxml").find_all("table"):
        head = table.find_previous(_is_station_head)
        dd = head.find_next_sibling("dd") if head else None
        if dd is not None and (name := dd.get_text(strip=True)) in BY_NAME:
            out.setdefault(name, table)
    return out


def parse_status(text: str, year: int) -> Status:
    """년도 | 시작 | 시작(평비) | 끝 | 끝(평비). 시작일이 그 년도 시즌 밖인 행(안동 2026년의 1/10)은 버림."""
    tables = _tables(text)
    if not tables:
        raise SnowError("기상청 계절관측 응답에서 지점 표를 찾지 못했습니다 (형식 변경 의심)")
    status = Status(year)
    for name, table in tables.items():
        for row in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            try:
                start = dt.date.fromisoformat(cells[1])
            except ValueError:
                continue
            row_year = int(cells[0])
            if season_year(start) != row_year:
                continue
            if row_year == year:
                status.first[name] = start
            elif row_year == year - 1:
                status.last[name] = start
    return status


def fetch_status(today: dt.date, *, timeout: float = TIMEOUT_SEC, retries: int = 0) -> Status:
    """retries 는 시간 초과·접속 실패 때 더 받는 횟수 — 포털이 가끔 한 번만 늦음. 기다려도 되는 주간 게시·조회만 씀."""
    year = season_year(today)
    params = {"pgmNo": PGM_NO, "stnIds": ",".join(f"_{s.stn}" for s in STATIONS),
              "elementCds": SNOW_ELEMENT, "startDt": str(year - 1), "endDt": str(year)}

    def load() -> Status:
        for attempt in range(retries + 1):
            try:
                resp = shared.get(URL, error=SnowError, timeout=timeout, params=params)
                break
            except SnowError as exc:
                if attempt == retries:
                    raise
                log.info("기상자료개방포털이 응답하지 않아 한 번 더 받습니다: %s", exc)
        return parse_status(resp.text, year)

    return get_or_set(("snow-status", today), STATUS_TTL_SEC, load,
                      errors=(SnowError,), error_ttl=STATUS_RETRY_SEC)


def recent(status: Status, day: dt.date, stations: tuple[Station, ...] = STATIONS) -> list[Station]:
    """day 까지 RECENT_DAYS 안에 첫눈이 관측된 곳."""
    return [st for st in stations
            if (d := status.first.get(st.name)) and 0 <= (day - d).days <= RECENT_DAYS]


def waiting(status: Status, stations: tuple[Station, ...] = STATIONS) -> list[Station]:
    return [st for st in stations if st.name not in status.first]


def showing(status: Status, day: dt.date, snowy: bool, stations: tuple[Station, ...] = STATIONS) -> bool:
    """다룰 때인지 — 최근 첫눈이 관측됐거나, 아직인 곳이 남았는데 눈 예보가 있을 때.

    기간은 우리가 정하지 않고 자료가 정함 — 첫눈은 관측만 있고 예상이 없어 «새 소식» 이 있을 때만 다룸.
    """
    return bool(recent(status, day, stations)) or (snowy and bool(waiting(status, stations)))
