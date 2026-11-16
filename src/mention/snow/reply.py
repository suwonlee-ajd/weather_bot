"""첫눈을 물었을 때의 답 — 전국 현황(지도와 함께), 지점·지역별 관측과 평년, 앞으로 7일 예보의 눈."""
from __future__ import annotations

import datetime as dt
import logging

from src.common.text import bold, short_date
from src.kma.page import ScrapedDay, ScrapeError
from src.kma.regions import NATIONWIDE, Region, extract_region, region_by_key
from src.mention.forecast import cached_scrape, days_in
from src.mention.parse import FORWARD_DAYS, SNOW_RE, WEATHER_ASK_RE
from src.mention.reply import Reply, with_map
from src.season.snow import data as snow
from src.season.snow import map as snow_map
from src.season.snow.data import PAGE, SnowError, Status
from src.season.snow.stations import Station, find_station, stations_in_region
from src.season.snow.text import (
    SOURCES,
    observed_line,
    season_text,
    snow_days,
    station_text,
    week_line,
)

log = logging.getLogger("weather-mention")


def _forecast(region: Region, now: dt.datetime) -> list[ScrapedDay] | None:
    """앞으로 7일. 못 받으면 None — «눈 소식이 없다» 와 갈라 말함."""
    try:
        scrape = cached_scrape(region, now)
    except ScrapeError as exc:
        log.warning("첫눈 답의 예보 수집 실패: %s", exc)
        return None
    return [v for _, v in sorted(days_in(scrape, now.date(), FORWARD_DAYS).items())]


def _stations_text(stations: tuple[Station, ...], label: str, region: Region, status: Status,
                   now: dt.datetime) -> str:
    days = _forecast(region, now)
    lines = [f"*{label} 첫눈* ({season_text(status)})",
             *(f"• {station_text(st, status, bold)}" for st in stations)]
    if days and snow_days(days):
        lines.append(f"• 앞으로 7일 — {week_line(status, days, stations, muted=lambda s: s)}")
    lines.append(f"_{SOURCES}_")
    return "\n".join(lines)


def snow_theme(query: str, now: dt.datetime) -> Reply | None:
    """첫눈 질문이면 답(전국 현황은 지도와 함께), 아니면 None."""
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
        return Reply("기상청 첫눈 관측을 가져오지 못했습니다. 잠시 뒤 다시 불러 주세요.\n"
                     f"기상자료개방포털에서 직접 보실 수 있어요 — {PAGE}")

    if station := find_station(query):
        home = region_by_key(station.regions[-1])     # 영동·영서처럼 좁은 구역이 뒤
        return Reply(_stations_text((station,), station.name, home, status, now))
    if region not in (None, NATIONWIDE) and (stations := stations_in_region(region.key)):
        return Reply(_stations_text(stations, region.label, region, status, now))

    today = now.date()
    days = _forecast(NATIONWIDE, now)
    text = "\n".join([
        f"*첫눈 현황* ({short_date(today)} 기준 · {season_text(status)})",
        f"• 관측 — {observed_line(status, bold)}",
        f"• 앞으로 7일 — {week_line(status, days, muted=lambda s: s)}",
        f"_{SOURCES} · 지역 이름을 함께 불러 주시면 그 지역만 자세히 알려드려요_",
    ])
    snowy = tuple(snow_days(days)) if days is not None else None    # 지도 머리의 «앞으로 7일» 줄도 그림 재료
    return with_map(text, snow_map.INFO, ("snow-map", today, status.signature(), snowy),
                    lambda: snow_map.render_png(status, today, days, span_label="앞으로 7일"))
