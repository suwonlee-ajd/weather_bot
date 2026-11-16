"""벚꽃 지도 — 웨더아이 19개 도시의 개화 예상일을 한 장으로 그림.

기상청 군락지 관측은 싣지 않음 — 장소 이름(여의도 윤중로 · 진해 여좌천 …)이 낯설어 읽는 사람에게 닿지 않음(사용자 결정).
"""
from __future__ import annotations

import datetime as dt

from src.common.browser import capture
from src.common.text import day_label, html_bold, short_date
from src.season.basemap import BASE_CSS, MapInfo, emoji, frame, label, place
from src.season.blossom.data import Outlook
from src.season.blossom.spots import CITY_BY_NAME
from src.season.blossom.text import week_line, year_line
from src.season.sources import OUTLOOK_SOURCE

INFO = MapInfo("벚꽃", "blossom", "19개 도시의 벚꽃 개화 예상(웨더아이) 지도")

# 예상일이 뒤면 회색 빈 원 · 이번 주면 옅은 🌸 와 점선 고리 · 지났으면 🌸 (단풍 지도와 같은 짜임)
GRAY = "#898781"
BLOOM_OPACITY = 0.65         # 🌸 는 원래 연분홍이라 단풍(0.45)보다 덜 옅게 — 더 옅으면 바탕에 묻힘
# 단풍(6.5 · 고리 +3)보다 작고 고리도 붙여 그림 — 서울·수원, 청주·대전은 20~22px 거리라 함께 이번 주면 고리가 겹침
MARK_R, RING_GAP = 5.5, 1
# 고리 두른 도시의 라벨만 바깥으로 — 기본 자리(11px)는 고리에 닿아 낱말 사이로 고리가 비침(«강릉·4/1»)
RING_LABEL_PAD = 2
NOTE = "날짜는 도시마다 기상관서 표준목 기준입니다."
LEGEND = {"예상": {"later": "개화 예상 전", "week": "이번 주 개화 예상", "past": "개화 예상일 지남"},
          "평년": {"later": "평년 개화일 전", "week": "평년 개화일 이번 주", "past": "평년 개화일 지남"}}


def _when(day: dt.date, start: dt.date, end: dt.date) -> str:
    return "past" if day < start else "week" if day <= end else "later"


def _marker(x: float, y: float, when: str, r: float = MARK_R) -> str:
    if when == "later":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fcfcfb" stroke="{GRAY}" stroke-width="2"/>'
    size = 2 * r + 7          # 그림은 여백이 있어 같은 크기면 빈 원보다 작아 보임
    if when == "past":
        return emoji("blossom", x, y, size)
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size / 2 + RING_GAP}" fill="none" stroke="#0b0b0b" '
            f'stroke-width="1.4" stroke-dasharray="2.6 2.2"/>' + emoji("blossom", x, y, size, opacity=BLOOM_OPACITY))


def _icon(when: str) -> str:
    # 상자는 가장 큰 이번 주 고리에 맞춤 — 표지마다 크기가 달라 글자 줄이 들쭉날쭉하지 않게
    return f'<svg width="22" height="22" viewBox="-11.5 -11.5 23 23">{_marker(0, 0, when, r=4.5)}</svg>'


def _label(x: float, y: float, text: str, side: str, ring: bool) -> str:
    """이번 주(고리)는 굵게, 라벨을 바깥으로 조금 밀어 둠."""
    pad = RING_LABEL_PAD if ring else 0
    dx, dy = {"r": (pad, 0), "l": (-pad, 0), "t": (0, -pad), "b": (0, pad)}[side]
    return label(x + dx, y + dy, text, side, strong=ring)


def _marks(days: dict[str, dt.date], start: dt.date, end: dt.date) -> tuple[str, set[str]]:
    """표지 + 라벨 SVG 와 지도에 나온 when 들."""
    marks, labels, seen = [], [], set()
    for name, day in days.items():
        if (spot := CITY_BY_NAME.get(name)) is None:      # 새로 생긴 도시 — 좌표가 없어 표에만
            continue
        x, y = place(spot.lon, spot.lat)
        when = _when(day, start, end)
        seen.add(when)
        marks.append(_marker(x, y, when))
        text = _label(x, y, f"{name} {short_date(day)}", spot.label, ring=when == "week")
        labels.append(f'<g class="past">{text}</g>' if when == "past" else text)
    return "".join(marks) + "".join(labels), seen


