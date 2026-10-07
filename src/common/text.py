"""날짜·기온 표기와 슬랙 굵게."""
from __future__ import annotations

import datetime as dt

WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")


def day_label(date: dt.date) -> str:
    return f"{date:%m/%d}({WEEKDAY_KO[date.weekday()]})"


def short_date(date: dt.date) -> str:
    return f"{date.month}/{date.day}"


def short_day_label(date: dt.date) -> str:
    return f"{short_date(date)}({WEEKDAY_KO[date.weekday()]})"


def range_text(lo: float | None, hi: float | None) -> str | None:
    if lo is None and hi is None:
        return None
    if lo is None or hi is None or lo == hi:
        return f"{(lo if lo is not None else hi):.0f}℃"
    return f"{lo:.0f}~{hi:.0f}℃"


def bold(text: str) -> str:
    """슬랙 mrkdwn 굵게."""
    return f"*{text}*"
