"""단풍 지도 — 기상청 현황과 웨더아이 예상을 한 장에.

주간 게시물에 카드·일기도와 함께 붙는 세 번째 이미지로, 자료만 받아 직접 그림.
기상청 날씨누리의 지도는 320×418 GIF 라 슬랙에서 흐리고 예상일이 없음.

    [제목 · 게시 주]
    [관측 한 줄 / 이번 주 예상 한 줄]
    [지도 (21곳, 상태별 표식)] [표 (산 · 현황 · 첫단풍 · 절정)]
    [출처]

표기 원칙
  - 상태는 색과 모양을 함께 씀: 빈 원 단풍전 / 아래 반원 첫단풍 / 채운 원 절정.
    주황→진홍은 한 계열 순서형 색이라 색맹 검증(dataviz 검증기, ordinal)을 통과함.
  - 관측 날짜는 굵게, 예상 날짜는 흐리게. 둘을 섞어 읽지 않게 함.
  - 게시 주에 예상된 변화가 있는 산은 점선 고리와 표 강조로 짚음.

지도 윤곽은 src/season/assets/korea_provinces.json (Natural Earth, 퍼블릭 도메인).
울릉도·독도는 오른쪽 상자로 옮겨 그림. 독도는 좌표로 점만 찍음(원자료에 없음).
"""
from __future__ import annotations

import datetime as dt
import functools
import html
import json
import math
from pathlib import Path

from src.season.foliage import CRITERIA_TEXT, KINDS, NOT_STARTED_TEXT, OUTLOOK_SOURCE, STAGES, Snapshot
from src.weekly.forecast import day_label, short_date
from src.season.mountains import MOUNTAINS, Mountain
from src.weekly.card import CARD_WIDTH, capture

ASSET = Path(__file__).parent / "assets" / "korea_provinces.json"

ORANGE, RED, GRAY = "#eb6834", "#a8321f", "#898781"

# 투영 — 위도 36° 기준 등장방형. 한반도 남쪽만 쓰므로 이것으로 충분함
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
    """지도 윤곽 SVG. 프로세스마다 한 번만 만듦 — 자산도 투영도 바뀌지 않음."""
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
    dokdo_x, dokdo_y = x + w - 12, y + 22   # 위치만 표시 — 실제 거리로는 상자에 안 들어감
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
        # 반지름을 키워 빈 원·반원과 같은 크기로 보이게 함 — 흰 테두리가 안쪽을 먹음
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


def gap_text(predicted: dt.date | None, observed: dt.date, *, show_date: bool = False) -> str:
    """관측이 예상과 얼마나 어긋났는지. 같거나 예상이 없으면 빈 문자열."""
    if not predicted or predicted == observed:
        return ""
    gap = (predicted - observed).days
    shown = f"({short_date(predicted)})" if show_date else ""
    return f"예상{shown}보다 {abs(gap)}일 {'빠름' if gap > 0 else '늦음'}"


def sources(snap: Snapshot, *, detail: bool = False) -> str:
    """출처 한 줄. detail 이면 지도 꼬리말처럼 관측 시점과 예상 곳 수까지."""
    status = "현황 기상청 날씨누리" + (" 유명산 단풍현황" if detail else "")
    if detail and snap.status.updated:
        status += f" ({short_date(snap.status.updated)} 관측까지)"
    o = snap.outlook
    if o is None:
        return f"{status} · 예상 없음" if detail else status
    bits = [f"{short_date(o.published)} 발표"] if o.published else []
    if detail:
        bits.append(f"{len(o.first)}곳")
    return f"{status} · 예상 {OUTLOOK_SOURCE}" + (f"({', '.join(bits)})" if bits else "")


def week_changes(snap: Snapshot, start: dt.date, end: dt.date) -> dict[str, list[tuple[str, dt.date]]]:
    """그 주에 예상된 변화 {'first': [(산, 날짜)], 'peak': [...]}. 이미 지난 단계는 뺌."""
    out: dict[str, list[tuple[str, dt.date]]] = {}
    for stage, kind in enumerate(KINDS, start=1):
        out[kind] = sorted(
            ((m.name, d) for m in MOUNTAINS
             if snap.stage(m.name) < stage and (d := snap.predicted(kind, m.name)) and start <= d <= end),
            key=lambda x: x[1],
        )
    return out


def _html_bold(text: str) -> str:
    return f"<b>{text}</b>"


def observed_line(snap: Snapshot, bold=_html_bold) -> str:
    """관측 한 줄. 물든 곳이 적으면 이름과 날짜를, 많아지면 개수와 최근 변화를 씀.

    지도(HTML)와 멘션 답(슬랙)이 같은 문장을 씀. 굵게 쓰는 방법만 bold 로 갈아 끼움.
    """
    s = snap.status
    if not s.in_service:
        return NOT_STARTED_TEXT
    counts = [sum(1 for m in MOUNTAINS if s.stage(m.name) == k) for k in (2, 1, 0)]
    if not counts[0] and not counts[1]:
        return f"아직 물든 곳이 없습니다 — {len(MOUNTAINS)}곳 모두 단풍 전"

    # 물든 산마다 지금 단계 하나. 촬영일이 아직 안 올라온 산도 빠뜨리지 않음.
    events = []   # (날짜 또는 None, 산, 단계)
    for m in MOUNTAINS:
        if stage := s.stage(m.name):
            events.append((getattr(s, KINDS[stage - 1]).get(m.name), m.name, stage))

    def event_text(e) -> str:
        day, name, stage = e
        text = f"{bold(name)} {STAGES[stage]}"
        if day is None:
            return text
        gap = gap_text(snap.predicted(KINDS[stage - 1], name), day)
        return f"{text} {short_date(day)}" + (f" ({gap})" if gap else "")

    def latest(e):
        return e[0] or dt.date.min       # 날짜 없는 산은 '최근' 에서 뒤로

    if len(events) <= 2:
        head = " · ".join(event_text(e) for e in sorted(events, key=latest))
        return f"{head}, 나머지 {counts[2]}곳은 단풍 전" if counts[2] else head
    tally = " · ".join(f"{STAGES[k]} {n}곳" for k, n in zip((2, 1, 0), counts) if n)
    return f"{tally} — 최근 " + " · ".join(event_text(e) for e in sorted(events, key=latest, reverse=True)[:2])


def week_line(snap: Snapshot, start: dt.date, end: dt.date, bold=_html_bold,
              muted=lambda s: f'<span class="muted">{s}</span>') -> str:
    """그 주에 예상된 변화 한 줄."""
    if snap.outlook is None:
        return (f"{OUTLOOK_SOURCE} 예상을 읽지 못해 현황만 표시합니다" if snap.outlook_error
                else "올해 예상이 아직 나오지 않았습니다")
    bits = [f"{STAGES[stage]} " + " · ".join(f"{bold(n)} {short_date(d)}" for n, d in changes)
            for stage, changes in enumerate(week_changes(snap, start, end).values(), start=1) if changes]
    return (" / ".join(bits) + " " + muted("(예상)")) if bits else "예상된 변화가 없습니다"


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
        # 첫단풍 날짜순. 물들었는데 날짜가 아직 없는 산은 맨 앞, 예상도 없는 산은 맨 뒤.
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
