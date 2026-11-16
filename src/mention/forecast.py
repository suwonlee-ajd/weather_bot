"""멘션 답이 함께 쓰는 광역 예보 캐시 — 광역 답과 첫눈 답이 지역당 한 항목을 나눠 씀."""
from __future__ import annotations

import datetime as dt
import os

from src.common.cache import get_or_set
from src.kma.page import Scrape, ScrapedDay
from src.kma.regions import Region
from src.kma.scrape import scrape_range
from src.mention.parse import MAX_FORECAST_DAYS

CACHE_TTL_SEC = int(os.environ.get("MENTION_CACHE_TTL", "3600"))


def cached_scrape(region: Region, now: dt.datetime) -> Scrape:
    """오늘부터 열흘. 통째로 담고 기간은 쓰는 쪽에서 자름 — 자른 값을 담으면
    «다음 주» 를 먼저 물은 뒤 «앞으로 7일» 에 오늘·내일이 빠짐."""
    return get_or_set(region.key, CACHE_TTL_SEC,
                      lambda: scrape_range(now, now.date(), MAX_FORECAST_DAYS, region))


def days_in(scrape: Scrape, start: dt.date, days: int) -> dict[dt.date, ScrapedDay]:
    """열흘 캐시에서 물은 기간만."""
    window = {start + dt.timedelta(days=i) for i in range(days)}
    return {d: v for d, v in scrape.days.items() if d in window}
