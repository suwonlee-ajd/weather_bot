"""기상청 예보 통보문(D+0~D+3)과 중기예보(D+4~D+10)를 긁어 날짜별로 합침.

둘 다 서버 렌더링이고 robots.txt 가 허용함. 특보·태풍 페이지는 JS 지도라 긁지 않고
통보문 종합 서술로 대신함.
"""
from __future__ import annotations

import datetime as dt
import logging

import requests

from src.kma.mid_term import fetch_mid_term
from src.kma.notice import fetch_notice
from src.kma.page import Narrative, Scrape, ScrapedDay, ScrapeError
from src.kma.regions import NATIONWIDE, Region

log = logging.getLogger(__name__)


def scrape_range(
    now: dt.datetime,
    start: dt.date,
    num_days: int = 7,
    region: Region = NATIONWIDE,
) -> Scrape:
    """start 부터 num_days 일을 통보문(가까운 날) + 중기예보(먼 날) 로 채움."""
    merged: dict[dt.date, ScrapedDay] = {}
    narratives: list[Narrative] = []
    errors: list[str] = []

    for fetch in (fetch_mid_term, fetch_notice):  # 나중에 오는 통보문이 덮어씀 — 더 정확함
        try:
            days, narrative = fetch(now, region)
        except (requests.RequestException, ScrapeError) as exc:
            errors.append(f"{fetch.__name__}: {exc}")
            log.warning("수집 실패 — %s region=%s %s: %s",
                        fetch.__name__, region.key, type(exc).__name__, exc)
            continue
        merged.update(days)
        narratives.append(narrative)

    if not merged:
        raise ScrapeError("기상청 페이지에서 아무 값도 얻지 못했습니다: " + " / ".join(errors))

    window = {start + dt.timedelta(days=i) for i in range(num_days)}
    return Scrape(days={d: v for d, v in merged.items() if d in window}, narratives=narratives)


def scrape_week(now: dt.datetime, week_start: dt.date, region: Region = NATIONWIDE) -> Scrape:
    return scrape_range(now, week_start, 7, region)
