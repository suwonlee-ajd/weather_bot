"""철마다 주간 게시에 붙이는 소식(테마) — 다루는 기간과 덩어리(Block) 조립 함수의 짝.

모델에 맡기지 않음 — 지어낸 개화일·단풍일은 그럴듯해서 알아채기 어려움. 못 만들면 테마만 빼고 게시함.

  단풍  9월 둘째 주 ~ 11월 둘째 주      관측 기상청 · 예상 웨더아이 + 지도
  첫눈  11월 첫째 주 ~ 서울 관측 다음 주  관측 기상청 계절관측 · 평년 · 그 주 예보의 눈 + 지도
  벚꽃  2월 마지막 주 ~ 3월 마지막 주   관측 기상청 · 예상 웨더아이  (문단 구성은 2027 시즌 전에 다시 봄)
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.common.text import bold
from src.season.basemap import MapInfo
from src.season.blossom import data as blossom
from src.season.blossom import text as blossom_text
from src.season.foliage import data as foliage
from src.season.foliage import map as foliage_map
from src.season.foliage import text as foliage_text
from src.season.snow import data as snow
from src.season.snow import map as snow_map
from src.season.snow import text as snow_text
from src.weekly.forecast import WeekForecast
from src.weekly.paragraph import Attachment, Block, Paragraph

log = logging.getLogger(__name__)


def _with_map(paragraph: Paragraph, info: MapInfo, render: Callable[[], bytes], sources: str) -> Block:
    """지도를 못 그려도 글은 남김 — 출처의 «X 지도» 도 실린 것에 맞춰 «X» 로."""
    try:
        png = render()
    except Exception:
        log.warning("%s를 만들지 못해 글로만 붙입니다", info.title, exc_info=True)
        return Block(paragraph, f"{info.name} · {sources}")
    log.info("%s %s bytes", info.title, f"{len(png):,}")
    return Block(paragraph, f"{info.title} · {sources}", Attachment(info.slug, png, info.title, info.alt))


def foliage_block(week: WeekForecast, today: dt.date, scale: int) -> Block | None:
    try:
        snap = foliage.fetch_snapshot(today)
    except Exception:
        log.warning("단풍 현황을 받지 못해 단풍 소식을 빼고 게시합니다", exc_info=True)
        return None
    paragraph = (Paragraph("이번 주 단풍", emoji=":maple_leaf:")
                 .add("관측", foliage_text.observed_line(snap, bold))
                 .add("이번 주", foliage_text.week_line(snap, week.week_start, week.week_end, bold,
                                                         muted=lambda s: s)))
    # 출처는 실린 것에 맞춤 — 예상을 못 읽었으면 예상 출처도 뺌
    return _with_map(paragraph, foliage_map.INFO, lambda: foliage_map.render_png(snap, week.week_start, scale=scale),
                     foliage_text.sources(snap))


def blossom_block(week: WeekForecast, today: dt.date, scale: int) -> Block | None:
    status = outlook = None
    try:
        status = blossom.fetch_status(today)
    except Exception:
        log.warning("기상청 벚꽃 관측을 받지 못했습니다", exc_info=True)
    try:
        outlook = blossom.fetch_outlook(week.week_start.year)
    except Exception:
        log.warning("웨더아이 벚꽃 예상을 받지 못했습니다", exc_info=True)
    if status is None and outlook is None:
        log.warning("벚꽃 자료가 없어 벚꽃 소식을 빼고 게시합니다")
        return None

    paragraph = Paragraph("이번 주 벚꽃", emoji=":cherry_blossom:")
    if status is not None:
        paragraph.add("관측", blossom_text.observed_line(status))
    # 못 받은 예상은 "아직 나오지 않았습니다" 로 둘러대지 않고 뺌
    if outlook is not None:
        paragraph.add("이번 주", blossom_text.week_line(outlook, week.week_start, week.week_end))
        paragraph.add("올해" if outlook.expected else "평년", blossom_text.year_line(outlook))
    return Block(paragraph, f"벚꽃 · {blossom_text.sources(status, outlook)}")


def snow_block(week: WeekForecast, today: dt.date, scale: int) -> Block | None:
    """«이번 주» 줄은 그 주 예보의 하늘상태에서 눈을 셈."""
    try:
        status = snow.fetch_status(today, timeout=snow.WEEKLY_TIMEOUT_SEC)
    except Exception:
        log.warning("첫눈 관측을 받지 못해 첫눈 소식을 빼고 게시합니다", exc_info=True)
        return None
    if not snow.weekly_open(status, week.week_start):
        return None
    paragraph = (Paragraph("이번 주 첫눈", emoji=":snowflake:")
                 .add("관측", snow_text.observed_line(status, bold))
                 .add("이번 주", snow_text.week_line(status, week.days, muted=lambda s: s)))
    return _with_map(paragraph, snow_map.INFO,
                     lambda: snow_map.render_png(status, week.week_start, week.days, scale=scale), snow_text.SOURCES)


@dataclass(frozen=True)
class Theme:
    name: str
    in_season: Callable[[dt.date], bool]
    build: Callable[[WeekForecast, dt.date, int], Block | None]


THEMES: tuple[Theme, ...] = (
    Theme("단풍", foliage.in_season, foliage_block),
    Theme("첫눈", snow.in_weekly_season, snow_block),
    Theme("벚꽃", blossom.in_season, blossom_block),
)


def blocks_for(week: WeekForecast, today: dt.date, scale: int) -> list[Block]:
    """그 주(월요일 기준)에 든 철의 덩어리."""
    return [block for theme in THEMES
            if theme.in_season(week.week_start) and (block := theme.build(week, today, scale))]
