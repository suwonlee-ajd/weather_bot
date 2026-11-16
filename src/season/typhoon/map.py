"""태풍 예상 경로 지도 — 기상청 태풍정보의 지난 경로·현재 위치·예상 위치와 시각·중심기압, 반경을 한 장에 그림.

날씨누리 태풍 지도는 브라우저에서 그리는 화면이라 내려받을 그림이 없음 — 받은 경로표로 직접 그림. 바탕은 pacific.
기압선은 경로표에 없어 그리지 않음 — 함께 올리는 지상일기도에 있음.
"""
from __future__ import annotations

import datetime as dt
import html
from collections.abc import Sequence
from typing import Protocol

from src.common.browser import CARD_WIDTH, capture
from src.common.text import day_label, short_date
from src.season.basemap import BASE_CSS, MapInfo
from src.season.typhoon import pacific

INFO = MapInfo("태풍", "typhoon", "기상청 태풍정보의 현재 위치와 예상 경로 지도", heading="태풍 예상 경로 지도")
MAP_W = CARD_WIDTH - 48                     # 카드 좌우 여백(24px)을 뺀 폭
MAX_H, MIN_H = 560, 380
NAME_ROOM = 2.8                             # 현재 위치 아래 두 줄(이름·시각)이 지도 끝에 닿지 않게 남길 위도
NOW = "#d6372b"
# 반경은 경로표에 값이 있을 때만 그리고 범례에도 그때만 적음. 색은 날씨누리 지도의 결(확률 파랑·강풍 노랑·폭풍 빨강)
EXTENTS = (("radius", "#1f87fd", "70% 확률반경 — 태풍 중심이 들어올 확률이 70%인 범위"),
           ("gale", "#f0a020", "강풍반경 — 초속 15m 이상 바람이 부는 범위"),
           ("storm", "#e0483e", "폭풍반경 — 초속 25m 이상 바람이 부는 범위"))


class Reach(Protocol):
    km: int
    text: str


class Spot(Protocol):
    """kma.typhoon.Point 의 모양 — season 은 kma 를 가져다 쓰지 않음."""
    at: dt.datetime
    lat: float
    lon: float
    pressure: int | None
    radius: int | None
    gale: Reach | None
    storm: Reach | None
    summary: str
    when: str


class Storm(Protocol):
    """kma.typhoon.Typhoon 의 모양."""
    no: int
    name: str
    title: str
    issued: dt.datetime | None
    now: Spot
    forecast: Sequence[Spot]
    past: Sequence[Spot]


def _km(p: Spot, kind: str) -> int:
    value = getattr(p, kind)
    return (value if kind == "radius" else value.km) if value else 0


def _spots(storms: Sequence[Storm]) -> list[tuple[float, float]]:
    """범위에 넣을 점 — 반경 끝까지, 현재 위치 아래 글자 자리까지."""
    out = []
    for s in storms:
        out.append((s.now.lon, s.now.lat - NAME_ROOM))
        reach = [(p, 0) for p in s.past] + [(s.now, max(_km(s.now, "gale"), _km(s.now, "storm")))]
        reach += [(p, _km(p, "radius")) for p in s.forecast]
        for p, km in reach:
            deg = km / pacific.KM_PER_DEG
            out += [(p.lon - deg, p.lat - deg), (p.lon + deg, p.lat + deg)]
    return out


def _stamp(p: Spot) -> str:
    """«20일 15시 990hPa» — 중심기압이 없으면 시각만."""
    return f"{p.at.day}일 {p.at.hour}시" + (f" {p.pressure}hPa" if p.pressure else "")


def _line(view: pacific.View, spots: Sequence[Spot], cls: str) -> str:
    if len(spots) < 2:
        return ""
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (view.xy(p.lon, p.lat) for p in spots))
    return f'<polyline class="{cls}" points="{pts}"/>'


def _extent(view: pacific.View, p: Spot, kind: str) -> str:
    if not (km := _km(p, kind)):
        return ""
    x, y = view.xy(p.lon, p.lat)
    rx, ry = view.radii(p.lat, km)
    return f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{rx:.1f}" ry="{ry:.1f}"/>'


