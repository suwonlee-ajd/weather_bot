"""주간 전망 카드 PNG — 원본 게시물 첫 첨부(AI 검색 결과 캡처)처럼 리드·출처 칩·구간 불릿만 그림.

더 넣으면 캡처처럼 보이지 않음. 리눅스에는 한글 폰트(fonts-noto-cjk)가 필요함.
"""
from __future__ import annotations

import html

from src.common.browser import CARD_WIDTH, capture
from src.weekly.forecast import Section, Source, WeekForecast

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #ffffff; }
#card {
  width: %(width)spx;
  padding: 22px 24px 20px;
  background: #ffffff;
  font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', 'Noto Sans CJK KR',
               'Malgun Gothic', 'Helvetica Neue', sans-serif;
  color: #1f2328;
  line-height: 1.7;
  font-size: 14.5px;
  -webkit-font-smoothing: antialiased;
}
.lead { margin-bottom: 26px; }
.lead mark { background: #fdf3c4; padding: 2px 1px; color: inherit; }
h2 { font-size: 19px; font-weight: 700; letter-spacing: -.01em; margin-bottom: 14px; }
ul { list-style: none; }
li { position: relative; padding-left: 17px; margin-bottom: 16px; }
li:last-child { margin-bottom: 0; }
li::before {
  content: ''; position: absolute; left: 3px; top: 11px;
  width: 5px; height: 5px; border-radius: 50%%; background: #3c4149;
}
li b { font-weight: 700; }
.chip {
  display: inline-flex; align-items: center; gap: 5px;
  margin-left: 6px; padding: 1px 9px 2px;
  background: #f2f3f5; border-radius: 999px;
  font-size: 11.5px; color: #4b5563; vertical-align: 1px; white-space: nowrap;
}
.chip::before { content: ''; width: 7px; height: 7px; border-radius: 50%%; background: #2f6feb; }
.chip .more { color: #8b919b; }
""" % {"width": CARD_WIDTH}


def _chip(sources: list[Source]) -> str:
    if not sources:
        return ""
    more = f'<span class="more">+{len(sources) - 1}</span>' if len(sources) > 1 else ""
    return f'<span class="chip">{html.escape(sources[0].title)}{more}</span>'


def _bullets(sections: list[Section]) -> str:
    rows = []
    for s in sections:
        label = html.escape(s.label)
        if s.period:
            label += f" ({html.escape(s.period)})"
        rows.append(f"<li><b>{label}:</b> {html.escape(s.text)}{_chip(s.sources)}</li>")
    return "".join(rows)


def _fallback_lead(week: WeekForecast) -> str:
    mornings = [v for d in week.days for v in (d.tmin_lo, d.tmin_hi) if v is not None]
    noons = [v for d in week.days for v in (d.tmax_lo, d.tmax_hi) if v is not None]
    if not (mornings and noons):
        return f"이번 주 {week.area} 예보입니다."
    return (
        f"이번 주 {week.area} 아침 기온은 {min(mornings):.0f}~{max(mornings):.0f}℃, "
        f"낮 기온은 {min(noons):.0f}~{max(noons):.0f}℃ 분포가 예상됩니다."
    )


def build_html(week: WeekForecast) -> str:
    lead = week.lead or _fallback_lead(week)
    body = [f'<p class="lead"><mark>{html.escape(lead)}</mark>{_chip(week.sources)}</p>']
    if week.sections:
        body.append("<h2>기온 전망 및 날씨 흐름</h2>")
        body.append(f"<ul>{_bullets(week.sections)}</ul>")

    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        f"<style>{CSS}</style></head><body>"
        f"<div id='card'>{''.join(body)}</div></body></html>"
    )


def render_png(week: WeekForecast, *, scale: int = 2) -> bytes:
    return capture(build_html(week), scale=scale)
