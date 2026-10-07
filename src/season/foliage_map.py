"""단풍 지도 — 기상청 현황과 웨더아이 예상을 한 장에 그림.

날씨누리 지도는 320×418 GIF 라 슬랙에서 흐리고 예상일이 없음. 윤곽은 Natural Earth(퍼블릭 도메인).
"""
from __future__ import annotations

import datetime as dt
import functools
import html
import json
import math
from pathlib import Path

from src.common.browser import CARD_WIDTH, capture
from src.common.text import day_label, short_date
from src.season.foliage import CRITERIA_TEXT, KINDS, STAGES, Snapshot
from src.season.foliage_text import observed_line, sources, week_changes, week_line
from src.season.mountains import MOUNTAINS, Mountain

ASSET = Path(__file__).parent / "assets" / "korea_provinces.json"

# 주황→진홍 순서형이라 색맹 검증 통과. 상태는 모양(빈 원·아래 반원·채운 원)으로도 가름
ORANGE, RED, GRAY = "#eb6834", "#a8321f", "#898781"

# 위도 36° 기준 등장방형 — 남한만 그려 이것으로 충분함
LON0, LON1, LAT0, LAT1 = 124.55, 130.35, 33.05, 38.68
_K = math.cos(math.radians(36))
_S = 74.0
MAP_W = (LON1 - LON0) * _K * _S
MAP_H = (LAT1 - LAT0) * _S
INSET = {"x": MAP_W - 60, "y": 70.0, "w": 56.0, "h": 46.0}


def _proj(lon: float, lat: float) -> tuple[float, float]:
    return (lon - LON0) * _K * _S, (LAT1 - lat) * _S


def _proj_inset(lon: float, lat: float) -> tuple[float, float]:
    # 울릉도는 실제 축척 그대로 상자 왼쪽에 둠
    return INSET["x"] + 10 + (lon - 130.80) * _K * _S, INSET["y"] + 12 + (37.56 - lat) * _S


def _path(ring: list[list[float]], inset: bool = False) -> str:
    f = _proj_inset if inset else _proj
    pts = [f(lon, lat) for lon, lat in ring]
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"


@functools.cache
def _basemap() -> str:
    doc = json.loads(ASSET.read_text(encoding="utf-8"))
    main, islands = [], []
    for prov in doc["provinces"]:
        d_main = "".join(_path(r) for r in prov["rings"] if r[0][0] <= 130.5)
        d_isl = "".join(_path(r, inset=True) for r in prov["rings"] if r[0][0] > 130.5)
        if d_main:
            main.append(f'<path d="{d_main}"/>')
        if d_isl:
            islands.append(f'<path d="{d_isl}"/>')
    x, y, w, h = INSET["x"], INSET["y"], INSET["w"], INSET["h"]
    dokdo_x, dokdo_y = x + w - 12, y + 22   # 원자료에 없어 점만 — 실제 거리로는 상자 밖
    return (
        f'<g class="land">{"".join(main)}</g>'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="4" fill="none" '
        f'stroke="#c3c2b7" stroke-width="1" stroke-dasharray="3 2"/>'
        f'<g class="land">{"".join(islands)}</g>'
        f'<circle cx="{dokdo_x:.1f}" cy="{dokdo_y:.1f}" r="1.8" fill="#d9d7cf"/>'
        f'<text class="inset" x="{x + w / 2:.1f}" y="{y + h - 5:.1f}" text-anchor="middle">울릉도·독도</text>'
    )


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
        x, y = _proj(m.lon, m.lat)
        stage = snap.stage(m.name)
        marks.append(_marker(x, y, stage, ring=m.name in flagged))
        labels.append(_label(x, y, m, strong=m.name in flagged or stage > 0))
    svg = (f'<svg width="{MAP_W:.0f}" height="{MAP_H:.0f}" viewBox="0 0 {MAP_W:.0f} {MAP_H:.0f}" '
           f'role="img" aria-label="전국 {len(MOUNTAINS)}개 명산 단풍 현황 지도">'
           f'{_basemap()}{"".join(marks)}{"".join(labels)}</svg>')

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


CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #ffffff; }}
#card {{
  --ink: #0b0b0b; --ink2: #52514e; --muted: #898781; --hair: #e1e0d9;
  width: {CARD_WIDTH}px; padding: 22px 24px 18px; background: #ffffff;
  font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', 'Noto Sans CJK KR', 'Malgun Gothic', sans-serif;
  color: var(--ink); line-height: 1.6; font-size: 14px; -webkit-font-smoothing: antialiased;
  word-break: keep-all;   /* 한국어는 낱말 단위로 줄을 바꾼다 ("첫단|풍" 방지) */
}}
.head {{ display: flex; align-items: baseline; gap: 10px; }}
h1 {{ font-size: 19px; font-weight: 700; letter-spacing: -0.2px; }}
.period {{ color: var(--ink2); font-size: 13.5px; }}
.muted {{ color: var(--muted); }}
.lead {{ margin: 8px 0 14px; padding: 9px 12px; background: #fbf3ee; border-radius: 8px; font-size: 13.5px; }}
.lead div {{ display: flex; }}
.lead div + div {{ margin-top: 2px; }}
.lead .k {{ flex: none; width: 56px; color: var(--ink2); font-size: 12.5px; padding-top: 1px; }}
.body {{ display: flex; gap: 18px; align-items: flex-start; }}
.map {{ flex: none; }}
.land path {{ fill: #eeede8; stroke: #ffffff; stroke-width: 1; stroke-linejoin: round; }}
.lbl {{ font-size: 11.5px; fill: var(--ink2); paint-order: stroke; stroke: #ffffff;
        stroke-width: 3px; stroke-linejoin: round; }}
.lbl.strong {{ fill: var(--ink); font-weight: 700; }}
.inset {{ font-size: 9px; fill: var(--muted); }}
.legend {{ display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 6px; font-size: 12px; color: var(--ink2); }}
.legend span {{ display: inline-flex; align-items: center; gap: 4px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12.5px; font-variant-numeric: tabular-nums; }}
caption {{ text-align: left; font-size: 12px; color: var(--ink2); padding-bottom: 6px; }}
caption b {{ color: var(--ink); }}
thead th {{ font-weight: 600; color: var(--ink2); text-align: left; font-size: 12px;
            border-bottom: 1px solid #c3c2b7; padding: 0 4px 4px; }}
tbody tr {{ line-height: 1.4; }}
tbody th {{ text-align: left; font-weight: 600; padding: 1px 4px; white-space: nowrap; }}
tbody td {{ padding: 1px 4px; white-space: nowrap; }}
tbody tr + tr > * {{ border-top: 1px solid #f0efec; }}
td.st {{ color: var(--ink2); }}
td.st svg {{ vertical-align: -2px; margin-right: 4px; }}
.obs {{ font-weight: 700; color: var(--ink); }}
.prd {{ color: var(--muted); }}
.prd.wk {{ color: var(--ink); font-weight: 600; background: #fbe3d6; border-radius: 4px; padding: 0 4px; margin: 0 -4px; }}
.none {{ color: #c3c2b7; }}
.foot {{ margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--hair);
         font-size: 11.5px; color: var(--muted); line-height: 1.55; }}
"""
