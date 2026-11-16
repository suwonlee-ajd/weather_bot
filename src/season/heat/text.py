"""폭염·열대야 문장 — 주간 게시의 «이번 주 더위» 문단."""
from __future__ import annotations

from src.common.text import bold, short_day_label
from src.season.heat.data import HEAT_DAY, TROPICAL_NIGHT, Heat, Picked

SOURCES = "기상청 예보 통보문·중기예보 · 기준 기상청 기후통계 폭염일수·열대야일수"
HOT_LABEL = f"폭염 기준({HEAT_DAY:.0f}℃↑)"
NIGHT_LABEL = f"열대야 기준({TROPICAL_NIGHT:.0f}℃↑)"


def _days_text(picked: Picked) -> str:
    return " · ".join(f"{bold(short_day_label(day))} {value:.0f}℃" for day, value in picked)


def hot_line(heat: Heat) -> str:
    """«*7/21(화)* 34℃ · *7/22(수)* 35℃ (일부 지역 낮 최고)». 없으면 빈 문자열."""
    return f"{_days_text(heat.hot)} (일부 지역 낮 최고)" if heat.hot else ""


def night_line(heat: Heat) -> str:
    # 아침 최저는 전날 밤부터 그날 아침까지의 최저 — 기상청 열대야의 밤(18:01~익일 09:00)에 가장 가까운 값
    return f"{_days_text(heat.tropical)} (일부 지역 아침 최저)" if heat.tropical else ""
