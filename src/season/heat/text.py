"""폭염·열대야 문장 — 주간 게시의 «이번 주 더위» 문단과 더위 지도 머리 줄이 같은 말을 씀."""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from src.common.text import bold, short_day_label
from src.season.heat.data import HEAT_DAY, TROPICAL_NIGHT, Heat, Picked, peak

FORECAST_SOURCE = "기상청 예보 통보문·중기예보"
SOURCES = f"{FORECAST_SOURCE} · 기준 기상청 기후통계 폭염일수·열대야일수"
HOT_LABEL = f"폭염 기준({HEAT_DAY:.0f}℃↑)"
NIGHT_LABEL = f"열대야 기준({TROPICAL_NIGHT:.0f}℃↑)"

Style = Callable[[str], str]     # 굵게 — 슬랙(mrkdwn)이냐 지도(HTML)냐


def _runs(dates: list[dt.date]) -> list[str]:
    """이어진 날은 «7/19(월)~7/21(수)» 하나로."""
    runs: list[list[dt.date]] = []
    for day in dates:
        if runs and (day - runs[-1][-1]).days == 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    return [short_day_label(r[0]) if len(r) == 1 else f"{short_day_label(r[0])}~{short_day_label(r[-1])}"
            for r in runs]


def span_text(picked: Picked, strong: Style = bold) -> str:
    """«*7/19(월)~7/25(일)* 7일 · 최고 38℃ 7/24(토)» — 하루면 «*7/21(수)* 36℃». 날마다의 값은 늘어놓지 않음."""
    top_day, top = peak(picked)
    runs = " · ".join(strong(r) for r in _runs([day for day, _ in picked]))
    if len(picked) == 1:
        return f"{runs} {top:.0f}℃"
    return f"{runs} {len(picked)}일 · 최고 {top:.0f}℃ {short_day_label(top_day)}"


def hot_line(heat: Heat, strong: Style = bold) -> str:
    """값은 지역 분포의 위쪽 끝이라 «일부 지역». 없으면 빈 문자열."""
    return f"{span_text(heat.hot, strong)} (일부 지역 낮 최고)" if heat.hot else ""


def night_line(heat: Heat, strong: Style = bold) -> str:
    # 아침 최저는 전날 밤부터 그날 아침까지의 최저 — 기상청 열대야의 밤(18:01~익일 09:00)에 가장 가까운 값
    return f"{span_text(heat.tropical, strong)} (일부 지역 아침 최저)" if heat.tropical else ""
