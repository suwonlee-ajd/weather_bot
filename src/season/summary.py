"""철 소식의 관측 한 줄 꼴 — 단풍·첫눈·벚꽃이 같은 규칙으로 줄임."""
from __future__ import annotations

import datetime as dt


def observed_summary(events: list[tuple[dt.date | None, str]], rest: str, tally: str) -> str:
    """둘 이하면 이름·날짜를 날짜순으로(rest 는 «나머지 N곳은 …»), 많으면 개수(tally)와 최근 둘."""
    def latest(e: tuple[dt.date | None, str]) -> dt.date:
        return e[0] or dt.date.min

    if len(events) <= 2:
        head = " · ".join(text for _, text in sorted(events, key=latest))
        return f"{head}, {rest}" if rest else head
    return f"{tally} — 최근 " + " · ".join(text for _, text in sorted(events, key=latest, reverse=True)[:2])
