"""장마 문장 — 주간 게시의 «이번 주 장마» 문단."""
from __future__ import annotations

from src.common.text import bold, short_day_label
from src.season.monsoon.data import Monsoon

# 시작·종료일을 말하지 않는 까닭을 출처에 밝힘 — 읽는 사람이 날짜를 기대하지 않게
SOURCES = "기상청 예보 통보문·중기예보 (장마 시작·종료일은 기상청이 철이 끝난 뒤 확정)"


def title(monsoon: Monsoon) -> str:
    return "이번 주 장마" if monsoon.named else "이번 주 정체전선"


def rain_line(monsoon: Monsoon) -> str:
    """«*7/14(화)* · *7/15(수)*». 예보 구역 전체의 하늘상태라 어느 곳일지는 말하지 않음. 없으면 빈 문자열."""
    return " · ".join(bold(short_day_label(d)) for d in monsoon.rainy)
