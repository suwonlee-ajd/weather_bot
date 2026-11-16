"""벚꽃 문장 — 주간 게시의 이번 주·올해 줄과 출처. bold 로 슬랙(기본)·지도(HTML)를 가름."""
from __future__ import annotations

import datetime as dt

from src.common.text import bold, short_date
from src.season.blossom.data import Outlook
from src.season.sources import OUTLOOK_SOURCE

NOT_PUBLISHED_TEXT = f"올해 개화 예상은 아직 나오지 않았습니다 ({OUTLOOK_SOURCE}, 해마다 2월 말 발표)"


def _grouped(days: list[tuple[str, dt.date]], bold=bold) -> str:
    """[(서귀포, 3/25), (부산, 3/25), (울산, 3/26)] → '*서귀포*·*부산* 3/25 · *울산* 3/26'."""
    by_day: dict[dt.date, list[str]] = {}
    for city, d in days:
        by_day.setdefault(d, []).append(bold(city))
    return " · ".join(f"{'·'.join(cities)} {short_date(d)}" for d, cities in sorted(by_day.items()))


def week_line(outlook: Outlook, start: dt.date, end: dt.date, bold=bold) -> str:
    if not outlook.expected:
        return NOT_PUBLISHED_TEXT
    week = [(c, d) for c, d in outlook.expected.items() if start <= d <= end]
    if week:
        return f"개화 {_grouped(week, bold)} (예상)"
    ahead = sorted(((c, d) for c, d in outlook.expected.items() if d > end), key=lambda x: x[1])
    if not ahead:
        return "개화가 예상된 곳이 없습니다"
    first = ahead[0][1]
    return f"개화 예상 없음 · 다음은 {_grouped([x for x in ahead if x[1] == first], bold)} (예상)"


def year_line(outlook: Outlook, bold=bold) -> str:
    """평년보다 이른지 늦은지. 올해 예상이 없으면 평년 개화일."""
    if not outlook.normal:
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


def sources(outlook: Outlook, *, detail: bool = False) -> str:
    """출처 한 줄. detail 은 지도 꼬리말용(도시 수 · 지난해 표인지까지)."""
    if not outlook.expected:
        return f"평년 {OUTLOOK_SOURCE}" + (" 지난해 표" if detail else "")
    bits = [f"{short_date(outlook.published)} 발표"] if outlook.published else []
    if detail:
        return f"예상 {OUTLOOK_SOURCE} ({', '.join([*bits, f'{len(outlook.expected)}개 도시'])})"
    return f"예상 {OUTLOOK_SOURCE}" + (f"({bits[0]})" if bits else "")
