"""더위 지도 — 중기예보 도시 표의 낮 최고를 도시마다 찍고 기상청 폭염일 기준(33℃↑)에 닿는 곳을 🥵 로 표시함.

도시별 값은 중기예보에만 있음(통보문은 전국 범위뿐) — 지도는 그 날들만 그리고 그 기간을 밝힘. 표의 값만 옮기고
어림하지 않음. 41곳이 붙어 있어 라벨은 더운 곳부터 자리가 나는 것만 닮 — 겹칠 바에야 라벨을 뺌.
"""
from __future__ import annotations

import datetime as dt

from src.common.browser import capture
from src.common.text import WEEKDAY_KO, html_bold, short_day_label
from src.season.basemap import (
    BASE_CSS,
    INSET_BOX,
    MAP_W,
    OFFSETS,
    Box,
    MapInfo,
    frame,
    hits,
    label,
    label_box,
    place,
)
from src.season.heat.cities import SPOTS
from src.season.heat.data import HEAT_DAY, TROPICAL_NIGHT, Heat
from src.season.heat.text import (
    FORECAST_SOURCE,
    HOT_LABEL,
    NIGHT_LABEL,
    hot_line,
    night_line,
)
from src.season.mapcard import Card, body, glyph, glyph_size, hollow, icon, legend

INFO = MapInfo("더위", "heat", "중기예보 도시별 낮 최고·아침 최저로 그린 폭염일·열대야 기준 지도")

# 기준 미만은 다른 지도의 «없음·아직» 과 같은 회색 빈 원 — 모양으로 가름
HOT_R = 4                # 🥵 15px
MAX_ROWS = 20           # 표가 지도보다 길어지지 않게 — 나머지는 «외 N곳»
CRITERIA = (f"기준 기상청 기후통계 — 폭염일 «일 최고기온이 {HEAT_DAY:.0f}℃ 이상인 날» · 열대야 «밤최저기온이 "
            f"{TROPICAL_NIGHT:.0f}℃ 이상인 날(18:01~익일 09:00)». 표의 열대야는 예보의 아침 최저로 가늠함. "
            "폭염특보(체감온도 기준)와 다름")

LABEL_PX = 10.5          # CSS 의 .lbl 과 같게


def _free(box: Box, taken: list[Box], name: str) -> bool:
    inside = name == "울릉도" or not hits(box, INSET_BOX)
    return box[0] >= -16 and box[2] <= MAP_W + 8 and inside and not any(hits(box, t) for t in taken)


def _marks(heat: Heat) -> str:
    """표지는 모두, 라벨은 더운 곳부터 다른 표지·라벨·울릉도 상자와 겹치지 않는 자리에만."""
    placed = [(c, *place(s.lon, s.lat), s.label) for c in heat.cities if (s := SPOTS.get(c.name))]
    # 남의 표지 바로 옆에 붙은 라벨은 그 도시 값으로 읽혀 좌우를 3 더 비움
    px, py = glyph_size(HOT_R) / 2 + 3, glyph_size(HOT_R) / 2
    around = {c.name: (x - px, y - py, x + px, y + py) for c, x, y, _ in placed}
    left, _, right, bottom = INSET_BOX
    labels_taken: list[Box] = [(left, bottom - 14, right, bottom)]       # 상자 안 «울릉도·독도» 글자
    marks, labels = [], []
    for city, x, y, side in sorted(placed, key=lambda p: -p[0].high[1]):
        marks.append(glyph("hot", x, y, HOT_R) if city.hot else hollow(x, y))
        text = f"{city.name} {city.high[1]:.0f}"
        others = [b for name, b in around.items() if name != city.name] + labels_taken
        for s in dict.fromkeys((side, *OFFSETS)):                   # 정해 둔 자리부터
            if _free(box := label_box(x, y, text, s, LABEL_PX), others, city.name):
                labels_taken.append(box)
                labels.append(label(x, y, text, s, strong=city.hot))
                break
    return "".join(marks) + "".join(labels)


