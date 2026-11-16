"""태풍 예상 경로 지도 — 기상청 태풍정보의 지난 경로·현재 위치·예상 위치와 시각·중심기압, 반경을 한 장에 그림.

날씨누리 태풍 지도는 브라우저에서 그리는 화면이라 내려받을 그림이 없음 — 받은 경로표로 직접 그림. 바탕은 pacific.
기압선은 경로표에 없어 그리지 않음 — 함께 올리는 지상일기도에 있음.
"""
from __future__ import annotations

import datetime as dt
import html
from collections.abc import Sequence

from src.common.browser import CARD_WIDTH, capture
from src.common.text import html_bold
from src.season.basemap import BASE_CSS, Box, MapInfo, hits, text_box
from src.season.mapcard import Card, icon, legend
from src.season.typhoon import pacific
from src.season.typhoon.data import Point, Reach, Typhoon
from src.season.typhoon.text import issued_text, now_line
from src.season.weeks import week_end_of

INFO = MapInfo("태풍", "typhoon", "기상청 태풍정보의 현재 위치와 예상 경로 지도", heading="태풍 예상 경로 지도")
MAP_W = CARD_WIDTH - 48                     # 카드 좌우 여백(24px)을 뺀 폭
MAX_H, MIN_H = 560, 380
NAME_ROOM = 2.8                             # 현재 위치 아래 두 줄(이름·시각)이 지도 끝에 닿지 않게 남길 위도
NOW = "#d6372b"
WHEN_PX, NAME_PX = 11.5, 12.5               # CSS 의 .when · .name 글자 크기
# 반경은 경로표에 값이 있을 때만 그리고 범례에도 그때만 적음. 색은 날씨누리 지도의 결(확률 파랑·강풍 노랑·폭풍 빨강)
RADIUS_COLOR, GALE_COLOR, STORM_COLOR = "#1f87fd", "#f0a020", "#e0483e"
EXTENTS = (("radius", "70% 확률반경 — 태풍 중심이 들어올 확률이 70%인 범위"),
           ("gale", "강풍반경 — 초속 15m 이상 바람이 부는 범위"),
           ("storm", "폭풍반경 — 초속 25m 이상 바람이 부는 범위"))


def _km(reach: Reach | None) -> int:
    return reach.km if reach else 0


def _spots(storms: Sequence[Typhoon]) -> list[tuple[float, float]]:
    """범위에 넣을 점 — 반경 끝까지, 현재 위치 아래 글자 자리까지."""
    out = []
    for s in storms:
        out.append((s.now.lon, s.now.lat - NAME_ROOM))
        reach = [(p, 0) for p in s.past] + [(s.now, max(_km(s.now.gale), _km(s.now.storm)))]
        reach += [(p, p.radius or 0) for p in s.forecast]
        for p, km in reach:
            deg = km / pacific.KM_PER_DEG
            out += [(p.lon - deg, p.lat - deg), (p.lon + deg, p.lat + deg)]
    return out


def _stamp(p: Point) -> str:
    """«20일 15시 990hPa» — 중심기압이 없으면 시각만."""
    return f"{p.at.day}일 {p.at.hour}시" + (f" {p.pressure}hPa" if p.pressure else "")


def _line(view: pacific.View, spots: Sequence[Point], cls: str) -> str:
    if len(spots) < 2:
        return ""
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (view.xy(p.lon, p.lat) for p in spots))
    return f'<polyline class="{cls}" points="{pts}"/>'


def _extent(view: pacific.View, p: Point, km: int | None) -> str:
    if not km:
        return ""
    x, y = view.xy(p.lon, p.lat)
    rx, ry = view.radii(p.lat, km)
    return f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{rx:.1f}" ry="{ry:.1f}"/>'


class _Labels:
    """예상 위치 글자 — 붙은 점(느린 태풍)끼리 겹치면 뒤의 것을 뺌."""
    def __init__(self) -> None:
        self.taken: list[Box] = []
        self.parts: list[str] = []

    def free(self, box: Box) -> bool:
        return not any(hits(box, t) for t in self.taken)

    def add(self, x: float, y: float, text: str, cls: str) -> None:
        if not self.free(box := text_box(x, y, text, size=WHEN_PX)):
            return
        self.taken.append(box)
        self.parts.append(f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}">{html.escape(text)}</text>')


def _name(storm: Typhoon) -> str:
    return f"제{storm.no}호 {storm.name}"


def _name_boxes(view: pacific.View, storm: Typhoon) -> list[Box]:
    """현재 위치 아래 두 줄(이름·시각)의 글자 상자 — 늘 그리므로 예상 글자보다 먼저 자리를 잡음."""
    x, y = view.xy(storm.now.lon, storm.now.lat)
    return [text_box(x, y + 25, _name(storm), 0.5, NAME_PX), text_box(x, y + 39, _stamp(storm.now), 0.5, WHEN_PX)]


