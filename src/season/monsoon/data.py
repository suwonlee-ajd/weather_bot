"""장마 — 예보관 서술의 «장마»·«정체전선» 줄과 그 주 비 예보. 따로 받지 않음.

기상청은 장마 시작·종료일을 철이 끝난 뒤 사후 분석으로 확정함(9월 무렵, 기상자료개방포털 «장마» 통계).
철 중에 받을 수 있는 구조화된 자료가 없어 예보관이 장마·정체전선을 말할 때만 다룸.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from src.season.narrative import mentioning

WORDS = ("장마", "정체전선")
RAIN_WORDS = ("비", "소나기")


@dataclass(frozen=True)
class Monsoon:
    mentioned: list[str]        # 예보관 서술 중 장마·정체전선이 든 줄
    rainy: list[dt.date]        # 하늘상태에 비·소나기가 있거나 강수확률이 문턱 이상인 날

    @property
    def showing(self) -> bool:
        """다룰 때인지 — 기간 없이, 예보관이 장마·정체전선을 말할 때만."""
        return bool(self.mentioned)

    @property
    def named(self) -> bool:
        """예보관이 «장마» 라고 썼는지 — 정체전선은 봄·가을에도 걸려 그것만으로는 장마라 부르지 않음."""
        return any("장마" in text for text in self.mentioned)


def is_rainy(sky: str | None, pop: int | None, pop_at: int) -> bool:
    return (pop or 0) >= pop_at or any(w in (sky or "") for w in RAIN_WORDS)


def read(days: Sequence, lines: Iterable[str], pop_at: int) -> Monsoon:
    """days 는 DayForecast 처럼 date · sky · pop 을 가진 것. pop_at 은 비로 볼 강수확률 —
    본문 조언과 같은 문턱을 부르는 쪽이 넘김(season 은 advice 를 모름)."""
    return Monsoon(mentioning(lines, WORDS), [d.date for d in days if is_rainy(d.sky, d.pop, pop_at)])
