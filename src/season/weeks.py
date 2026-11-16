"""주의 시작(월요일) — 주간 게시·조회·멘션이 함께 씀."""
from __future__ import annotations

import datetime as dt


def week_start_of(day: dt.date, week_offset: int = 0) -> dt.date:
    """day 가 든 주의 월요일에서 week_offset 주 뒤."""
    return day - dt.timedelta(days=day.weekday()) + dt.timedelta(weeks=week_offset)

