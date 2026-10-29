"""첫눈을 물었을 때의 답 — 전국 현황(지도와 함께), 지점·지역별 관측과 평년, 앞으로 7일 예보의 눈."""
from __future__ import annotations

import datetime as dt
import logging

from src.common.text import bold, short_date, short_day_label
from src.kma.page import ScrapedDay, ScrapeError
from src.kma.regions import NATIONWIDE, REGIONS, Region, extract_region
from src.mention.parse import FORWARD_DAYS, SNOW_RE, WEATHER_ASK_RE
from src.mention.region_reply import cached_scrape
from src.season import snow
from src.season.snow import SnowError, Status
from src.season.snow_text import (
    gap_text,
    observed_line,
    season_text,
    snow_days,
    sources,
    waiting_text,
    week_line,
)
from src.season.stations import Station, find_station, stations_in_region

log = logging.getLogger("weather-mention")

SNOW_PAGE = "https://data.kma.go.kr/data/seasonObs/seasonObsDataList.do?pgmNo=648"


def _forecast(region: Region, now: dt.datetime) -> list[ScrapedDay]:
    """앞으로 7일 — 못 받으면 비움(예보 없이 관측만 답함)."""
    try:
        scrape = cached_scrape(region, now)
    except ScrapeError as exc:
        log.warning("첫눈 답의 예보 수집 실패: %s", exc)
        return []
    end = now.date() + dt.timedelta(days=FORWARD_DAYS - 1)
    return [scrape.days[d] for d in sorted(scrape.days) if now.date() <= d <= end]


def _station_line(st: Station, status: Status) -> str:
    if day := status.first.get(st.name):
        gap = gap_text(st, day)
        return f"• *{st.name}* — *{short_date(day)} 첫눈 관측*" + (f" · {gap}" if gap else "")
    wait = waiting_text(st, status)
    return f"• *{st.name}* — 아직" + (f" ({wait})" if wait else "")


def _stations_text(stations: tuple[Station, ...], label: str, region: Region, status: Status,
                   now: dt.datetime) -> str:
    snowy = snow_days(_forecast(region, now))
    lines = [f"*{label} 첫눈* ({season_text(status)})", *(_station_line(st, status) for st in stations)]
    if snowy:
        tail = " (첫눈이 될 수 있음)" if any(st.name not in status.first for st in stations) else ""
        lines.append(f"• 앞으로 7일 — {' · '.join(short_day_label(d) for d in snowy)} 눈 예보{tail}")
    lines.append(f"_{sources()}_")
    return "\n".join(lines)


def snow_theme(query: str, now: dt.datetime) -> tuple[str, tuple[Status, list] | None] | None:
    """첫눈 질문이면 (답, 지도로 그릴 (현황, 예보) 또는 None), 아니면 None."""
    if not SNOW_RE.search(query):
        return None
    region, _ = extract_region(query)
    # 지역 날씨를 물으면 날씨 질문 ("첫눈 온다는 주말 서울 날씨") — 그 답에 첫눈 한 줄이 붙음
    if WEATHER_ASK_RE.search(query) and region not in (None, NATIONWIDE):
        return None
    try:
        status = snow.fetch_status(now.date())
    except SnowError as exc:
        log.warning("첫눈 관측 실패: %s", exc)
        return ("기상청 첫눈 관측을 가져오지 못했습니다. 잠시 뒤 다시 불러 주세요.\n"
                f"기상자료개방포털에서 직접 보실 수 있어요 — {SNOW_PAGE}"), None

    if station := find_station(query):
        home = next(r for r in REGIONS if r.key == station.regions[-1])   # 영동·영서처럼 좁은 구역이 뒤
        return _stations_text((station,), station.name, home, status, now), None
    if region not in (None, NATIONWIDE) and (stations := stations_in_region(region.key)):
        return _stations_text(stations, region.label, region, status, now), None

    today = now.date()
    days = _forecast(NATIONWIDE, now)
    end = today + dt.timedelta(days=FORWARD_DAYS - 1)
    text = "\n".join([
        f"*첫눈 현황* ({short_date(today)} 기준 · {season_text(status)})",
        f"• 관측 — {observed_line(status, bold)}",
        f"• 앞으로 7일 — {week_line(status, days, today, end, muted=lambda s: s)}",
        f"_{sources()} · 지역 이름을 함께 불러 주시면 그 지역만 자세히 알려드려요_",
    ])
    return text, (status, days)
