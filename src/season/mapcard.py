"""지도 카드의 틀과 표지 — 머리·요약 줄·꼬리말, 범례, 빈 원·점선 고리·그림. 단풍·첫눈·벚꽃·더위·태풍 지도가 함께 씀.

투영을 모름 — 좌표는 그린 자리의 픽셀로 받음.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from src.common.text import day_label
from src.season.basemap import emoji
from src.season.weeks import week_end_of

# 회색 빈 원은 «없음·아직» 의 중립 — 색이 아니라 모양으로 가름
GRAY = "#898781"
NONE = '<span class="none">–</span>'


def glyph_size(r: float) -> float:
    """반지름 r 빈 원과 같아 보이는 그림 크기 — 그림은 여백이 있어 같은 크기면 빈 원보다 작아 보임."""
    return 2 * r + 7


def hollow(x: float, y: float, r: float = 6.5) -> str:
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fcfcfb" stroke="{GRAY}" stroke-width="2"/>'


def ring(x: float, y: float, r: float) -> str:
    """이번 주 예상의 점선 고리."""
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="none" stroke="#0b0b0b" stroke-width="1.4" '
            f'stroke-dasharray="2.6 2.2"/>')


def glyph(name: str, x: float, y: float, r: float = 6.5, opacity: float = 1.0) -> str:
    return emoji(name, x, y, glyph_size(r), opacity)


def icon(inner: str, w: float, h: float | None = None, view: float | None = None) -> str:
    """범례 그림 상자 — (0, 0) 이 가운데. view 는 보기 상자 폭(기본 w) — 크면 그만큼 줄여 그림."""
    h = h or w
    vw = view or w
    vh = vw * h / w
    return f'<svg width="{w:g}" height="{h:g}" viewBox="{-vw / 2:g} {-vh / 2:g} {vw:g} {vh:g}">{inner}</svg>'


def legend(items: Iterable[tuple[str, str]], note: str = "") -> str:
    """범례 한 줄 — (그림, 글) 들과 끝의 흐린 덧말."""
    spans = "".join(f"<span>{pic}{text}</span>" for pic, text in items)
    tail = f'<span class="muted">{note}</span>' if note else ""
    return f'<div class="legend">{spans}{tail}</div>'


def lead_rows(rows: Iterable[tuple[str, str]]) -> str:
    """요약 줄 — 내용이 빈 줄은 뺌."""
    return "".join(f'<div><span class="k">{k}</span><span>{v}</span></div>' for k, v in rows if v)


def body(left: str, right: str) -> str:
    """지도(왼쪽)와 표(오른쪽)."""
    return f'<div class="body"><div class="map">{left}</div>{right}</div>'


@dataclass(frozen=True)
class Card:
    """지도 카드 한 장 — 제목과 그 주 기간, 요약 줄(이름, 내용), 본문, 꼬리말."""
    title: str
    week_start: dt.date
    rows: Sequence[tuple[str, str]]
    main: str
    foot: str

    def html(self, css: str) -> str:
        period = f"{day_label(self.week_start)} ~ {day_label(week_end_of(self.week_start))}"
        return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{css}</style></head>'
                f'<body><div id="card"><div class="head"><h1>{self.title}</h1><span class="period">{period}'
                f'</span></div><div class="lead">{lead_rows(self.rows)}</div>{self.main}'
                f'<div class="foot">{self.foot}</div></div></body></html>')
