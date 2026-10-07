"""기상청 날씨누리 공개 페이지에서 이번 주 예보를 긁어옴. (API 키·결제 불필요)

두 페이지만 씀. 둘 다 서버 렌더링이라 requests + BeautifulSoup 로 충분하고,
robots.txt 는 `User-Agent: * / Allow: /` 로 이 경로들을 허용함.

  예보 통보문  /w/forecast/notice.do
      총괄예보관이 쓴 종합 서술(□/○ 줄) + **전국** 최저/최고기온 범위 표 (오전 발표 기준 오늘~글피, D+0~D+3)
      "최저기온 14 ~ 22 / 최고기온 25 ~ 30" 처럼 지역 간 분포 범위로 나옴.
      원본 게시물의 "아침 기온 18~24℃, 낮 기온 25~33℃" 와 정확히 같은 형식.

  중기예보     /w/forecast/overall/mid-term.do
      기상전망 서술 + 도시별 최저/최고기온 표 + 지역별 오전/오후 하늘상태·강수확률 표 (D+4~D+10)
      도시별 값을 가로로 모으면 전국 분포 범위가 나옴.

특보·태풍 페이지는 지도 기반 JS 라 긁지 않음. 대신 통보문의 종합 서술이 그것을 짚어줌
("내일까지 풍랑과 너울 유의" 처럼).
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


# --------------------------------------------------------------------------- #
# 공통 유틸
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 1) 예보 통보문 — 전국 최저/최고기온 범위 (오전 발표 기준 D+0 ~ D+3)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 2) 중기예보 — 도시별 기온 표를 전국 범위로 집계 (D+4 ~ D+10)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 합치기
# --------------------------------------------------------------------------- #

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
    """월~일 한 주. 주간 게시(월요일 실행)가 씀."""
    return scrape_range(now, week_start, 7, region)
