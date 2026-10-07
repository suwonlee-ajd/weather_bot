"""철마다 주간 게시에 붙이는 소식(테마) — 다루는 기간과 덩어리(Block) 조립 함수의 짝.

모델에 맡기지 않음 — 지어낸 개화일·단풍일은 그럴듯해서 알아채기 어려움. 못 만들면 테마만 빼고 게시함.

  단풍  9월 둘째 주 ~ 11월 둘째 주      관측 기상청 · 예상 웨더아이 + 지도
  벚꽃  2월 마지막 주 ~ 3월 마지막 주   관측 기상청 · 예상 웨더아이  (문단 구성은 2027 시즌 전에 다시 봄)
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.common.text import bold
from src.season import blossom, foliage, foliage_map, foliage_text
from src.weekly.paragraph import Attachment, Block, Paragraph

log = logging.getLogger(__name__)


def foliage_block(week_start: dt.date, today: dt.date, scale: int) -> Block | None:
    try:
        snap = foliage.fetch_snapshot(today)
    except Exception:
        log.warning("단풍 현황을 받지 못해 단풍 소식을 빼고 게시합니다", exc_info=True)
        return None
    week_end = week_start + dt.timedelta(days=6)
    paragraph = (Paragraph("이번 주 단풍", emoji=":maple_leaf:")
                 .add("관측", foliage_text.observed_line(snap, bold))
                 .add("이번 주", foliage_text.week_line(snap, week_start, week_end, bold,
                                                         muted=lambda s: s)))
    attachment = None
    try:
        png = foliage_map.render_png(snap, week_start, scale=scale)
        attachment = Attachment("foliage", png, "단풍 지도",
                                "전국 21개 명산의 단풍 현황(기상청)과 예상 시기(웨더아이) 지도")
        log.info("단풍 지도 %s bytes", f"{len(png):,}")
    except Exception:
        log.warning("단풍 지도를 만들지 못해 글로만 붙입니다", exc_info=True)
    # 출처는 실린 것에 맞춤 — 예상을 못 읽었으면 예상 출처도 뺌
    credit = f"{'단풍 지도' if attachment else '단풍'} · {foliage_text.sources(snap)}"
    return Block(paragraph, credit, attachment)


def blossom_block(week_start: dt.date, today: dt.date, scale: int) -> Block | None:
    status = outlook = None
    try:
        status = blossom.fetch_status(today)
    except Exception:
        log.warning("기상청 벚꽃 관측을 받지 못했습니다", exc_info=True)
    try:
        outlook = blossom.fetch_outlook(week_start.year)
    except Exception:
        log.warning("웨더아이 벚꽃 예상을 받지 못했습니다", exc_info=True)
    if status is None and outlook is None:
        log.warning("벚꽃 자료가 없어 벚꽃 소식을 빼고 게시합니다")
        return None

    week_end = week_start + dt.timedelta(days=6)
    paragraph = Paragraph("이번 주 벚꽃", emoji=":cherry_blossom:")
    if status is not None:
        paragraph.add("관측", blossom.observed_line(status))
    # 못 받은 예상은 "아직 나오지 않았습니다" 로 둘러대지 않고 뺌
    if outlook is not None:
        paragraph.add("이번 주", blossom.week_line(outlook, week_start, week_end))
        paragraph.add("올해" if outlook.expected else "평년", blossom.year_line(outlook))
    return Block(paragraph, f"벚꽃 · {blossom.sources(status, outlook)}")


@dataclass(frozen=True)
class Theme:
    name: str
    in_season: Callable[[dt.date], bool]
    build: Callable[[dt.date, dt.date, int], Block | None]


THEMES: tuple[Theme, ...] = (
    Theme("단풍", foliage.in_season, foliage_block),
    Theme("벚꽃", blossom.in_season, blossom_block),
)


def blocks_for(week_start: dt.date, today: dt.date, scale: int) -> list[Block]:
    """그 주(월요일 기준)에 든 철의 덩어리."""
    return [block for theme in THEMES
            if theme.in_season(week_start) and (block := theme.build(week_start, today, scale))]