def _city_rows(days: dict[str, dt.date], normal: dict[str, dt.date] | None, start: dt.date, end: dt.date) -> str:
    """도시 표 — 길어서 두 갈래로 나눠 한 줄에 두 도시. normal 이 None 이면 평년 칸 없음(날짜가 곧 평년)."""
    def cells(name: str) -> str:
        day = days[name]
        out = f'<th scope="row">{name}</th><td><span class="prd {_when(day, start, end)}">{short_date(day)}</span></td>'
        if normal is not None:
            out += f'<td class="muted">{short_date(normal[name]) if name in normal else "–"}</td>'
        return out

    ordered = sorted(days, key=lambda c: (days[c], CITY_BY_NAME[c].lat if c in CITY_BY_NAME else 0.0))
    half = (len(ordered) + 1) // 2
    blank = "<td></td>" * (2 if normal is None else 3)
    return "".join(
        f'<tr>{cells(left)}<td class="gap"></td>'
        + (cells(ordered[i + half]) if i + half < len(ordered) else blank) + "</tr>"
        for i, left in enumerate(ordered[:half])
    )


def _lead(outlook: Outlook, start: dt.date, end: dt.date) -> str:
    """주간 문단과 같은 줄."""
    rows = (("이번 주", week_line(outlook, start, end, html_bold)),
            ("올해" if outlook.expected else "평년", year_line(outlook, html_bold)))
    return "".join(f'<div><span class="k">{k}</span><span>{v}</span></div>' for k, v in rows if v)


def _foot(outlook: Outlook) -> str:
    if outlook.expected:
        when = f"{short_date(outlook.published)} 발표, " if outlook.published else ""
        source = f"예상 {OUTLOOK_SOURCE} ({when}{len(outlook.expected)}개 도시)"
    else:
        source = f"평년 {OUTLOOK_SOURCE} 지난해 표"
    return f"{source}<br>{NOTE}"


def build_html(outlook: Outlook, week_start: dt.date) -> str:
    """올해 표가 없으면 지난해 표의 평년으로 — 제목·범례·표 머리도 «평년»."""
    week_end = week_start + dt.timedelta(days=6)
    days = outlook.expected or outlook.normal
    kind = "예상" if outlook.expected else "평년"
    marks, seen = _marks(days, week_start, week_end)
    legend = "".join(f"<span>{_icon(when)}{text}</span>" for when, text in LEGEND[kind].items() if when in seen)
    head = "<th>도시</th><th>예상</th><th>평년</th>" if outlook.expected else "<th>도시</th><th>평년</th>"
    rows = _city_rows(days, outlook.normal if outlook.expected else None, week_start, week_end)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div id="card">
  <div class="head"><h1>벚꽃 지도</h1><span class="period">{day_label(week_start)} ~ {day_label(week_end)}</span></div>
  <div class="lead">{_lead(outlook, week_start, week_end)}</div>
  <h2><span class="k">{kind}</span>{OUTLOOK_SOURCE} {len(days)}개 도시</h2>
  <div class="pane">
    <div class="map">{frame(marks, f"{len(days)}개 도시 벚꽃 개화 {kind} 지도")}<div class="legend">{legend}</div></div>
    <table class="cities"><thead><tr>{head}<th class="gap"></th>{head}</tr></thead><tbody>{rows}</tbody></table>
  </div>
  <div class="foot">{_foot(outlook)}</div>
</div></body></html>"""


def render_png(outlook: Outlook, week_start: dt.date, *, scale: int = 2) -> bytes:
    return capture(build_html(outlook, week_start), scale=scale)


CSS = BASE_CSS + """
.lead { background: #fbf0f4; }
.pane { display: flex; gap: 18px; align-items: flex-start; }
.pane .map { flex: none; }
h2 { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
h2 .k { display: inline-block; font-size: 12px; font-weight: 600; color: var(--ink2); background: #f0efec;
        border-radius: 4px; padding: 0 6px; margin-right: 6px; }
.past .lbl { fill: var(--muted); }
.prd.past { color: var(--muted); }
.prd.week { font-weight: 600; background: #fbdde9; border-radius: 4px; padding: 0 4px; margin: 0 -4px; }
.cities .gap { width: 14px; border: none; }
"""
