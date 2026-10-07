"""기상청 페이지에서 긁은 값으로 이번 주(월~일) 예보를 조립함.

페이지 구조가 바뀌면 엉뚱한 값이 잡힐 수 있어, 범위 밖 값은 버리고 7일 중 절반 이상 비면 게시를 포기함.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from src.common.config import KST
from src.common.text import WEEKDAY_KO, day_label, range_text
from src.kma.page import Narrative, ScrapeError
from src.kma.regions import Region, find_region
from src.kma.scrape import scrape_week

log = logging.getLogger(__name__)

TEMP_RANGE = (-35.0, 45.0)  # 한반도에서 물리적으로 가능한 범위
MAX_BAD_DAYS = 3


@dataclass
class Source:
    title: str
    url: str


@dataclass
class Section:
    label: str
    period: str
    text: str
    sources: list[Source] = field(default_factory=list)


@dataclass
class DayForecast:
    """하루치 예보. 기온은 지역 간 분포 범위임 — 전국 "아침 14~22℃" 가 (tmin_lo, tmin_hi)."""

    date: dt.date
    tmin_lo: float | None = None
    tmin_hi: float | None = None
    tmax_lo: float | None = None
    tmax_hi: float | None = None
    sky: str | None = None
    pop: int | None = None
    source: str = ""

    @property
    def weekday_ko(self) -> str:
        return WEEKDAY_KO[self.date.weekday()]

    @property
    def is_complete(self) -> bool:
        return self.tmin_lo is not None and self.tmax_hi is not None

    _range_text = staticmethod(range_text)

    @property
    def morning_text(self) -> str | None:
        return self._range_text(self.tmin_lo, self.tmin_hi)

    @property
    def noon_text(self) -> str | None:
        return self._range_text(self.tmax_lo, self.tmax_hi)

    @property
    def tmin_mid(self) -> float | None:
        vals = [v for v in (self.tmin_lo, self.tmin_hi) if v is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def tmax_mid(self) -> float | None:
        vals = [v for v in (self.tmax_lo, self.tmax_hi) if v is not None]
        return sum(vals) / len(vals) if vals else None

    def as_line(self) -> str:
        morning, noon = self.morning_text, self.noon_text
        temp = f"아침 {morning} / 낮 {noon}" if morning and noon else "기온 정보 없음"
        pop = f", 강수확률 {self.pop}%" if self.pop is not None else ""
        tail = f"  [{self.source}]" if self.source else ""
        return f"{day_label(self.date)} {temp}, {self.sky or '하늘상태 정보 없음'}{pop}{tail}"


@dataclass
class WeekForecast:
    area: str
    week_start: dt.date
    days: list[DayForecast]
    narratives: list[Narrative] = field(default_factory=list)
    lead: str = ""
    sections: list[Section] = field(default_factory=list)
    alerts: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def week_end(self) -> dt.date:
        return self.week_start + dt.timedelta(days=6)

    @property
    def sources(self) -> list[Source]:
        return [Source(n.title, n.url) for n in self.narratives]

    @property
    def morning_range(self) -> tuple[float, float] | None:
        vals = [v for d in self.days for v in (d.tmin_lo, d.tmin_hi) if v is not None]
        return (min(vals), max(vals)) if vals else None

    @property
    def noon_range(self) -> tuple[float, float] | None:
        vals = [v for d in self.days for v in (d.tmax_lo, d.tmax_hi) if v is not None]
        return (min(vals), max(vals)) if vals else None

    def as_digest(self) -> str:
        head = (
            f"지역: {self.area}\n"
            f"기간: {self.week_start:%Y-%m-%d}(월) ~ {self.week_end:%m-%d}(일)\n"
            f"※ 기온은 지역 간 분포 범위입니다.\n"
        )
        body = "\n".join(d.as_line() for d in self.days)
        official = "\n\n".join(
            f"[{n.title}{f' ({n.issued_at:%m월 %d일 %H시} 발표)' if n.issued_at else ''}]\n{n.text}"
            for n in self.narratives
        )
        return "\n".join([head, body, "", official]).strip()


class ForecastError(RuntimeError):
    pass


def _valid(value: float | None) -> float | None:
    if value is None:
        return None
    return value if TEMP_RANGE[0] <= value <= TEMP_RANGE[1] else None


def build_week(
    cfg,
    now: dt.datetime | None = None,
    *,
    region: Region | None = None,
    week_offset: int = 0,
) -> WeekForecast:
    now = now or dt.datetime.now(tz=KST)
    week_start = now.date() - dt.timedelta(days=now.weekday()) + dt.timedelta(weeks=week_offset)

    if region is None:
        region = find_region(getattr(cfg, "region", None) or "전국")
        if region is None:
            raise ForecastError(f"알 수 없는 지역입니다: {cfg.region}")
    area = getattr(cfg, "area_label", "") or region.label

    try:
        scrape = scrape_week(now, week_start, region)
    except ScrapeError as exc:
        raise ForecastError(str(exc)) from exc

    days: list[DayForecast] = []
    warnings: list[str] = []
    for offset in range(7):
        date = week_start + dt.timedelta(days=offset)
        raw = scrape.days.get(date)
        if raw is None:
            warnings.append(f"{date:%m/%d} 예보 없음")
            days.append(DayForecast(date=date))
            continue

        tmin_lo, tmin_hi = _valid(raw.tmin_lo), _valid(raw.tmin_hi)
        tmax_lo, tmax_hi = _valid(raw.tmax_lo), _valid(raw.tmax_hi)
        if None not in (tmin_lo, tmin_hi) and tmin_lo > tmin_hi:
            tmin_lo, tmin_hi = tmin_hi, tmin_lo
            warnings.append(f"{date:%m/%d} 아침 기온 범위가 뒤집혀 바로잡았습니다")
        if None not in (tmax_lo, tmax_hi) and tmax_lo > tmax_hi:
            tmax_lo, tmax_hi = tmax_hi, tmax_lo
            warnings.append(f"{date:%m/%d} 낮 기온 범위가 뒤집혀 바로잡았습니다")

        pop = raw.pop if raw.pop is None or 0 <= raw.pop <= 100 else None
        days.append(
            DayForecast(
                date=date,
                tmin_lo=tmin_lo,
                tmin_hi=tmin_hi,
                tmax_lo=tmax_lo,
                tmax_hi=tmax_hi,
                sky=raw.sky,
                pop=pop,
                source=raw.source,
            )
        )

    incomplete = [d for d in days if not d.is_complete]
    if len(incomplete) > MAX_BAD_DAYS:
        missing = ", ".join(f"{d.date:%m/%d}" for d in incomplete)
        # 지난 날짜는 기상청이 예보를 내리지 않아 비는 게 정상 — 파서 고장과 구분함
        today = now.date()
        future = [d for d in incomplete if d.date >= today]
        cause = (
            "기상청 페이지 구조가 바뀌었을 수 있습니다."
            if future
            else f"지난 날짜라 예보가 없습니다 — 주 중간 실행이면 정상입니다 (오늘 {today:%m/%d})."
        )
        raise ForecastError(
            f"7일 중 {len(incomplete)}일의 기온을 얻지 못해 신뢰할 수 없습니다 ({missing}). {cause}"
        )

    return WeekForecast(
        area=area,
        week_start=week_start,
        days=days,
        narratives=scrape.narratives,
        warnings=warnings,
    )
