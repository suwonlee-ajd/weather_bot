"""폭염·열대야 — 따로 받지 않고 그 주 예보의 기온 분포와 예보관 서술에서 기상청 기준에 닿는 날을 고름."""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from src.season.narrative import mentioning

# 기상청 기상자료개방포털 기후통계 정의 — 폭염일수 «일 최고기온이 33℃ 이상인 날», 열대야일수 «밤최저기온이
# 25℃ 이상인 날(밤: 당일 18:01~익일 09:00)». 폭염특보는 체감온도 기준이라 다름 — 특보는 예보관 서술로만 전함
HEAT_DAY = 33.0
TROPICAL_NIGHT = 25.0
WORDS = ("폭염", "열대야")

Picked = list[tuple[dt.date, float]]


@dataclass(frozen=True)
class Heat:
    """기온은 지역 분포의 위쪽 끝(tmax_hi · tmin_hi) — 기준에 닿는 곳이 «일부 지역» 이라는 뜻."""
    hot: Picked             # 낮 최고가 33℃ 이상인 곳이 있는 날
    tropical: Picked        # 아침 최저가 25℃ 이상인 곳이 있는 날
    mentioned: list[str]    # 예보관 서술 중 폭염·열대야가 든 줄

    @property
    def showing(self) -> bool:
        """다룰 때인지 — 기간 없이, 기준에 닿는 날이나 예보관 언급이 있을 때만."""
        return bool(self.hot or self.tropical or self.mentioned)


def _reaching(days: Sequence, field: str, threshold: float) -> Picked:
    return [(d.date, v) for d in days if (v := getattr(d, field)) is not None and v >= threshold]


def read(days: Sequence, lines: Iterable[str]) -> Heat:
    """days 는 DayForecast 처럼 date · tmax_hi · tmin_hi 를 가진 것."""
    return Heat(_reaching(days, "tmax_hi", HEAT_DAY), _reaching(days, "tmin_hi", TROPICAL_NIGHT),
                mentioning(lines, WORDS))
