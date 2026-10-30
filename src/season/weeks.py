"""철 기간의 경계 — 어느 철이든 월요일에 시작하고 그 주 일요일에 끝남(주간 게시가 월요일)."""
from __future__ import annotations

import datetime as dt


def first_monday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(7 - first.weekday()) % 7)


def last_monday(year: int, month: int) -> dt.date:
    last = dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)
    return last - dt.timedelta(days=last.weekday())
