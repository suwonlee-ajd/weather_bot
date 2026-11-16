"""단풍 지도 — 기상청 현황과 웨더아이 예상을 한 장에 그림.

날씨누리 지도는 320×418 GIF 라 슬랙에서 흐리고 예상일이 없음. 바탕 지도는 season/basemap.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from src.common.browser import capture
from src.common.text import short_date
from src.season.basemap import BASE_CSS, MapInfo, frame, label, place
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
from src.season.mapcard import (
    NONE,
    Card,
    body,
    glyph,
    glyph_size,
    hollow,
    icon,
    legend,
    ring,
)
from src.season.weeks import week_end_of

INFO = MapInfo("단풍", "foliage", "전국 21개 명산의 단풍 현황(기상청)과 예상 시기(웨더아이) 지도")

# 단풍전은 회색 빈 원, 물든 산은 🍁, 절정 2주 넘은 산은 🍂 — 모양으로 가르고 첫단풍은 🍁 을 옅게(밝기로 가름)
FIRST_OPACITY = 0.45


@dataclass(frozen=True)
class Mark:
    """산 표지 — 단계, 이번 주 예상(점선 고리), 절정 2주 넘음(옅게)."""
    stage: int
    ring: bool = False
    faded: bool = False


def _marker(x: float, y: float, mark: Mark, r: float = 6.5) -> str:
    out = ring(x, y, glyph_size(r) / 2 + 3) if mark.ring else ""
    if mark.stage == 0:
        return out + hollow(x, y, r)
    if mark.faded:
        return out + glyph("fallen", x, y, r)
    return out + glyph("maple", x, y, r, opacity=FIRST_OPACITY if mark.stage == 1 else 1.0)


def _icon(stage: int, faded: bool = False) -> str:
    return icon(_marker(0, 0, Mark(stage, faded=faded), r=5), 17, view=19)


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
            return NONE
        this_week = " week" if week_start <= day <= week_end else ""
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
    week_end = week_end_of(week_start)
    flagged = {n for changes in week_changes(snap, week_start, week_end).values() for n, _ in changes}
    faded = {m.name for m in MOUNTAINS
             if (age := peak_age(snap, m.name, week_start)) is not None and age > FRESH_PEAK_DAYS}
    marks = [(_icon(0), "단풍전"), (_icon(1), "첫단풍"), (_icon(2), "절정")]
    marks += [(_icon(2, faded=True), "절정 2주 넘음")] if faded else []
    marks += [(icon(ring(0, 0, 7), 18), "이번 주 예상")]
    table = ('<table><caption><b>굵게</b> 관측 · <span class="muted">흐리게</span> 예상</caption>'
             '<thead><tr><th>산</th><th>현황</th><th>첫단풍</th><th>절정</th></tr></thead>'
             f'<tbody>{_rows(snap, week_start, week_end, faded)}</tbody></table>')
    rows = (("관측", observed_line(snap, day=week_start)), (span_label, week_line(snap, week_start, week_end)))
    foot = f"{sources(snap, detail=True)}<br>{CRITERIA_TEXT}입니다."
    return Card("단풍 지도", week_start, rows, body(_svg(snap, flagged, faded) + legend(marks), table), foot).html(CSS)


def render_png(snap: Snapshot, week_start: dt.date, *, span_label: str = "이번 주", scale: int = 2) -> bytes:
    return capture(build_html(snap, week_start, span_label), scale=scale)


CSS = BASE_CSS + """
#card { --week: #fbe3d6; }
.lead { background: #fbf3ee; }
td.st { color: var(--ink2); }
td.st svg { vertical-align: -2px; margin-right: 4px; }
.prd { color: var(--muted); }
"""