class _Labels:
    """예상 위치 글자 — 붙은 점(느린 태풍)끼리 겹치면 뒤의 것을 뺌."""
    def __init__(self) -> None:
        self.placed: list[tuple[float, float]] = []
        self.parts: list[str] = []

    def add(self, x: float, y: float, text: str, cls: str) -> None:
        if any(abs(x - px) < 100 and abs(y - py) < 14 for px, py in self.placed):
            return
        self.placed.append((x, y))
        self.parts.append(f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}">{html.escape(text)}</text>')


def _track(view: pacific.View, storm: Storm, week_end: dt.date, labels: _Labels) -> tuple[dict[str, str], str]:
    """(반경 종류별 원, 경로·표지·글자). 바람 반경은 현재 위치에, 확률반경은 예상 위치에. 이번 주 뒤는 옅게."""
    extents = {"radius": "".join(_extent(view, p, "radius") for p in storm.forecast),
               "gale": _extent(view, storm.now, "gale"), "storm": _extent(view, storm.now, "storm")}
    x, y = view.xy(storm.now.lon, storm.now.lat)
    labels.placed += [(x - 50, y + 21), (x - 50, y + 35)]          # 현재 위치 아래 두 줄 자리
    marks = [f'<circle class="pt" cx="{px:.1f}" cy="{py:.1f}" r="2.2"/>'
             for px, py in (view.xy(p.lon, p.lat) for p in storm.past)]
    for p in storm.forecast:
        px, py = view.xy(p.lon, p.lat)
        later = "" if p.at.date() <= week_end else " later"
        marks.append(f'<circle class="fc{later}" cx="{px:.1f}" cy="{py:.1f}" r="3.6"/>')
        labels.add(px + 8, py + 4, _stamp(p), f"when{later}")
    path = (_line(view, [*storm.past, storm.now], "past") + _line(view, [storm.now, *storm.forecast], "ahead")
            + "".join(marks) + _now_mark(x, y)
            + f'<text class="name" x="{x:.1f}" y="{y + 25:.1f}" text-anchor="middle">제{storm.no}호 {storm.name}</text>'
            + f'<text class="when" x="{x:.1f}" y="{y + 39:.1f}" text-anchor="middle">{_stamp(storm.now)}</text>')
    return extents, path


def _now_mark(x: float, y: float, ring: float = 9, dot: float = 5) -> str:
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{ring}" fill="#ffffff" fill-opacity="0.6" stroke="{NOW}" '
            f'stroke-width="2"/><circle cx="{x:.1f}" cy="{y:.1f}" r="{dot}" fill="{NOW}"/>')


def build_svg(storms: Sequence[Storm], week_end: dt.date) -> tuple[str, list[str]]:
    """(지도 SVG, 그린 반경 종류) — 범례는 실제로 그린 반경만 적음."""
    view = pacific.fit(_spots(storms), MAP_W, MAX_H, MIN_H)
    labels = _Labels()
    tracks = [_track(view, s, week_end, labels) for s in storms]
    # 경로 글자(왼쪽 끝 기준, 폭 100px 안팎)와 겹치는 지명은 뺌 — 괌처럼 경로 곁에 있는 곳
    places = "".join(svg for x, y, svg in pacific.places(view)
                     if not any(abs(x - lx - 50) < 75 and abs(y - ly) < 16 for lx, ly in labels.placed))
    drawn = [kind for kind, _, _ in EXTENTS if any(t[kind] for t, _ in tracks)]
    groups = "".join(f'<g class="{kind}">{"".join(t[kind] for t, _ in tracks)}</g>' for kind in drawn)
    svg = (f'<svg width="{view.width:.0f}" height="{view.height:.0f}" viewBox="0 0 {view.width:.0f} '
           f'{view.height:.0f}" role="img" aria-label="태풍 예상 경로 지도">{pacific.background(view)}{groups}{places}'
           f'{"".join(p for _, p in tracks)}{"".join(labels.parts)}</svg>')
    return svg, drawn


def _icon(inner: str) -> str:
    return f'<svg width="22" height="18" viewBox="-11 -9 22 18">{inner}</svg>'


