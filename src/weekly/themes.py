"""철마다 주간 게시에 붙이는 소식(테마).

테마 하나는 «다루는 기간» 과 «덩어리(paragraph.Block)를 조립하는 함수» 의 짝.
게시물에 넣고 슬랙 글로 옮기는 일은 post.py 와 paragraph.py 가 맡음.

자료로만 조립하고 모델에 맡기지 않음 — 개화일·단풍일을 지어내면 그럴듯해 보여서
알아채기 어려움. 못 만들어도 날씨 게시는 그대로 나감. 테마는 덤이고, 날씨가 빠지면
게시물의 이유가 없어짐.

  단풍  9월 둘째 주 ~ 11월 둘째 주      관측 기상청 · 예상 웨더아이 + 지도
  벚꽃  2월 마지막 주 ~ 3월 마지막 주   관측 기상청 · 예상 웨더아이  (문단 구성은 2027 시즌 전에 다시 봄)
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.season import blossom
from src.season import foliage
from src.season import foliage_map as render_foliage
from src.weekly.paragraph import Attachment, Block, Paragraph, bold

log = logging.getLogger(__name__)


def foliage_block(week_start: dt.date, today: dt.date, scale: int) -> Block | None:
    """단풍 — 관측 · 이번 주 예상 두 줄과 지도. 지도를 못 그려도 글은 남음."""
    try:
        snap = foliage.fetch_snapshot(today)
    except Exception:
        log.warning("단풍 현황을 받지 못해 단풍 소식을 빼고 게시합니다", exc_info=True)
        return None
    week_end = week_start + dt.timedelta(days=6)
    paragraph = (Paragraph("이번 주 단풍", emoji=":maple_leaf:")
                 .add("관측", render_foliage.observed_line(snap, bold))
                 .add("이번 주", render_foliage.week_line(snap, week_start, week_end, bold,
                                                         muted=lambda s: s)))
    attachment = None
    try:
        png = render_foliage.render_png(snap, week_start, scale=scale)
        attachment = Attachment("foliage", png, "단풍 지도",
                                "전국 21개 명산의 단풍 현황(기상청)과 예상 시기(웨더아이) 지도")
        log.info("단풍 지도 %s bytes", f"{len(png):,}")
    except Exception:
        log.warning("단풍 지도를 만들지 못해 글로만 붙입니다", exc_info=True)
    # 출처는 실린 것에 맞춤 — 예상을 못 읽었으면 글에도 지도에도 예상이 없음
    credit = f"{'단풍 지도' if attachment else '단풍'} · {render_foliage.sources(snap)}"
    return Block(paragraph, credit, attachment)


def blossom_block(week_start: dt.date, today: dt.date, scale: int) -> Block | None:
    """벚꽃 — 관측 · 이번 주 예상 · 올해(평년) 세 줄. 관측과 예상은 따로 받아, 받은 쪽 줄만 넣음."""
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
    # 예상을 못 받았으면 줄을 뺌 — "아직 나오지 않았습니다" 로 둘러대지 않음
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
    """그 주(월요일 기준)에 든 철의 덩어리. 철이 아니면 자료도 부르지 않음."""
    return [block for theme in THEMES
            if theme.in_season(week_start) and (block := theme.build(week_start, today, scale))]
