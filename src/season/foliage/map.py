"""단풍 지도 — 기상청 현황과 웨더아이 예상을 한 장에 그림.

날씨누리 지도는 320×418 GIF 라 슬랙에서 흐리고 예상일이 없음. 바탕 지도는 season/basemap.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from src.common.browser import capture
from src.common.text import day_label, short_date
from src.season.basemap import BASE_CSS, MapInfo, emoji, frame, label, place
from src.season.foliage.data import CRITERIA_TEXT, KINDS, STAGES, Snapshot
from src.season.foliage.mountains import MOUNTAINS, Mountain
from src.season.foliage.text import (
    FRESH_PEAK_DAYS,
    observed_line,
    peak_age,
    sources,
    week_changes,
    week_line,
)

INFO = MapInfo("단풍", "foliage", "전국 21개 명산의 단풍 현황(기상청)과 예상 시기(웨더아이) 지도")

# 단풍전은 회색 빈 원, 물든 산은 🍁, 절정 2주 넘은 산은 🍂 — 모양으로 가르고 첫단풍은 🍁 을 옅게(밝기로 가름)
GRAY = "#898781"
FIRST_OPACITY = 0.45


@dataclass(frozen=True)
class Mark:
    """산 표지 — 단계, 이번 주 예상(점선 고리), 절정 2주 넘음(옅게)."""
    stage: int
    ring: bool = False
    faded: bool = False


def _marker(x: float, y: float, mark: Mark, r: float = 6.5) -> str:
    stage, out, size = mark.stage, [], 2 * r + 7     # 그림은 여백이 있어 같은 크기면 빈 원보다 작아 보임
    if mark.ring:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size / 2 + 3}" fill="none" '
                   f'stroke="#0b0b0b" stroke-width="1.4" stroke-dasharray="2.6 2.2"/>')
    if stage == 0:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fcfcfb" stroke="{GRAY}" stroke-width="2"/>')
    elif mark.faded:
        out.append(emoji("fallen", x, y, size))
    else:
        out.append(emoji("maple", x, y, size, opacity=FIRST_OPACITY if stage == 1 else 1.0))
    return "".join(out)


def _icon(stage: int, faded: bool = False) -> str:
    return f'<svg width="17" height="17" viewBox="-9.5 -9.5 19 19">{_marker(0, 0, Mark(stage, faded=faded), r=5)}</svg>'


def _svg(snap: Snapshot, flagged: set[str], faded: set[str]) -> str:
    marks, labels = [], []
    for m in MOUNTAINS:
        x, y = place(m.lon, m.lat)
        stage = snap.stage(m.name)
        marks.append(_marker(x, y, Mark(stage, ring=m.name in flagged, faded=m.name in faded)))
        strong = m.name in flagged or (stage > 0 and m.name not in faded)
        labels.append(label(x, y, m.name, m.label, strong=strong))
    return frame("".join(marks) + "".join(labels), f"전국 {len(MOUNTAINS)}개 명산 단풍 현황 지도")


def _rows(snap: Snapshot, week_start: dt.date, week_end: dt.date, faded: set[str]) -> str:
    def cell(kind: str, name: str) -> str:
        day, observed = snap.when(kind, name)
        if observed:
            return f'<span class="obs">{short_date(day) if day else "관측"}</span>'
        if day is None:
            return '<span class="none">–</span>'
        this_week = " wk" if week_start <= day <= week_end else ""
        return f'<span class="prd{this_week}">{short_date(day)}</span>'

    def order(m: Mountain):
        # 첫단풍 날짜순 — 물들었는데 날짜 없는 산은 맨 앞, 예상도 없는 산은 맨 뒤
        day, observed = snap.when("first", m.name)
        return (day is None and not observed, day or dt.date.min, -m.lat)

    return "".join(
        f'<tr><th scope="row">{m.name}</th>'
        f'<td class="st">{_icon(snap.stage(m.name), m.name in faded)}<span>{STAGES[snap.stage(m.name)]}</span></td>'
        + "".join(f"<td>{cell(kind, m.name)}</td>" for kind in KINDS) + "</tr>"
        for m in sorted(MOUNTAINS, key=order)
    )


def build_html(snap: Snapshot, week_start: dt.date, span_label: str = "이번 주") -> str:
    week_end = week_start + dt.timedelta(days=6)
    flagged = {n for changes in week_changes(snap, week_start, week_end).values() for n, _ in changes}
    faded = {m.name for m in MOUNTAINS
             if (age := peak_age(snap, m.name, week_start)) is not None and age > FRESH_PEAK_DAYS}
    svg = _svg(snap, flagged, faded)
    rows = _rows(snap, week_start, week_end, faded)
    faded_legend = f"<span>{_icon(2, faded=True)}절정 2주 넘음</span>" if faded else ""
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div id="card">
  <div class="head"><h1>단풍 지도</h1><span class="period">{day_label(week_start)} ~ {day_label(week_end)}</span></div>
  <div class="lead">
    <div><span class="k">관측</span><span>{observed_line(snap, day=week_start)}</span></div>
    <div><span class="k">{span_label}</span><span>{week_line(snap, week_start, week_end)}</span></div>
  </div>
  <div class="body">
    <div class="map">{svg}
      <div class="legend">
        <span>{_icon(0)}단풍전</span><span>{_icon(1)}첫단풍</span><span>{_icon(2)}절정</span>{faded_legend}
        <span><svg width="18" height="18" viewBox="-9 -9 18 18"><circle r="7" fill="none" stroke="#0b0b0b"
          stroke-width="1.4" stroke-dasharray="2.6 2.2"/></svg>이번 주 예상</span>
      </div>
    </div>
    <table>
      <caption><b>굵게</b> 관측 · <span class="muted">흐리게</span> 예상</caption>
      <thead><tr><th>산</th><th>현황</th><th>첫단풍</th><th>절정</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div class="foot">{sources(snap, detail=True)}<br>{CRITERIA_TEXT}입니다.</div>
</div></body></html>"""


def render_png(snap: Snapshot, week_start: dt.date, *, span_label: str = "이번 주", scale: int = 2) -> bytes:
    return capture(build_html(snap, week_start, span_label), scale=scale)


CSS = BASE_CSS + """
.lead { background: #fbf3ee; }
td.st { color: var(--ink2); }
td.st svg { vertical-align: -2px; margin-right: 4px; }
.prd { color: var(--muted); }
.prd.wk { color: var(--ink); font-weight: 600; background: #fbe3d6; border-radius: 4px; padding: 0 4px; margin: 0 -4px; }
"""
