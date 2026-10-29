"""철 소식 지도의 바탕 — 남한 윤곽(Natural Earth, 퍼블릭 도메인)·투영·카드 공통 CSS. 단풍·첫눈 지도가 함께 씀."""
from __future__ import annotations

import functools
import json
import math
from pathlib import Path

from src.common.browser import CARD_WIDTH

ASSET = Path(__file__).parent / "assets" / "korea_provinces.json"

# 위도 36° 기준 등장방형 — 남한만 그려 이것으로 충분함
LON0, LON1, LAT0, LAT1 = 124.55, 130.35, 33.05, 38.68
_K = math.cos(math.radians(36))
_S = 74.0
MAP_W = (LON1 - LON0) * _K * _S
MAP_H = (LAT1 - LAT0) * _S
INSET = {"x": MAP_W - 60, "y": 70.0, "w": 56.0, "h": 46.0}


def proj(lon: float, lat: float) -> tuple[float, float]:
    return (lon - LON0) * _K * _S, (LAT1 - lat) * _S


def proj_inset(lon: float, lat: float) -> tuple[float, float]:
    # 울릉도는 실제 축척 그대로 상자 왼쪽에 둠
    return INSET["x"] + 10 + (lon - 130.80) * _K * _S, INSET["y"] + 12 + (37.56 - lat) * _S


def _path(ring: list[list[float]], inset: bool = False) -> str:
    f = proj_inset if inset else proj
    pts = [f(lon, lat) for lon, lat in ring]
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"


@functools.cache
def basemap() -> str:
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
.foot {{ margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--hair);
         font-size: 11.5px; color: var(--muted); line-height: 1.55; }}
"""
