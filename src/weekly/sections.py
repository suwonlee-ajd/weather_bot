"""주간 게시의 영역 — 1번 날씨(본문)는 필수, 카드·일기도부터는 못 만들면 빠짐. 철 소식·태풍(3~6)은 themes.

영역은 서로 기다리지 않음. 날씨 예보를 쓰는 카드 · 장마 · 폭염 · 4번 태풍(예보관 서술) · 6번 눈만 Context.forecast() 로 1번 결과를 받음.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from src.common.config import Config
from src.kma.chart import fetch_latest_chart
from src.season.weeks import week_end_of, week_start_of
from src.weekly.card import render_png
from src.weekly.forecast import WeekForecast, build_week
from src.weekly.paragraph import Attachment, Block
from src.weekly.writer import write

log = logging.getLogger(__name__)

# 개별 요청은 저마다 timeout 이 있음 — 이것은 영역 전체가 늘어질 때의 마지막 한도
SECTIONS_TIMEOUT_SEC = 300


@dataclass
class Weather:
    week: WeekForecast
    body: str


@dataclass(frozen=True)
class Context:
    """영역마다 넘기는 공통 입력. can_render 가 거짓이면(헬스체크의 Chromium 실패) 카드·지도 없이 글만."""
    cfg: Config
    now: dt.datetime
    week_offset: int = 0
    can_render: bool = True
    weather: Future | None = None       # 1번 결과 — 1번 말고 다른 영역에만 채움

    @property
    def today(self) -> dt.date:
        return self.now.date()

    @property
    def week_start(self) -> dt.date:
        return week_start_of(self.today, self.week_offset)

    @property
    def week_end(self) -> dt.date:
        return week_end_of(self.week_start)

    @property
    def scale(self) -> int:
        return self.cfg.card_scale

    def forecast(self) -> WeekForecast | None:
        """1번 날씨의 예보를 기다림. 날씨가 실패했으면 그 예외가 영역 경계(pipeline)로 올라감."""
        if self.weather is None:
            return None
        return self.weather.result(timeout=SECTIONS_TIMEOUT_SEC).week

    def body(self) -> str:
        """1번 날씨의 본문 — 철 소식이 본문이 이미 인용한 예보관 문장을 되풀이하지 않게."""
        if self.weather is None:
            return ""
        return self.weather.result(timeout=SECTIONS_TIMEOUT_SEC).body

    def image(self, slug: str, title: str, alt: str, render: Callable[[], bytes]) -> Attachment | None:
        """다시 만들 수 있는 그림(카드·지도). 못 그리면 None — 글은 남기고 그림만 뺌.

        파일 이름에 그 주 월요일, 보존은 카드와 같게(CARD_KEEP_DAYS).
        """
        if not self.can_render:
            return None
        try:
            png = render()
        except Exception:
            log.warning("그림을 그리지 못해 빼고 게시합니다 — %s", title, exc_info=True)
            return None
        log.info("%s %s bytes", title, f"{len(png):,}")
        return Attachment(png, title, alt, filename=f"{slug}-{self.week_start:%Y%m%d}.png",
                          keep_days=self.cfg.card_keep_days, pattern=f"{slug}-*.png")


@dataclass(frozen=True)
class Section:
    """영역 하나. 다룰 때인지는 build 가 자료를 보고 정함 — 아니면 None(해당 없음)."""
    name: str
    build: Callable[[Context], Block | None]


def weather(ctx: Context) -> Weather:
    """ForecastError 는 그대로 올림 — 지어낸 날씨를 올리지 않게 게시를 건너뜀."""
    week = build_week(ctx.cfg, ctx.now, week_offset=ctx.week_offset)
    for warning in week.warnings:
        log.warning("예보 검증: %s", warning)
    for n in week.narratives:
        stamp = f"{n.issued_at:%m/%d %H시}" if n.issued_at else "발표시각 미상"
        log.info("자료: %s (%s)", n.title, stamp)

    written = write(week, ctx.cfg)
    week.lead, week.sections, week.alerts = written.lead, written.sections, written.alerts
    log.info("특이사항 %d건", len(week.alerts))
    return Weather(week, written.body)


def card_block(ctx: Context) -> Block | None:
    """1번 날씨의 예보·문구로 그린 카드. 글·출처 없이 그림만."""
    week = ctx.forecast()
    att = ctx.image("weekly-weather", f"이번 주 날씨 전망 ({week.area})", "이번 주 기온·강수 전망 요약 카드",
                    lambda: render_png(week, scale=ctx.scale))
    return Block(None, attachment=att) if att else None


def chart_block(ctx: Context) -> Block:
    """글 없이 그림과 출처만. 기상청이 2일치만 보관해 보존을 카드보다 길게 둠."""
    product = ctx.cfg.chart_product
    chart = fetch_latest_chart(product, back=5)
    log.info("일기도 %s (%s bytes)", chart.url, f"{len(chart.png):,}")
    att = Attachment(chart.png, chart.label, f"기상청 {chart.label}", filename=chart.filename,
                     keep_days=ctx.cfg.chart_keep_days, pattern=f"{product}_*.png")
    return Block(None, f"{chart.label} · 기상청", att)