def _track(view: pacific.View, storm: Typhoon, week_end: dt.date, labels: _Labels) -> tuple[dict[str, str], str]:
    """(반경 종류별 원, 경로·표지·글자). 바람 반경은 현재 위치에, 확률반경은 예상 위치에. 이번 주 뒤는 옅게."""
    extents = {"radius": "".join(_extent(view, p, p.radius) for p in storm.forecast),
               "gale": _extent(view, storm.now, _km(storm.now.gale)),
               "storm": _extent(view, storm.now, _km(storm.now.storm))}
    x, y = view.xy(storm.now.lon, storm.now.lat)
    name, stamp = _name(storm), _stamp(storm.now)
    marks = [f'<circle class="pt" cx="{px:.1f}" cy="{py:.1f}" r="2.2"/>'
             for px, py in (view.xy(p.lon, p.lat) for p in storm.past)]
    for p in storm.forecast:
        px, py = view.xy(p.lon, p.lat)
        later = "" if p.at.date() <= week_end else " later"
        marks.append(f'<circle class="fc{later}" cx="{px:.1f}" cy="{py:.1f}" r="3.6"/>')
        labels.add(px + 8, py + 4, _stamp(p), f"when{later}")
    path = (_line(view, [*storm.past, storm.now], "past") + _line(view, [storm.now, *storm.forecast], "ahead")
            + "".join(marks) + _now_mark(x, y)
            + f'<text class="name" x="{x:.1f}" y="{y + 25:.1f}" text-anchor="middle">{html.escape(name)}</text>'
            + f'<text class="when" x="{x:.1f}" y="{y + 39:.1f}" text-anchor="middle">{stamp}</text>')
    return extents, path


def _now_mark(x: float, y: float, ring: float = 9, dot: float = 5) -> str:
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{ring}" fill="#ffffff" fill-opacity="0.6" stroke="{NOW}" '
            f'stroke-width="2"/><circle cx="{x:.1f}" cy="{y:.1f}" r="{dot}" fill="{NOW}"/>')


def build_svg(storms: Sequence[Typhoon], week_end: dt.date) -> tuple[str, list[str]]:
    """(지도 SVG, 그린 반경 종류) — 범례는 실제로 그린 반경만 적음."""
    view = pacific.fit(_spots(storms), MAP_W, MAX_H, MIN_H)
    labels = _Labels()
    # 태풍이 여럿이면 앞 태풍의 예상 글자가 뒤 태풍의 이름에 겹치지 않게 이름 자리를 모두 먼저 잡음
    labels.taken += [box for s in storms for box in _name_boxes(view, s)]
    tracks = [_track(view, s, week_end, labels) for s in storms]
    # 경로 글자와 겹치는 지명은 뺌 — 괌처럼 경로 곁에 있는 곳
    places = "".join(svg for box, svg in pacific.places(view) if labels.free(box))
    drawn = [kind for kind, _ in EXTENTS if any(t[kind] for t, _ in tracks)]
    groups = "".join(f'<g class="{kind}">{"".join(t[kind] for t, _ in tracks)}</g>' for kind in drawn)
    svg = (f'<svg width="{view.width:.0f}" height="{view.height:.0f}" viewBox="0 0 {view.width:.0f} '
           f'{view.height:.0f}" role="img" aria-label="태풍 예상 경로 지도">{pacific.background(view)}{groups}{places}'
           f'{"".join(p for _, p in tracks)}{"".join(labels.parts)}</svg>')
    return svg, drawn


def _key(inner: str) -> str:
    return icon(inner, 22, 18)


MARKS = tuple((_key(inner), text) for inner, text in (
    (_now_mark(0, 0, ring=7, dot=4), "현재 위치"),
    ('<line class="past" x1="-9" y1="0" x2="9" y2="0"/><circle class="pt" r="2.2"/>', "지난 경로"),
    ('<line class="ahead" x1="-10" y1="0" x2="10" y2="0"/><circle class="fc" r="3.6"/>', "이번 주 예상"),
    ('<circle class="fc later" r="3.6"/>', "그 뒤 예상"),
))


def _legend(drawn: list[str]) -> str:
    swatches = [(_key(f'<g class="{kind}"><ellipse rx="7" ry="7"/></g>'), text)
                for kind, text in EXTENTS if kind in drawn]
    return legend(MARKS) + (legend(swatches) if swatches else "")


def build_html(storms: Sequence[Typhoon], week_start: dt.date) -> str:
    svg, drawn = build_svg(storms, week_end_of(week_start))
    rows = [("현재", now_line(s, html_bold, reach=True, plain=html.escape)) for s in storms]
    foot = f"{issued_text(storms)} · 바탕 지도 Natural Earth<br>기압선은 기상청 지상일기도에서 볼 수 있습니다."
    return Card("태풍 예상 경로", week_start, rows, f'<div class="map">{svg}{_legend(drawn)}</div>', foot).html(CSS)


def render_png(storms: Sequence[Typhoon], week_start: dt.date, *, scale: int = 2) -> bytes:
    return capture(build_html(storms, week_start), scale=scale)


# 확률반경은 예상 위치마다 겹쳐 그려 묶음째 옅게 — 겹친 곳이 진해지지 않고 한 덩어리로 보임
CSS = BASE_CSS + pacific.CSS + f"""
g.radius {{ opacity: 0.18; }}
g.radius ellipse {{ fill: {RADIUS_COLOR}; }}
g.gale ellipse {{ fill: {GALE_COLOR}; fill-opacity: 0.16; stroke: {GALE_COLOR}; stroke-width: 1.4; }}
g.storm ellipse {{ fill: {STORM_COLOR}; fill-opacity: 0.18; stroke: {STORM_COLOR}; stroke-width: 1.4; }}
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
