"""첫눈 지도 — 계절관측 24곳의 올해 첫눈과 평년·지난겨울을 한 장에 그림."""
from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from src.common.browser import capture
from src.common.text import short_date
from src.season.basemap import BASE_CSS, INSET_LON, MapInfo, frame, label, place
from src.season.mapcard import NONE, Card, body, glyph, hollow, icon, legend
from src.season.snow.data import Status, gap_days, normal_of
from src.season.snow.stations import STATIONS, Station
from src.season.snow.text import SOURCES, observed_line, season_text, week_line
from src.season.weeks import week_end_of

INFO = MapInfo("첫눈", "snow", "계절관측 24곳의 올해 첫눈과 평년·지난겨울 지도(기상청)")


def _marker(x: float, y: float, seen: bool, r: float = 6.5) -> str:
    """관측은 ❄️, 아직은 회색 빈 원."""
    return glyph("snow", x, y, r) if seen else hollow(x, y, r)


def _icon(seen: bool) -> str:
    return icon(_marker(0, 0, seen, r=4.6), 16)


def _this_year(status: Status, st: Station) -> str:
    day = status.first.get(st.name)
    if day is None:
        return NONE
    gap = gap_days(st, day)
    tail = f' <span class="gap">{gap:+d}일</span>' if gap else ""
    return f'<span class="obs">{short_date(day)}</span>{tail}'


def build_html(status: Status, week_start: dt.date, days: Sequence | None, span_label: str = "이번 주") -> str:
    """days 는 lead 의 «이번 주»(또는 span_label) 줄에 쓸 예보 — 머리의 기간 밖 날은 뺌. None 이면 못 받음."""
    week_end = week_end_of(week_start)
    if days is not None:
        days = [d for d in days if week_start <= d.date <= week_end]
    marks, labels = [], []
    for st in STATIONS:
        x, y = place(st.lon, st.lat)
        seen = st.name in status.first
        marks.append(_marker(x, y, seen))
        if st.lon <= INSET_LON:      # 울릉도는 상자 이름(울릉도·독도)이 라벨을 대신함
            labels.append(label(x, y, st.name, st.label, strong=seen))
    svg = frame("".join(marks) + "".join(labels), f"전국 {len(STATIONS)}개 관측 지점 첫눈 현황 지도")

    def order(st: Station):
        # 올해 관측일 순, 아직인 곳은 평년 순, 평년도 없는 곳은 맨 뒤
        day = status.first.get(st.name)
        normal = normal_of(st, status.year)
        return (day is None, day or normal or dt.date.max)

    def cell(day: dt.date | None) -> str:
        return short_date(day) if day else NONE

    rows = "".join(
        f'<tr><th scope="row">{st.name}</th><td>{_this_year(status, st)}</td>'
        f'<td>{cell(normal_of(st, status.year))}</td><td>{cell(status.last.get(st.name))}</td></tr>'
        for st in sorted(STATIONS, key=order)
    )

    table = ("<table><caption>올해 옆 숫자는 평년과의 차이(+ 늦음)</caption>"
             "<thead><tr><th>지점</th><th>올해</th><th>평년</th><th>지난겨울</th></tr></thead>"
             f"<tbody>{rows}</tbody></table>")
    lead = (("관측", observed_line(status)), (span_label, week_line(status, days)))
    foot = f"{SOURCES} ({season_text(status)})<br>첫눈은 관측자가 눈으로 보고 정하며, 진눈깨비도 첫눈으로 칩니다."
    key = legend(((_icon(True), "첫눈 관측"), (_icon(False), "아직")))
    return Card("첫눈 지도", week_start, lead, body(svg + key, table), foot).html(CSS)


def render_png(status: Status, week_start: dt.date, days: Sequence | None, *, span_label: str = "이번 주",
               scale: int = 2) -> bytes:
    return capture(build_html(status, week_start, days, span_label), scale=scale)


CSS = BASE_CSS + """
.lead { background: #eef4fb; }
.gap { color: var(--ink2); font-size: 11.5px; }
"""
