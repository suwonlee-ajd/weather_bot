"""벚꽃 문장 — 주간 게시의 관측·이번 주·올해 줄과 출처."""
from __future__ import annotations

import datetime as dt

from src.common.text import bold, short_date
from src.season.blossom.data import STAGES, Outlook, Status
from src.season.sources import OUTLOOK_SOURCE
from src.season.summary import observed_summary

NOT_STARTED_TEXT = "기상청 벚꽃 관측이 아직 시작되지 않았습니다 (해마다 3월부터)"
NOT_PUBLISHED_TEXT = f"올해 개화 예상은 아직 나오지 않았습니다 ({OUTLOOK_SOURCE}, 해마다 2월 말 발표)"


def observed_line(status: Status) -> str:
    """관측 한 줄 — 핀 곳이 적으면 이름·날짜, 많으면 개수·최근 변화."""
    if not status.in_service:
        return NOT_STARTED_TEXT
    events = []   # (날짜 또는 None, 군락지, 단계)
    for name, stage in status.stages.items():
        if stage:
            events.append(((status.full if stage == 2 else status.bloom).get(name), name, stage))
    waiting = len(status.stages) - len(events)
    if not events:
        return f"아직 핀 곳이 없습니다 — {len(status.stages)}곳 모두 개화 전"

    def text(e) -> str:
        day, name, stage = e
        return f"{bold(name)} {STAGES[stage]}" + (f" {short_date(day)}" if day else "")

    counts = [(STAGES[k], sum(1 for e in events if e[2] == k)) for k in (2, 1)]
    tally = " · ".join(f"{label} {n}곳" for label, n in counts if n)
    if waiting:
        tally += f" · 개화 전 {waiting}곳"
    return observed_summary([(e[0], text(e)) for e in events],
                            f"나머지 {waiting}곳은 개화 전" if waiting else "", tally)


def _grouped(days: list[tuple[str, dt.date]]) -> str:
    """[(서귀포, 3/25), (부산, 3/25), (울산, 3/26)] → '*서귀포*·*부산* 3/25 · *울산* 3/26'."""
    by_day: dict[dt.date, list[str]] = {}
    for city, d in days:
        by_day.setdefault(d, []).append(bold(city))
    return " · ".join(f"{'·'.join(cities)} {short_date(d)}" for d, cities in sorted(by_day.items()))


def week_line(outlook: Outlook | None, start: dt.date, end: dt.date) -> str:
    if outlook is None or not outlook.expected:
        return NOT_PUBLISHED_TEXT
    week = [(c, d) for c, d in outlook.expected.items() if start <= d <= end]
    if week:
        return f"개화 {_grouped(week)} (예상)"
    ahead = sorted(((c, d) for c, d in outlook.expected.items() if d > end), key=lambda x: x[1])
    if not ahead:
        return "개화가 예상된 곳이 없습니다"
    first = ahead[0][1]
    return f"개화 예상 없음 · 다음은 {_grouped([x for x in ahead if x[1] == first])} (예상)"


def year_line(outlook: Outlook | None) -> str:
    """평년보다 이른지 늦은지. 올해 예상이 없으면 평년 개화일."""
    if outlook is None or not outlook.normal:
        return ""
    seoul_normal = outlook.normal.get("서울")
    if not outlook.expected:
        first_city, first_day = min(outlook.normal.items(), key=lambda x: x[1])
        line = f"{bold(first_city)} {short_date(first_day)} 무렵 시작해"
        return line + (f" {bold('서울')} {short_date(seoul_normal)} 무렵 핍니다" if seoul_normal else " 북상합니다")
    gap = outlook.gap_days()
    if gap is None:
        return ""
    days = int(abs(gap) + 0.5)             # 사사오입 — round() 는 2.5 를 2 로 내림
    trend = ("평년과 비슷하겠습니다" if days == 0
             else f"평년보다 {days}일가량 {'이르겠습니다' if gap < 0 else '늦겠습니다'}")
    seoul = outlook.expected.get("서울")
    if seoul and seoul_normal:
        trend += f" (서울 {short_date(seoul)}, 평년 {short_date(seoul_normal)})"
    return trend


def sources(status: Status | None, outlook: Outlook | None) -> str:
    bits = ["관측 기상청 날씨누리"] if status is not None else []
    if outlook is not None:
        if outlook.expected:
            bits.append(f"예상 {OUTLOOK_SOURCE}" + (f"({short_date(outlook.published)} 발표)" if outlook.published else ""))
        else:
            bits.append(f"평년 {OUTLOOK_SOURCE}")
    return " · ".join(bits)
