"""첫눈 문장 — 지도(HTML)와 슬랙 답이 함께 씀."""
from __future__ import annotations

import datetime as dt

from src.common.text import short_date, short_day_label
from src.season.snow import HEADLINE, Status, gap_days, normal_of
from src.season.stations import BY_NAME, STATIONS, Station

SOURCE = "기상청 기상자료개방포털 계절관측"


def _html_bold(text: str) -> str:
    return f"<b>{text}</b>"


def gap_text(station: Station, day: dt.date) -> str:
    gap = gap_days(station, day)
    if gap is None:
        return ""
    return "평년과 같음" if gap == 0 else f"평년보다 {abs(gap)}일 {'늦음' if gap > 0 else '빠름'}"


def waiting_text(station: Station, status: Status) -> str:
    """아직인 곳 — 평년과 지난겨울. 둘 다 없으면 빈 문자열."""
    bits = []
    if normal := normal_of(station, status.year):
        bits.append(f"평년 {short_date(normal)}")
    if last := status.last.get(station.name):
        bits.append(f"지난겨울 {short_date(last)}")
    return ", ".join(bits)


def season_text(status: Status) -> str:
    return f"{status.year}~{(status.year + 1) % 100:02d}년 겨울"


def sources(status: Status | None = None, *, detail: bool = False) -> str:
    text = f"관측 {SOURCE} · 평년 1991~2020"
    return f"{text} ({season_text(status)})" if detail and status else text


def observed_line(status: Status, bold=_html_bold) -> str:
    """관측 한 줄 — 관측된 곳이 적으면 이름·날짜, 많으면 개수·최근. 서울이 아직이면 그 평년을 덧붙임."""
    seen = sorted(((d, BY_NAME[n]) for n, d in status.first.items() if n in BY_NAME), key=lambda e: e[0])
    head = BY_NAME[HEADLINE]
    # 조사를 붙이지 않음 — 닫는 별표 바로 뒤에 글자가 붙으면 슬랙이 굵게로 읽지 않음
    waiting = "" if HEADLINE in status.first else f"{bold(HEADLINE)} 아직 ({waiting_text(head, status)})"
    if not seen:
        return f"아직 첫눈이 관측된 곳이 없습니다 — {waiting}"

    def event(e) -> str:
        day, st = e
        gap = gap_text(st, day)
        return f"{bold(st.name)} {short_date(day)}" + (f" ({gap})" if gap else "")

    rest = len(STATIONS) - len(seen)
    if len(seen) <= 2:
        text = " · ".join(event(e) for e in seen) + (f", 나머지 {rest}곳은 아직" if rest else "")
    else:
        text = (f"{len(seen)}곳 관측 · {rest}곳 아직 — 최근 "
                + " · ".join(event(e) for e in reversed(seen[-2:])))
    return f"{text} / {waiting}" if waiting else text


def snow_days(days) -> list[dt.date]:
    """하늘상태에 눈이 든 날 — «비/눈» 도 셈(진눈깨비도 첫눈으로 관측함)."""
    return [d.date for d in days if "눈" in (d.sky or "")]


def week_line(status: Status, days, start: dt.date, end: dt.date,
              muted=lambda s: f'<span class="muted">{s}</span>') -> str:
    snowy = [d for d in snow_days(days) if start <= d <= end]
    if not snowy:
        return "예보에 눈 소식이 없습니다"
    text = " · ".join(short_day_label(d) for d in snowy) + " 눈 예보"
    # 아직인 곳이 남았을 때만 — 예보 구역 전체의 눈이라 어느 지점일지는 말하지 않음
    return f"{text} {muted('(첫눈이 될 수 있음)')}" if len(status.first) < len(STATIONS) else text
