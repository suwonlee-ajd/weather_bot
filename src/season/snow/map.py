"""첫눈 지도 — 계절관측 24곳의 올해 첫눈과 평년·지난겨울을 한 장에 그림."""
from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence

from src.common.browser import capture
from src.common.text import day_label, short_date
from src.season.basemap import BASE_CSS, INSET_LON, MapInfo, frame, label, place
from src.season.snow.data import Status, gap_days, normal_of
from src.season.snow.stations import STATIONS, Station
from src.season.snow.text import SOURCES, observed_line, season_text, week_line

INFO = MapInfo("첫눈", "snow", "계절관측 24곳의 올해 첫눈과 평년·지난겨울 지도(기상청)")

# 관측은 파란 육각 눈 결정, 아직은 회색 빈 원 — 모양으로도 가름(대비·색각 검증 통과, 회색은 «없음» 의 중립)
BLUE, GRAY = "#2a78d6", "#898781"


def _flake(x: float, y: float, r: float) -> str:
    """육각 눈 결정 — 가지 여섯에 끝 가까이 V 잔가지. 흰 테두리를 먼저 그려 바탕 지도·이름 위에서도 또렷하게."""
    parts = []
    for k in range(6):
        a = math.radians(60 * k - 90)
        parts.append(f"M{x:.1f},{y:.1f}L{x + r * math.cos(a):.1f},{y + r * math.sin(a):.1f}")
        bx, by = x + 0.55 * r * math.cos(a), y + 0.55 * r * math.sin(a)
        for side in (-1, 1):
            b = a + side * math.radians(42)
            parts.append(f"M{bx:.1f},{by:.1f}L{bx + 0.4 * r * math.cos(b):.1f},{by + 0.4 * r * math.sin(b):.1f}")
    d, w = "".join(parts), max(1.2, r / 5)
    return (f'<path d="{d}" fill="none" stroke="#fcfcfb" stroke-width="{w + 2.2:.1f}" stroke-linecap="round"/>'
            f'<path d="{d}" fill="none" stroke="{BLUE}" stroke-width="{w:.1f}" stroke-linecap="round"/>')


def _marker(x: float, y: float, seen: bool, r: float = 6.5) -> str:
    if seen:
        return _flake(x, y, r + 2.5)     # 가지만 있어 같은 반지름이면 빈 원보다 작아 보임
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fcfcfb" stroke="{GRAY}" stroke-width="2"/>'


def _icon(seen: bool) -> str:
    return f'<svg width="16" height="16" viewBox="-8 -8 16 16">{_marker(0, 0, seen, r=4.6)}</svg>'


def _this_year(status: Status, st: Station) -> str:
    day = status.first.get(st.name)
    if day is None:
        return '<span class="none">–</span>'
    gap = gap_days(st, day)
    tail = f' <span class="gap">{gap:+d}일</span>' if gap else ""
    return f'<span class="obs">{short_date(day)}</span>{tail}'


def build_html(status: Status, week_start: dt.date, days: Sequence | None, span_label: str = "이번 주") -> str:
    """days 는 lead 의 «이번 주»(또는 span_label) 줄에 쓸 예보 — 머리의 기간 밖 날은 뺌. None 이면 못 받음."""
    week_end = week_start + dt.timedelta(days=6)
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
        return short_date(day) if day else '<span class="none">–</span>'

    rows = "".join(
        f'<tr><th scope="row">{st.name}</th><td>{_this_year(status, st)}</td>'
        f'<td>{cell(normal_of(st, status.year))}</td><td>{cell(status.last.get(st.name))}</td></tr>'
        for st in sorted(STATIONS, key=order)
    )

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div id="card">
  <div class="head"><h1>첫눈 지도</h1><span class="period">{day_label(week_start)} ~ {day_label(week_end)}</span></div>
  <div class="lead">
    <div><span class="k">관측</span><span>{observed_line(status)}</span></div>
    <div><span class="k">{span_label}</span><span>{week_line(status, days)}</span></div>
  </div>
  <div class="body">
    <div class="map">{svg}
      <div class="legend"><span>{_icon(True)}첫눈 관측</span><span>{_icon(False)}아직</span></div>
    </div>
    <table>
      <caption>올해 옆 숫자는 평년과의 차이(+ 늦음)</caption>
      <thead><tr><th>지점</th><th>올해</th><th>평년</th><th>지난겨울</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div class="foot">{SOURCES} ({season_text(status)})<br>첫눈은 관측자가 눈으로 보고 정하며, 진눈깨비도 첫눈으로 칩니다.</div>
</div></body></html>"""


def render_png(status: Status, week_start: dt.date, days: Sequence | None, *, span_label: str = "이번 주",
               scale: int = 2) -> bytes:
    return capture(build_html(status, week_start, days, span_label), scale=scale)


CSS = BASE_CSS + """
.lead { background: #eef4fb; }
.gap { color: var(--ink2); font-size: 11.5px; }
"""
