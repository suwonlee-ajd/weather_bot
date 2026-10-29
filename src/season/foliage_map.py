"""단풍 지도 — 기상청 현황과 웨더아이 예상을 한 장에 그림.

날씨누리 지도는 320×418 GIF 라 슬랙에서 흐리고 예상일이 없음. 윤곽은 Natural Earth(퍼블릭 도메인).
"""
from __future__ import annotations

import datetime as dt
import html

from src.common.browser import capture
from src.common.text import day_label, short_date
from src.season.basemap import BASE_CSS, MAP_H, MAP_W, basemap, proj
from src.season.foliage import CRITERIA_TEXT, KINDS, STAGES, Snapshot
from src.season.foliage_text import observed_line, sources, week_changes, week_line
from src.season.mountains import MOUNTAINS, Mountain

# 주황→진홍 순서형이라 색맹 검증 통과. 상태는 모양(빈 원·아래 반원·채운 원)으로도 가름
ORANGE, RED, GRAY = "#eb6834", "#a8321f", "#898781"


def _marker(x: float, y: float, stage: int, ring: bool = False, r: float = 6.5) -> str:
    out = []
    if ring:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 4.5}" fill="none" '
                   f'stroke="#0b0b0b" stroke-width="1.4" stroke-dasharray="2.6 2.2"/>')
    if stage == 0:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fcfcfb" stroke="{GRAY}" stroke-width="2"/>')
    elif stage == 1:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fcfcfb" stroke="{ORANGE}" stroke-width="2"/>')
        out.append(f'<path d="M{x - r:.1f},{y:.1f} A{r},{r} 0 0 0 {x + r:.1f},{y:.1f} Z" fill="{ORANGE}"/>')
    else:
        # 흰 테두리가 안쪽을 먹어 +1 해야 빈 원과 같은 크기로 보임
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 1}" fill="{RED}" stroke="#fcfcfb" stroke-width="1.5"/>')
    return "".join(out)


def _icon(stage: int) -> str:
    return f'<svg width="14" height="14" viewBox="-7 -7 14 14">{_marker(0, 0, stage, r=5)}</svg>'


def _label(x: float, y: float, m: Mountain, strong: bool) -> str:
    dx, dy, anchor = {"r": (11, 4, "start"), "l": (-11, 4, "end"),
                      "t": (0, -11, "middle"), "b": (0, 19, "middle")}[m.label]
    cls = "lbl strong" if strong else "lbl"
    return (f'<text class="{cls}" x="{x + dx:.1f}" y="{y + dy:.1f}" text-anchor="{anchor}">'
            f'{html.escape(m.name)}</text>')


def build_html(snap: Snapshot, week_start: dt.date, span_label: str = "이번 주") -> str:
    week_end = week_start + dt.timedelta(days=6)
    flagged = {n for changes in week_changes(snap, week_start, week_end).values() for n, _ in changes}

    marks, labels = [], []
    for m in MOUNTAINS:
        x, y = proj(m.lon, m.lat)
        stage = snap.stage(m.name)
        marks.append(_marker(x, y, stage, ring=m.name in flagged))
        labels.append(_label(x, y, m, strong=m.name in flagged or stage > 0))
    svg = (f'<svg width="{MAP_W:.0f}" height="{MAP_H:.0f}" viewBox="0 0 {MAP_W:.0f} {MAP_H:.0f}" '
           f'role="img" aria-label="전국 {len(MOUNTAINS)}개 명산 단풍 현황 지도">'
           f'{basemap()}{"".join(marks)}{"".join(labels)}</svg>')

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

    rows = "".join(
        f'<tr><th scope="row">{m.name}</th>'
        f'<td class="st">{_icon(snap.stage(m.name))}<span>{STAGES[snap.stage(m.name)]}</span></td>'
        + "".join(f"<td>{cell(kind, m.name)}</td>" for kind in KINDS) + "</tr>"
        for m in sorted(MOUNTAINS, key=order)
    )

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div id="card">
  <div class="head"><h1>단풍 지도</h1><span class="period">{day_label(week_start)} ~ {day_label(week_end)}</span></div>
  <div class="lead">
    <div><span class="k">관측</span><span>{observed_line(snap)}</span></div>
    <div><span class="k">{span_label}</span><span>{week_line(snap, week_start, week_end)}</span></div>
  </div>
  <div class="body">
    <div class="map">{svg}
      <div class="legend">
        <span>{_icon(0)}단풍전</span><span>{_icon(1)}첫단풍</span><span>{_icon(2)}절정</span>
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
.obs { font-weight: 700; color: var(--ink); }
.prd { color: var(--muted); }
.prd.wk { color: var(--ink); font-weight: 600; background: #fbe3d6; border-radius: 4px; padding: 0 4px; margin: 0 -4px; }
.none { color: #c3c2b7; }
"""
