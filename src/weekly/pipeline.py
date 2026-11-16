"""영역들을 동시에 돌려 게시물 하나로 합침(종합). 1번 날씨만 필수 — 나머지는 실패·해당 없음이면 빠짐.

  1 날씨(본문)  카드  2 일기도  3 벚꽃  5 단풍  6 첫눈     ← 게시물에 실리는 순서 (4 태풍은 아직 없음)
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from src.common.config import Config
from src.weekly import sections, themes
from src.weekly.forecast import ForecastError, WeekForecast
from src.weekly.paragraph import Attachment, Block, Message
from src.weekly.sections import SECTIONS_TIMEOUT_SEC, Context, Section, Weather

log = logging.getLogger(__name__)

# 철 소식은 기간을 따로 두지 않음 — 날마다 자료(기상청 서비스 여부·예상일·관측)를 보고 영역이 스스로 빠짐
SECTIONS: tuple[Section, ...] = (
    Section("카드", sections.card_block),
    Section("일기도", sections.chart_block),
    Section("벚꽃", themes.blossom_block),
    Section("단풍", themes.foliage_block),
    Section("첫눈", themes.snow_block),
)


@dataclass
class Post:
    """슬랙에 올릴 한 건 — 첨부는 영역 순서(카드 → 일기도 → 지도)."""
    week: WeekForecast
    text: str
    attachments: list[Attachment]


def compose(cfg: Config, now: dt.datetime, week_offset: int = 0, *, can_render: bool = True) -> Post | None:
    """None 이면 게시를 건너뜀 (날씨 실패)."""
    base = Context(cfg, now, week_offset, can_render)
    started = time.monotonic()
    # with 를 쓰지 않음 — 기한을 넘긴 영역을 기다리지 않고 게시하려고 shutdown(wait=False)
    pool = ThreadPoolExecutor(max_workers=len(SECTIONS) + 1, thread_name_prefix="weekly")
    try:
        weather_f = pool.submit(sections.weather, base)
        ctx = dataclasses.replace(base, weather=weather_f)
        futures = [pool.submit(_build, s, ctx) for s in SECTIONS]

        weather = _weather(weather_f)
        if weather is None:
            return None
        left = max(0.0, SECTIONS_TIMEOUT_SEC - (time.monotonic() - started))
        wait(futures, timeout=left)
        blocks = [b for s, f in zip(SECTIONS, futures, strict=True) if (b := _result(s, f))]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return merge(weather, blocks)


def _weather(future: Future) -> Weather | None:
    wait([future], timeout=SECTIONS_TIMEOUT_SEC)
    if not future.done():
        log.error("날씨 영역이 %d초 안에 끝나지 않았습니다", SECTIONS_TIMEOUT_SEC)
    else:
        try:
            return future.result()
        except ForecastError as exc:
            log.error("%s", exc)
        except Exception:
            log.exception("날씨 영역 실패")
    log.error("지어낸 날씨를 올리지 않기 위해 게시를 건너뜁니다.")
    return None


def _build(section: Section, ctx: Context) -> Block | None:
    """영역의 경계 — 무엇이 실패하든 그 영역만 빠짐."""
    started = time.monotonic()
    try:
        block = section.build(ctx)
    except Exception:
        log.warning("%s 영역 실패 — 이 영역은 빠짐 (%.1f초)", section.name, time.monotonic() - started,
                    exc_info=True)
        return None
    log.info("%s 영역 %s (%.1f초)", section.name, "완료" if block else "해당 없음", time.monotonic() - started)
    return block


def _result(section: Section, future: Future) -> Block | None:
    if not future.done():
        log.warning("%s 영역이 %d초 안에 끝나지 않아 빼고 게시합니다", section.name, SECTIONS_TIMEOUT_SEC)
        return None
    return future.result()


def merge(weather: Weather, blocks: list[Block]) -> Post:
    """본문 → 문단 → 출처 줄, 첨부는 영역 순서. 글도 그림도 없는 덩어리는 출처까지 빠짐."""
    message = Message(weather.body)
    for block in blocks:
        message.add(block)
    return Post(weather.week, message.to_slack(), message.attachments)