def _legend() -> str:
    return legend(((icon(glyph("hot", 0, 0, 3.5), 16), f"낮 최고 {HEAT_DAY:.0f}℃↑"),
                   (icon(hollow(0, 0, 5), 14), f"낮 최고 {HEAT_DAY:.0f}℃ 미만")),
                  "숫자는 그 기간 낮 최고(℃) · 자리가 없는 곳은 라벨을 뺌")


def _cell(value: tuple[dt.date, float], met: bool) -> str:
    day, temp = value
    text = f"{temp:.0f} <small>{WEEKDAY_KO[day.weekday()]}</small>"
    return f'<td class="{"met" if met else "muted"}">{text}</td>'


def _table(heat: Heat) -> str:
    """기준(낮 33℃↑ 또는 아침 25℃↑)에 닿는 도시만, 낮 최고가 높은 차례로 MAX_ROWS 까지."""
    hit = sorted((c for c in heat.cities if c.hot or c.tropical), key=lambda c: -c.high[1])
    shown = hit[:MAX_ROWS]
    rest = f" — 낮 최고 순 {len(shown)}곳 (외 {len(hit) - len(shown)}곳)" if len(hit) > len(shown) else ""
    caption = (f"기준에 닿는 도시 <b>{len(hit)}곳</b> / {len(heat.cities)}곳{rest}" if hit
               else f"기준에 닿는 도시가 없습니다 ({len(heat.cities)}곳 중)")
    rows = "".join(f'<tr><th scope="row">{c.name}</th>{_cell(c.high, c.hot)}{_cell(c.low, c.tropical)}</tr>'
                   for c in shown)
    return (f"<table><caption>{caption}</caption><thead><tr><th>도시</th><th>낮 최고</th><th>아침 최저</th></tr>"
            f"</thead><tbody>{rows}</tbody></table>")


def _span(heat: Heat) -> str:
    first, last = min(heat.city_days), max(heat.city_days)
    return short_day_label(first) if first == last else f"{short_day_label(first)}~{short_day_label(last)}"


def _lead(heat: Heat) -> list[tuple[str, str]]:
    """주간 문단과 같은 줄(지역 범위, 그 주 전체) + 도시별 한 줄."""
    hot = sum(c.hot for c in heat.cities)
    night = sum(c.tropical for c in heat.cities)
    cities = (f"{_span(heat)} {len(heat.cities)}곳 중 {HEAT_DAY:.0f}℃↑ <b>{hot}곳</b> · "
              f"아침 {TROPICAL_NIGHT:.0f}℃↑ <b>{night}곳</b>") if heat.cities else ""
    return [(HOT_LABEL, hot_line(heat, html_bold)), (NIGHT_LABEL, night_line(heat, html_bold)), ("도시별", cities)]


def build_html(heat: Heat, week_start: dt.date) -> str:
    """heat.cities 가 비어 있으면 부르지 않음(themes 가 글만 올림)."""
    note = f"도시별 값은 중기예보 도시 표에만 있어 {_span(heat)}만 그림(그 앞은 통보문이 지역 범위만 줌)"
    left = f"<h2>도시별 예보 {_span(heat)}</h2>{frame(_marks(heat), INFO.alt)}{_legend()}"
    foot = f"{FORECAST_SOURCE} · {note}<br>{CRITERIA}"
    return Card("더위 지도", week_start, _lead(heat), body(left, _table(heat)), foot).html(CSS)


def render_png(heat: Heat, week_start: dt.date, *, scale: int = 2) -> bytes:
    return capture(build_html(heat, week_start), scale=scale)


CSS = BASE_CSS + f".body .map {{ width: {MAP_W:.0f}px; }}" + """
.lead { background: #fdf0e6; }
.lead .k { width: 104px; }
.lbl { font-size: 10.5px; }
td.met { font-weight: 700; color: var(--ink); }
td small { font-size: 11px; font-weight: 400; color: var(--ink2); }
td.muted small { color: var(--muted); }
"""
