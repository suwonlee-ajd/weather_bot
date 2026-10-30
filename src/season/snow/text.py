"""첫눈 문장 — 지도(HTML)와 슬랙 답이 함께 씀."""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence

from src.common.text import html_bold, html_muted, short_date, short_day_label
from src.season.snow.data import HEADLINE, Status, gap_days, normal_of
from src.season.snow.stations import BY_NAME, STATIONS, Station
from src.season.summary import observed_summary

SOURCES = "관측 기상청 기상자료개방포털 계절관측 · 평년 1991~2020"

Style = Callable[[str], str]     # 굵게·흐리게 — 슬랙(mrkdwn)이냐 지도(HTML)냐


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


def station_text(station: Station, status: Status, bold: Style = html_bold) -> str:
    """«서울 11/26 (평년보다 6일 늦음)» 또는 «서울 아직 (평년 11/20, 지난겨울 12/4)»."""
    # 조사를 붙이지 않음 — 닫는 별표 바로 뒤에 글자가 붙으면 슬랙이 굵게로 읽지 않음
    if day := status.first.get(station.name):
        gap = gap_text(station, day)
        return f"{bold(station.name)} {short_date(day)}" + (f" ({gap})" if gap else "")
    wait = waiting_text(station, status)
    return f"{bold(station.name)} 아직" + (f" ({wait})" if wait else "")


def season_text(status: Status) -> str:
    return f"{status.year}~{(status.year + 1) % 100:02d}년 겨울"


def observed_line(status: Status, bold: Style = html_bold) -> str:
    """관측 한 줄 — 관측된 곳이 적으면 이름·날짜, 많으면 개수·최근. 서울이 아직이면 그 평년을 덧붙임."""
    seen = [st for st in STATIONS if st.name in status.first]
    waiting = "" if HEADLINE in status.first else station_text(BY_NAME[HEADLINE], status, bold)
    if not seen:
        return f"아직 첫눈이 관측된 곳이 없습니다 — {waiting}"
    rest = len(STATIONS) - len(seen)
    text = observed_summary([(status.first[st.name], station_text(st, status, bold)) for st in seen],
                            f"나머지 {rest}곳은 아직" if rest else "", f"{len(seen)}곳 관측 · {rest}곳 아직")
    return f"{text} / {waiting}" if waiting else text


def is_snowy(sky: str | None) -> bool:
    """«비/눈» 도 셈 — 진눈깨비도 첫눈으로 관측함."""
    return "눈" in (sky or "")


def snow_days(days: Sequence) -> list[dt.date]:
    return [d.date for d in days if is_snowy(d.sky)]


def snow_forecast(dates: list[dt.date]) -> str:
    return " · ".join(short_day_label(d) for d in dates) + " 눈 예보"


def week_line(status: Status, days: Sequence | None, stations: tuple[Station, ...] = STATIONS,
              muted: Style = html_muted) -> str:
    """days 는 보일 날만(None 이면 예보를 못 받음). 예보 구역 전체의 눈이라 어느 지점일지는 말하지 않고,
    아직인 곳이 남았을 때만 덧붙임."""
    if days is None:
        return "예보를 받지 못했습니다"
    snowy = snow_days(days)
    if not snowy:
        return "예보에 눈 소식이 없습니다"
    waiting = any(st.name not in status.first for st in stations)
    return f"{snow_forecast(snowy)} {muted('(첫눈이 될 수 있음)')}" if waiting else snow_forecast(snowy)
