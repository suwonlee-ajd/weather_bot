"""벚꽃 지도 — 웨더아이 도시 개화 예상을 한 장으로 그림(사용자 결정: 지도는 도시 기준).

두 자료는 장소부터 다름(군락지 13곳 · 도시 19곳). 한 장에 겹치면 여의도·서울처럼 붙은 점이 한 곳으로 읽혀
지도엔 도시만 — 기상청 군락지 관측은 머리 줄(관측)과 꼬리말에 씀. 예상을 못 받았을 때만 군락지 지도.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from src.common.browser import capture
from src.common.text import day_label, html_bold, short_date
from src.season.basemap import BASE_CSS, MapInfo, emoji, frame, label, place
from src.season.blossom.data import STAGES, Outlook, Status
from src.season.blossom.spots import CITY_BY_NAME, SITE_BY_NAME
from src.season.blossom.text import observed_line, week_line, year_line
from src.season.sources import OUTLOOK_SOURCE

INFO = MapInfo("벚꽃", "blossom", "벚꽃 군락지 13곳의 관측(기상청)과 19개 도시의 개화 예상(웨더아이) 지도")

# 군락지는 개화 전 회색 빈 원 · 개화 옅은 🌸 · 만발 🌸 (단풍 지도와 같은 짜임). 예상(도시)은 🌸 를 쓰지 않고
# 마름모 — 지도의 꽃은 관측만 뜻하게
GRAY, INK2, PALE = "#898781", "#52514e", "#c3c2b7"
BLOOM_OPACITY = 0.65         # 🌸 는 원래 연분홍이라 단풍(0.45)보다 덜 옅게 — 더 옅으면 바탕에 묻힘
NOTE = "관측은 기상청이 군락지에서, 예상은 웨더아이가 도시마다 기상관서 표준목을 기준으로 냅니다."


@dataclass(frozen=True)
class _Panel:
    """지도 한 장과 그 옆 표 — 바탕은 그릴 때 깜."""
    kind: str                 # 관측 · 예상 · 평년
    title: str
    marks: str                # 표지 + 라벨 SVG
    aria: str
    legend: str
    table: str = ""


def _site_marker(x: float, y: float, stage: int, r: float = 6.5) -> str:
    if stage == 0:
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fcfcfb" stroke="{GRAY}" stroke-width="2"/>'
    # 그림은 여백이 있어 같은 크기면 빈 원보다 작아 보임
    return emoji("blossom", x, y, 2 * r + 7, opacity=BLOOM_OPACITY if stage == 1 else 1.0)


def _city_marker(x: float, y: float, when: str, r: float = 4.5) -> str:
    """마름모 — when 은 날짜가 이번 주보다 앞(past)·이번 주(week)·뒤(later)."""
    diamond = f"M{x:.1f},{y - r:.1f}L{x + r:.1f},{y:.1f}L{x:.1f},{y + r:.1f}L{x - r:.1f},{y:.1f}Z"
    if when == "week":
        return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 4}" fill="none" stroke="#0b0b0b" '
                f'stroke-width="1.4" stroke-dasharray="2.6 2.2"/><path d="{diamond}" fill="#0b0b0b"/>')
    stroke = PALE if when == "past" else INK2
    return f'<path d="{diamond}" fill="#fcfcfb" stroke="{stroke}" stroke-width="1.6"/>'


def _icon(marker: str, size: int = 14) -> str:
    half = size / 2
    return f'<svg width="{size}" height="{size}" viewBox="-{half} -{half} {size} {size}">{marker}</svg>'


def _when(day: dt.date, start: dt.date, end: dt.date) -> str:
    return "past" if day < start else "week" if day <= end else "later"


def _site_rows(status: Status) -> str:
    def cell(day: dt.date | None, reached: bool) -> str:
        if day or reached:              # 단계는 올랐는데 촬영일이 아직 없으면 «관측»
            return f'<span class="obs">{short_date(day) if day else "관측"}</span>'
        return '<span class="none">–</span>'

    def order(item: tuple[str, int]):
        # 핀 곳은 개화일 순, 아직인 곳은 남쪽부터 — 꽃이 올라오는 차례
        name, stage = item
        spot = SITE_BY_NAME.get(name)
        return (stage == 0, status.bloom.get(name) or dt.date.min, spot.lat if spot else 90.0)

    return "".join(
        f'<tr><th scope="row">{name}</th>'
        f'<td class="st">{_icon(_site_marker(0, 0, stage, r=5), size=18)}<span>{STAGES[stage]}</span></td>'
        f'<td>{cell(status.bloom.get(name), stage >= 1)}</td><td>{cell(status.full.get(name), stage >= 2)}</td></tr>'
        for name, stage in sorted(status.stages.items(), key=order)
    )


def _site_panel(status: Status) -> _Panel:
    marks, labels = [], []
    for name, stage in status.stages.items():
        if (spot := SITE_BY_NAME.get(name)) is None:      # 새로 생긴 군락지 — 좌표가 없어 표에만
            continue
        x, y = place(spot.lon, spot.lat)
        marks.append(_site_marker(x, y, stage))
        labels.append(label(x, y, name, spot.label, strong=stage > 0))
    n = len(status.stages)
    legend = "".join(f"<span>{_icon(_site_marker(0, 0, k, r=5), size=18)}{STAGES[k]}</span>" for k in range(3))
    return _Panel("관측", f"기상청 군락지 {n}곳", "".join(marks) + "".join(labels),
                  f"벚꽃 군락지 {n}곳 관측 지도", legend,
                  f"<table><thead><tr><th>군락지</th><th>현황</th><th>개화</th><th>만발</th></tr></thead>"
                  f"<tbody>{_site_rows(status)}</tbody></table>")


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


def _city_panel(outlook: Outlook, start: dt.date, end: dt.date) -> _Panel:
    """올해 예상 전이면 지난해 표의 평년으로 — 제목·범례·표 머리도 «평년»."""
    days = outlook.expected or outlook.normal
    kind = "예상" if outlook.expected else "평년"
    marks, labels, seen = [], [], set()
    for name, day in days.items():
        if (spot := CITY_BY_NAME.get(name)) is None:
            continue
        x, y = place(spot.lon, spot.lat)
        when = _when(day, start, end)
        seen.add(when)
        marks.append(_city_marker(x, y, when))
        text = label(x, y, f"{name} {short_date(day)}", spot.label, strong=when == "week")
        labels.append(f'<g class="past">{text}</g>' if when == "past" else text)

    legend = [f"<span>{_icon(_city_marker(0, 0, 'later'))}{kind} 개화일</span>",
              f"<span>{_icon(_city_marker(0, 0, 'week', r=3.5), 18)}이번 주</span>"]
    if "past" in seen:
        legend.append(f"<span>{_icon(_city_marker(0, 0, 'past'))}지남</span>")
    head = "<th>도시</th><th>예상</th><th>평년</th>" if outlook.expected else "<th>도시</th><th>평년</th>"
    rows = _city_rows(days, outlook.normal if outlook.expected else None, start, end)
    return _Panel(kind, f"{OUTLOOK_SOURCE} {len(days)}개 도시", "".join(marks) + "".join(labels),
                  f"{len(days)}개 도시 벚꽃 개화 {kind} 지도", "".join(legend),
                  f'<table class="cities"><thead><tr>{head}<th class="gap"></th>{head}</tr></thead>'
                  f"<tbody>{rows}</tbody></table>")


def _layout(panel: _Panel | None) -> str:
    """단풍 지도처럼 지도 옆에 표."""
    if panel is None:
        return ""
    return (f'<h2><span class="k">{panel.kind}</span>{panel.title}</h2><div class="pane">'
            f'<div class="map">{frame(panel.marks, panel.aria)}<div class="legend">{panel.legend}</div></div>'
            f'{panel.table}</div>')


def _lead(status: Status | None, outlook: Outlook | None, start: dt.date, end: dt.date) -> str:
    """주간 문단과 같은 줄 — 못 받은 쪽은 뺌."""
    rows = []
    if status is not None:
        rows.append(("관측", observed_line(status, html_bold)))
    if outlook is not None:
        rows.append(("이번 주", week_line(outlook, start, end, html_bold)))
        rows.append(("올해" if outlook.expected else "평년", year_line(outlook, html_bold)))
    return "".join(f'<div><span class="k">{k}</span><span>{v}</span></div>' for k, v in rows if v)


def _foot(status: Status | None, outlook: Outlook | None) -> str:
    bits = []
    if status is None:
        bits.append("기상청 관측은 받지 못했습니다")
    else:
        updated = max([*status.bloom.values(), *status.full.values()], default=None)
        bits.append("관측 기상청 날씨누리 봄꽃 개화 현황" + (f" ({short_date(updated)} 관측까지)" if updated else ""))
    if outlook is None:
        bits.append(f"{OUTLOOK_SOURCE} 예상은 받지 못했습니다")
    elif outlook.expected:
        when = f"{short_date(outlook.published)} 발표, " if outlook.published else ""
        bits.append(f"예상 {OUTLOOK_SOURCE} ({when}{len(outlook.expected)}개 도시)")
    elif outlook.normal:
        bits.append(f"평년 {OUTLOOK_SOURCE} 지난해 표")
    return " · ".join(bits) + f"<br>{NOTE}"


def build_html(status: Status | None, outlook: Outlook | None, week_start: dt.date) -> str:
    """지도는 늘 한 장, 도시 기준 — 웨더아이 도시 예상(올해 표가 없으면 지난해 표의 평년). 군락지 관측은 머리 줄·꼬리말에.

    예상을 못 받았을 때만 군락지 지도 — 관측 전(서비스 밖)이면 그것도 그리지 않음: 단계가 모두 0 이라 «개화 전» 으로
    보이면 관측한 것처럼 읽힘. 둘 중 하나는 None 일 수 있음.
    """
    week_end = week_start + dt.timedelta(days=6)
    panel = None
    if outlook is not None and (outlook.expected or outlook.normal):
        panel = _city_panel(outlook, week_start, week_end)
    elif status is not None and status.in_service:
        panel = _site_panel(status)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div id="card">
  <div class="head"><h1>벚꽃 지도</h1><span class="period">{day_label(week_start)} ~ {day_label(week_end)}</span></div>
  <div class="lead">{_lead(status, outlook, week_start, week_end)}</div>
  {_layout(panel)}
  <div class="foot">{_foot(status, outlook)}</div>
</div></body></html>"""


def render_png(status: Status | None, outlook: Outlook | None, week_start: dt.date, *, scale: int = 2) -> bytes:
    return capture(build_html(status, outlook, week_start), scale=scale)


CSS = BASE_CSS + """
.lead { background: #fbf0f4; }
.pane { display: flex; gap: 18px; align-items: flex-start; }
.pane .map { flex: none; }
h2 { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
h2 .k { display: inline-block; font-size: 12px; font-weight: 600; color: var(--ink2); background: #f0efec;
        border-radius: 4px; padding: 0 6px; margin-right: 6px; }
.past .lbl { fill: var(--muted); }
td.st { color: var(--ink2); }
td.st svg { vertical-align: -2px; margin-right: 4px; }
.prd.past { color: var(--muted); }
.prd.week { font-weight: 600; background: #fbdde9; border-radius: 4px; padding: 0 4px; margin: 0 -4px; }
.cities .gap { width: 14px; border: none; }
"""
