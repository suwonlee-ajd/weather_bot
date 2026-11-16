"""폭염·열대야 — 따로 받지 않고 그 주 예보의 기온 분포와 예보관 서술에서 기상청 기준에 닿는 날을 고름."""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from src.season.narrative import mentioning

# 기상청 기상자료개방포털 기후통계 정의 — 폭염일수 «일 최고기온이 33℃ 이상인 날», 열대야일수 «밤최저기온이
# 25℃ 이상인 날(밤: 당일 18:01~익일 09:00)». 폭염특보는 체감온도 기준이라 다름 — 특보는 예보관 서술로만 전함
HEAT_DAY = 33.0
TROPICAL_NIGHT = 25.0
WORDS = ("폭염", "열대야")

Picked = list[tuple[dt.date, float]]


@dataclass(frozen=True)
class City:
    """도시 하나 — 도시별 값이 있는 날(중기예보 구간)만 봄. 값이 같으면 이른 날."""
    name: str
    high: tuple[dt.date, float]     # 그 날들의 낮 최고 중 가장 높은 값과 그날
    low: tuple[dt.date, float]      # 아침 최저 중 가장 높은 값과 그날

    @property
    def hot(self) -> bool:
        return self.high[1] >= HEAT_DAY

    @property
    def tropical(self) -> bool:
        return self.low[1] >= TROPICAL_NIGHT


@dataclass(frozen=True)
class Heat:
    """기온은 지역 분포의 위쪽 끝(tmax_hi · tmin_hi) — 기준에 닿는 곳이 «일부 지역» 이라는 뜻."""
    hot: Picked             # 낮 최고가 33℃ 이상인 곳이 있는 날
    tropical: Picked        # 아침 최저가 25℃ 이상인 곳이 있는 날
    mentioned: list[str]    # 예보관 서술 중 폭염·열대야가 든 줄
    cities: list[City] = field(default_factory=list)            # 표에 나온 차례(대체로 북 → 남)
    city_days: list[dt.date] = field(default_factory=list)      # 도시별 값이 있는 날

    @property
    def showing(self) -> bool:
        """다룰 때인지 — 기간 없이, 기준에 닿는 날이나 예보관 언급이 있을 때만."""
        return bool(self.hot or self.tropical or self.mentioned)


def _reaching(days: Sequence, field_name: str, threshold: float) -> Picked:
    return [(d.date, v) for d in days if (v := getattr(d, field_name)) is not None and v >= threshold]


def peak(picked: Picked) -> tuple[dt.date, float]:
    """가장 높은 값과 그날 — 날짜순으로 받아 같으면 이른 날(max 는 처음 것을 돌려줌)."""
    return max(picked, key=lambda p: p[1])


def _by_city(days: Sequence) -> list[City]:
    lows: dict[str, Picked] = {}
    highs: dict[str, Picked] = {}
    for d in sorted(days, key=lambda d: d.date):
        for name, (lo, hi) in d.cities.items():
            lows.setdefault(name, []).append((d.date, lo))
            highs.setdefault(name, []).append((d.date, hi))
    return [City(name, peak(highs[name]), peak(lows[name])) for name in highs]


def read(days: Sequence, lines: Iterable[str]) -> Heat:
    """days 는 DayForecast 처럼 date · tmax_hi · tmin_hi · cities 를 가진 것."""
    return Heat(_reaching(days, "tmax_hi", HEAT_DAY), _reaching(days, "tmin_hi", TROPICAL_NIGHT),
                mentioning(lines, WORDS), _by_city(days), [d.date for d in days if d.cities])