MARKS = "".join(f"<span>{_icon(icon)}{text}</span>" for icon, text in (
    (_now_mark(0, 0, ring=7, dot=4), "현재 위치"),
    ('<line class="past" x1="-9" y1="0" x2="9" y2="0"/><circle class="pt" r="2.2"/>', "지난 경로"),
    ('<line class="ahead" x1="-10" y1="0" x2="10" y2="0"/><circle class="fc" r="3.6"/>', "이번 주 예상"),
    ('<circle class="fc later" r="3.6"/>', "그 뒤 예상"),
))


def _swatch(kind: str) -> str:
    return _icon(f'<g class="{kind}"><ellipse rx="7" ry="7"/></g>')


def _legend(drawn: list[str]) -> str:
    swatches = "".join(f"<span>{_swatch(kind)}{text}</span>" for kind, _, text in EXTENTS if kind in drawn)
    return f'<div class="legend">{MARKS}</div>' + (f'<div class="legend">{swatches}</div>' if swatches else "")


def _lead(storms: Sequence[Storm]) -> str:
    rows = []
    for s in storms:
        reach = "".join(f" · {name} {r.text}" for name, r in (("강풍반경", s.now.gale), ("폭풍반경", s.now.storm)) if r)
        rows.append(f'<div><span class="k">현재</span><span><b>{html.escape(s.title)}</b> · '
                    f'{html.escape(s.now.summary)}{reach} ({s.now.when} 기준)</span></div>')
    return "".join(rows)


def build_html(storms: Sequence[Storm], week_start: dt.date) -> str:
    week_end = week_start + dt.timedelta(days=6)
    issued = max((s.issued for s in storms if s.issued), default=None)
    stamp = f" ({short_date(issued)} {issued.hour}시 발표)" if issued else ""
    svg, drawn = build_svg(storms, week_end)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div id="card">
  <div class="head"><h1>태풍 예상 경로</h1><span class="period">{day_label(week_start)} ~ {day_label(week_end)}</span></div>
  <div class="lead">{_lead(storms)}</div>
  <div class="map">{svg}{_legend(drawn)}</div>
  <div class="foot">기상청 태풍정보{stamp} · 바탕 지도 Natural Earth<br>기압선은 함께 올린 지상일기도에서 볼 수 있습니다.</div>
</div></body></html>"""


def render_png(storms: Sequence[Storm], week_start: dt.date, *, scale: int = 2) -> bytes:
    return capture(build_html(storms, week_start), scale=scale)


# 확률반경은 예상 위치마다 겹쳐 그려 묶음째 옅게 — 겹친 곳이 진해지지 않고 한 덩어리로 보임
CSS = BASE_CSS + pacific.CSS + f"""
g.radius {{ opacity: 0.18; }}
g.radius ellipse {{ fill: {EXTENTS[0][1]}; }}
g.gale ellipse {{ fill: {EXTENTS[1][1]}; fill-opacity: 0.16; stroke: {EXTENTS[1][1]}; stroke-width: 1.4; }}
g.storm ellipse {{ fill: {EXTENTS[2][1]}; fill-opacity: 0.18; stroke: {EXTENTS[2][1]}; stroke-width: 1.4; }}
.legend g.radius {{ opacity: 0.35; }}
.legend + .legend {{ margin-top: 2px; }}
.lead {{ background: #eef4fb; }}
.lead .k {{ width: 40px; }}
.map svg[role=img] {{ display: block; border-radius: 8px; }}
.past {{ fill: none; stroke: #8a8880; stroke-width: 1.8; }}
.ahead {{ fill: none; stroke: var(--ink); stroke-width: 1.8; stroke-dasharray: 5 4; }}
.pt {{ fill: #8a8880; }}
.fc {{ fill: #ffffff; stroke: var(--ink); stroke-width: 1.6; }}
.fc.later {{ stroke: #a3a19a; }}
.when, .name {{ font-size: 11.5px; fill: var(--ink); paint-order: stroke; stroke: #ffffff; stroke-width: 3px;
                stroke-linejoin: round; }}
.when.later {{ fill: var(--muted); }}
.name {{ font-weight: 700; font-size: 12.5px; fill: {NOW}; }}
"""
