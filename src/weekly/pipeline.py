"""영역들을 동시에 돌려 게시물 하나로 합침(종합). 1번 날씨만 필수 — 나머지는 실패·해당 없음이면 빠짐.

  1 날씨(+카드)  2 일기도  3 벚꽃  5 단풍  6 첫눈     ← 게시물에 실리는 순서 (4 태풍은 아직 없음)
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from src.common.config import Config
from src.season.blossom import data as blossom
from src.season.foliage import data as foliage
from src.season.snow import data as snow
from src.weekly import sections, themes
from src.weekly.forecast import ForecastError, WeekForecast
from src.weekly.paragraph import Attachment, Block, Message
from src.weekly.sections import SECTIONS_TIMEOUT_SEC, Context, Section, Weather, always

log = logging.getLogger(__name__)

SECTIONS: tuple[Section, ...] = (
    Section("일기도", always, sections.chart_block),
    Section("벚꽃", blossom.in_season, themes.blossom_block),
    Section("단풍", foliage.in_season, themes.foliage_block),
    Section("첫눈", snow.in_weekly_season, themes.snow_block),
)


@dataclass
class Post:
    """슬랙에 올릴 한 건 — 첨부는 카드 → 일기도 → 지도 순."""
    week: WeekForecast
    text: str
    attachments: list[Attachment] = field(default_factory=list)


def compose(cfg: Config, now: dt.datetime, week_offset: int = 0, *, can_render: bool = True) -> Post | None:
    """None 이면 게시를 건너뜀 (날씨 실패)."""
    base = Context(cfg, now, week_offset, can_render)
    started = time.monotonic()
    # with 를 쓰지 않음 — 기한을 넘긴 영역을 기다리지 않고 게시하려고 shutdown(wait=False)
    pool = ThreadPoolExecutor(max_workers=len(SECTIONS) + 1, thread_name_prefix="weekly")
    try:
        weather_f = pool.submit(sections.weather, base)
        ctx = dataclasses.replace(base, weather=weather_f)
        active = [s for s in SECTIONS if s.in_season(ctx.week_start)]
        log.info("영역: 날씨 · %s", " · ".join(s.name for s in active) or "(철 소식 없음)")
        futures = [pool.submit(_build, s, ctx) for s in active]

        weather = _weather(weather_f)
        if weather is None:
            return None
        left = max(0.0, SECTIONS_TIMEOUT_SEC - (time.monotonic() - started))
        wait(futures, timeout=left)
        blocks = [_result(s, f) for s, f in zip(active, futures, strict=True)]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return merge(weather, blocks)


def _weather(future: Future) -> Weather | None:
    try:
        return future.result(timeout=SECTIONS_TIMEOUT_SEC)
    except ForecastError as exc:
        log.error("%s", exc)
    except Exception:
        # 기한 초과도 TimeoutError 지만 영역 안에서 난 TimeoutError 와 가르려고 done() 으로 봄
        if future.done():
            log.exception("날씨 영역 실패")
        else:
            log.error("날씨 영역이 %d초 안에 끝나지 않았습니다", SECTIONS_TIMEOUT_SEC)
    log.error("지어낸 날씨를 올리지 않기 위해 게시를 건너뜁니다.")
    return None


def _build(section: Section, ctx: Context) -> Block | None:
    """영역의 경계 — 무엇이 실패하든 그 영역만 빠짐."""
    started = time.monotonic()
    try:
        block = section.build(ctx)
    except Exception:
        log.warning("%s 영역을 만들지 못해 빼고 게시합니다 (%.1f초)", section.name, time.monotonic() - started,
                    exc_info=True)
        return None
    log.info("%s 영역 %s (%.1f초)", section.name, "완료" if block else "해당 없음", time.monotonic() - started)
    return block


def _result(section: Section, future: Future) -> Block | None:
    if not future.done():
        log.warning("%s 영역이 %d초 안에 끝나지 않아 빼고 게시합니다", section.name, SECTIONS_TIMEOUT_SEC)
        return None
    return future.result()


def merge(weather: Weather, blocks: list[Block | None]) -> Post:
    """본문 → 문단 → 출처 줄. 빈 결과(None·빈 문단)는 출처까지 빠짐."""
    message = Message(weather.body)
    for block in blocks:
        if block is not None:
            message.add(block)
    card = [weather.card] if weather.card else []
    return Post(weather.week, message.to_slack(), card + message.attachments)
