"""철 소식 지도의 바탕 — 남한 윤곽(Natural Earth, 퍼블릭 도메인)·투영·카드 공통 CSS. 단풍·첫눈 지도가 함께 씀."""
from __future__ import annotations

import functools
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path

from src.common.browser import CARD_WIDTH

ASSET = Path(__file__).parent / "assets" / "korea_provinces.json"


@dataclass(frozen=True)
class MapInfo:
    """지도마다 다른 이름표. slug 는 올릴 파일 이름 앞부분이자 보존 정리 패턴(slug-*.png)임."""
    name: str
    slug: str
    alt: str

    @property
    def title(self) -> str:
        return f"{self.name} 지도"

# 위도 36° 기준 등장방형 — 남한만 그려 이것으로 충분함
LON0, LON1, LAT0, LAT1 = 124.55, 130.35, 33.05, 38.68
_K = math.cos(math.radians(36))
_S = 74.0
MAP_W = (LON1 - LON0) * _K * _S
MAP_H = (LAT1 - LAT0) * _S
INSET = {"x": MAP_W - 60, "y": 70.0, "w": 56.0, "h": 46.0}
INSET_LON = 130.5            # 이보다 동쪽(울릉도·독도)은 상자 안에 그림


def proj(lon: float, lat: float) -> tuple[float, float]:
    return (lon - LON0) * _K * _S, (LAT1 - lat) * _S


def proj_inset(lon: float, lat: float) -> tuple[float, float]:
    # 울릉도는 실제 축척 그대로 상자 왼쪽에 둠
    return INSET["x"] + 10 + (lon - 130.80) * _K * _S, INSET["y"] + 12 + (37.56 - lat) * _S


def place(lon: float, lat: float) -> tuple[float, float]:
    return proj_inset(lon, lat) if lon > INSET_LON else proj(lon, lat)


def _path(ring: list[list[float]]) -> str:
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (place(lon, lat) for lon, lat in ring)) + "Z"


def label(x: float, y: float, name: str, side: str, strong: bool) -> str:
    """점 옆 이름. side 는 점의 어느 쪽에 붙는지 r/l/t/b."""
    dx, dy, anchor = {"r": (11, 4, "start"), "l": (-11, 4, "end"),
                      "t": (0, -11, "middle"), "b": (0, 19, "middle")}[side]
    cls = "lbl strong" if strong else "lbl"
    return (f'<text class="{cls}" x="{x + dx:.1f}" y="{y + dy:.1f}" text-anchor="{anchor}">'
            f'{html.escape(name)}</text>')


def frame(inner: str, aria_label: str) -> str:
    """바탕 지도를 깐 SVG. 지도 끝에 붙은 점(백령도)이 잘리지 않게 카드 여백까지 그림."""
    return (f'<svg width="{MAP_W:.0f}" height="{MAP_H:.0f}" viewBox="0 0 {MAP_W:.0f} {MAP_H:.0f}" '
            f'overflow="visible" role="img" aria-label="{aria_label}">{basemap()}{inner}</svg>')


@functools.cache
def basemap() -> str:
    doc = json.loads(ASSET.read_text(encoding="utf-8"))
    main, islands = [], []
    for prov in doc["provinces"]:
        d_main = "".join(_path(r) for r in prov["rings"] if r[0][0] <= INSET_LON)
        d_isl = "".join(_path(r) for r in prov["rings"] if r[0][0] > INSET_LON)
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


# 카드 틀·지도·표 — 지도마다 다른 것(.lead 바탕색·표 칸)은 각 지도에서 덧붙임
BASE_CSS = f"""
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
.lead {{ margin: 8px 0 14px; padding: 9px 12px; border-radius: 8px; font-size: 13.5px; }}
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
.obs {{ font-weight: 700; color: var(--ink); }}
.none {{ color: #c3c2b7; }}
.foot {{ margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--hair);
         font-size: 11.5px; color: var(--muted); line-height: 1.55; }}
"""
