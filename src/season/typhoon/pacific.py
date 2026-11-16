"""태풍 지도의 바탕 — 북서태평양 육지(Natural Earth, 퍼블릭 도메인)를 경로에 맞춘 범위로 그림. 한국은 진하게.

남한 지도(season/basemap)는 축척이 달라 따로 둠 — 시도 윤곽만 빌려 한국을 칠함.
"""
from __future__ import annotations

import functools
import html
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.season.basemap import ASSET as KOREA_ASSET
from src.season.basemap import Box, text_box

ASSET = Path(__file__).parents[1] / "assets" / "pacific_land.json"
KOREA = ((124.0, 33.0), (131.0, 38.8))       # 늘 보이게 — 태풍이 멀어도 한국과의 거리가 보여야 함
PAD = 2.5                                     # 경로·확률반경 밖 여백(도)
KM_PER_DEG = 111.32
# 위치 설명(«괌 남동쪽 약 1370 km»)에 자주 나오는 곳 — 범위 안에 들 때만 씀
PLACES = (("한국", 128.4, 35.6, True), ("일본", 138.8, 36.6, False), ("중국", 113.5, 31.0, False),
          ("타이완", 121.0, 23.6, False), ("필리핀", 122.5, 14.5, False), ("오키나와", 127.9, 26.3, False),
          ("괌", 144.8, 13.4, False))
PLACE_PX = {False: 11.5, True: 12.5}          # CSS 의 .place · .place.strong 글자 크기


@dataclass(frozen=True)
class View:
    """등장방형(가운데 위도 기준) — 범위가 넓지 않아 이것으로 충분함."""
    lon0: float
    lon1: float
    lat0: float
    lat1: float
    width: float

    @property
    def _k(self) -> float:
        return math.cos(math.radians((self.lat0 + self.lat1) / 2))

    @property
    def scale(self) -> float:
        return self.width / ((self.lon1 - self.lon0) * self._k)

    @property
    def height(self) -> float:
        return (self.lat1 - self.lat0) * self.scale

    def xy(self, lon: float, lat: float) -> tuple[float, float]:
        return (lon - self.lon0) * self._k * self.scale, (self.lat1 - lat) * self.scale

    def radii(self, lat: float, km: float) -> tuple[float, float]:
        """반지름 km 원의 가로·세로 픽셀 — 경도 1도는 위도가 높을수록 짧음."""
        deg = km / KM_PER_DEG
        return deg / math.cos(math.radians(lat)) * self._k * self.scale, deg * self.scale


Rings = list[list[list[float]]]


@functools.cache
def _assets() -> tuple[tuple[float, float, float, float], Rings, Rings]:
    """(자료 범위 경도0·위도0·경도1·위도1, 육지 고리, 한국 시도 고리) — 파일마다 한 번만 읽음."""
    land = json.loads(ASSET.read_text(encoding="utf-8"))
    korea = [r for prov in json.loads(KOREA_ASSET.read_text(encoding="utf-8"))["provinces"] for r in prov["rings"]]
    return tuple(land["bounds"]), land["rings"], korea


def _span(lo: float, hi: float, need: float, floor: float, ceil: float) -> tuple[float, float]:
    """[lo, hi] 를 가운데 두고 need 만큼 넓힘 — 자료 범위 밖으로 나가면 안쪽으로 밂."""
    grow = max(0.0, need - (hi - lo)) / 2
    lo, hi = lo - grow, hi + grow
    shift = max(0.0, floor - lo) - max(0.0, hi - ceil)
    return max(floor, lo + shift), min(ceil, hi + shift)


def fit(spots: Iterable[tuple[float, float]], width: float, max_height: float, min_height: float) -> View:
    """점(경도, 위도)과 한국을 다 담는 범위. 너무 길쭉하면 짧은 쪽을 넓혀 카드에 맞춤."""
    lons, lats = zip(*[*spots, *KOREA], strict=True)
    b_lon0, b_lat0, b_lon1, b_lat1 = _assets()[0]
    lon0, lon1 = max(b_lon0, min(lons) - PAD), min(b_lon1, max(lons) + PAD)
    lat0, lat1 = max(b_lat0, min(lats) - PAD), min(b_lat1, max(lats) + PAD)
    k = math.cos(math.radians((lat0 + lat1) / 2))
    lat0, lat1 = _span(lat0, lat1, (lon1 - lon0) * k * min_height / width, b_lat0, b_lat1)
    lon0, lon1 = _span(lon0, lon1, (lat1 - lat0) * width / max_height / k, b_lon0, b_lon1)
    return View(lon0, lon1, lat0, lat1, width)


def _path(view: View, ring: list[list[float]]) -> str:
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (view.xy(lon, lat) for lon, lat in ring)) + "Z"


def _grid(view: View) -> tuple[str, str]:
    """(경위선, 도수 글자) — 글자는 육지 위에 얹어 가려지지 않게."""
    step = 5 if view.lon1 - view.lon0 < 25 else 10
    lines, marks = [], []
    for lon in range(math.ceil(view.lon0 / step) * step, math.floor(view.lon1) + 1, step):
        x, _ = view.xy(lon, view.lat0)
        lines.append(f'<line class="grid" x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{view.height:.1f}"/>')
        marks.append(f'<text class="deg" x="{x + 3:.1f}" y="{view.height - 5:.1f}">{lon}°E</text>')
    for lat in range(math.ceil(view.lat0 / step) * step, math.floor(view.lat1) + 1, step):
        _, y = view.xy(view.lon0, lat)
        lines.append(f'<line class="grid" x1="0" y1="{y:.1f}" x2="{view.width:.1f}" y2="{y:.1f}"/>')
        marks.append(f'<text class="deg" x="4" y="{y - 3:.1f}">{lat}°N</text>')
    return "".join(lines), "".join(marks)


def places(view: View) -> list[tuple[Box, str]]:
    """범위 안 지명 (글자 상자, SVG) — 경로 글자와 겹치는 것은 지도 쪽에서 뺌."""
    out = []
    for name, lon, lat, strong in PLACES:
        if view.lon0 + 1 < lon < view.lon1 - 1 and view.lat0 + 1 < lat < view.lat1 - 1:
            x, y = view.xy(lon, lat)
            cls = "place strong" if strong else "place"
            out.append((text_box(x, y, name, 0.5, PLACE_PX[strong]),
                        f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="middle">{html.escape(name)}</text>'))
    return out


def background(view: View) -> str:
    """바다·격자·육지·한국."""
    _, land, korea = _assets()
    lines, marks = _grid(view)
    return (f'<rect class="sea" width="{view.width:.1f}" height="{view.height:.1f}"/>{lines}'
            f'<path class="land" d="{"".join(_path(view, r) for r in land)}"/>'
            f'<path class="korea" d="{"".join(_path(view, r) for r in korea)}"/>{marks}')


CSS = """
.sea { fill: #f3f7fb; }
.grid { stroke: #e3e9ef; stroke-width: 1; }
.deg { font-size: 9.5px; fill: #a3a19a; paint-order: stroke; stroke: #f3f7fb; stroke-width: 2.5px; }
.land { fill: #e6e4dc; }
.korea { fill: #c4c1b4; }
.place { font-size: 11.5px; fill: #898781; paint-order: stroke; stroke: #f3f7fb; stroke-width: 3px; }
.place.strong { fill: #0b0b0b; font-weight: 700; font-size: 12.5px; stroke: #ffffff; }
"""
