"""단풍 현황 문장 — 지도(HTML)와 슬랙 답이 함께 씀."""
from __future__ import annotations

import datetime as dt

from src.common.text import html_bold, html_muted, short_date
from src.season.foliage.data import KINDS, NOT_STARTED_TEXT, STAGES, Snapshot
from src.season.foliage.mountains import MOUNTAINS
from src.season.sources import OUTLOOK_SOURCE
from src.season.summary import observed_summary

# 절정 사진 뒤 이 날수까지를 «절정 2주 안» 으로 묶음 — 보여 주는 구간일 뿐 «졌다» 는 뜻이 아님.
# 기상청은 낙엽을 관측하지 않음(계절관측의 낙엽 칸도 비어 있음) — 지난 날수만 사실로 적음
FRESH_PEAK_DAYS = 14
FRESH_SHOWN = 4                       # 이번 주 줄에 이름을 적는 산 — 넘으면 «외 N곳»


def peak_age(snap: Snapshot, name: str, day: dt.date) -> int | None:
    """절정 사진 뒤 지난 날수. 절정 전이거나 촬영일이 없거나 day 뒤의 관측이면 None."""
    peaked = snap.status.peak.get(name)
    if snap.stage(name) < 2 or peaked is None or peaked > day:
        return None
    return (day - peaked).days


def past_peak(snap: Snapshot, day: dt.date) -> tuple[list[tuple[str, dt.date]], int]:
    """(절정 2주 안인 산과 절정일 — 최근 순, 절정 2주 넘은 산의 수)."""
    fresh, old = [], 0
    for m in MOUNTAINS:
        age = peak_age(snap, m.name, day)
        if age is None:
            continue
        if age <= FRESH_PEAK_DAYS:
            fresh.append((m.name, snap.status.peak[m.name]))
        else:
            old += 1
    return sorted(fresh, key=lambda x: x[1], reverse=True), old


def gap_text(predicted: dt.date | None, observed: dt.date, *, show_date: bool = False) -> str:
    if not predicted or predicted == observed:
        return ""
    gap = (predicted - observed).days
    shown = f"({short_date(predicted)})" if show_date else ""
    return f"예상{shown}보다 {abs(gap)}일 {'빠름' if gap > 0 else '늦음'}"


def sources(snap: Snapshot, *, detail: bool = False) -> str:
    """출처 한 줄. detail 은 지도 꼬리말용(관측 시점·예상 곳 수까지)."""
    status = "현황 기상청 날씨누리" + (" 유명산 단풍현황" if detail else "")
    if detail and snap.status.updated:
        status += f" ({short_date(snap.status.updated)} 관측까지)"
    o = snap.outlook
    if o is None:
        return f"{status} · 예상 없음" if detail else status
    bits = [f"{short_date(o.published)} 발표"] if o.published else []
    if detail:
        bits.append(f"{len(o.first)}곳")
    return f"{status} · 예상 {OUTLOOK_SOURCE}" + (f"({', '.join(bits)})" if bits else "")


def week_changes(snap: Snapshot, start: dt.date, end: dt.date) -> dict[str, list[tuple[str, dt.date]]]:
    """그 주의 예상 변화 {kind: [(산, 날짜)]}. 이미 든 단계는 뺌."""
    out: dict[str, list[tuple[str, dt.date]]] = {}
    for stage, kind in enumerate(KINDS, start=1):
        out[kind] = sorted(
            ((m.name, d) for m in MOUNTAINS
             if snap.stage(m.name) < stage and (d := snap.predicted(kind, m.name)) and start <= d <= end),
            key=lambda x: x[1],
        )
    return out


def observed_line(snap: Snapshot, bold=html_bold, *, day: dt.date | None = None) -> str:
    """관측 한 줄 — 물든 곳이 적으면 이름·날짜, 많으면 개수·최근 변화. bold 로 HTML·슬랙을 가름.

    day 를 주면 절정 2주 넘은 산의 수를 개수에 덧붙임 — «절정 21곳(2주 넘음 19곳)».
    """
    s = snap.status
    if not s.in_service:
        return NOT_STARTED_TEXT
    counts = [sum(1 for m in MOUNTAINS if s.stage(m.name) == k) for k in (2, 1, 0)]
    if not counts[0] and not counts[1]:
        return f"아직 물든 곳이 없습니다 — {len(MOUNTAINS)}곳 모두 단풍 전"

    events = []   # (날짜 또는 None, 산, 단계)
    for m in MOUNTAINS:
        if stage := s.stage(m.name):
            events.append((getattr(s, KINDS[stage - 1]).get(m.name), m.name, stage))

    def event_text(e) -> str:
        day, name, stage = e
        text = f"{bold(name)} {STAGES[stage]}"
        if day is None:
            return text
        gap = gap_text(snap.predicted(KINDS[stage - 1], name), day)
        return f"{text} {short_date(day)}" + (f" ({gap})" if gap else "")

    old = past_peak(snap, day)[1] if day else 0
    tally = " · ".join(f"{STAGES[k]} {n}곳" + (f"(2주 넘음 {old}곳)" if k == 2 and old else "")
                       for k, n in zip((2, 1, 0), counts) if n)
    return observed_summary([(e[0], event_text(e)) for e in events],
                            f"나머지 {counts[2]}곳은 단풍 전" if counts[2] else "", tally)


def week_line(snap: Snapshot, start: dt.date, end: dt.date, bold=html_bold, muted=html_muted, *,
              day: dt.date | None = None) -> str:
    """start~end 의 예상 변화. 없으면 day(기본 start) 기준 절정 뒤 지난 날수."""
    if snap.outlook is None:
        return (f"{OUTLOOK_SOURCE} 예상을 읽지 못해 현황만 표시합니다" if snap.outlook_error
                else "올해 예상이 아직 나오지 않았습니다")
    bits = [f"{STAGES[stage]} " + " · ".join(f"{bold(n)} {short_date(d)}" for n, d in changes)
            for stage, changes in enumerate(week_changes(snap, start, end).values(), start=1) if changes]
    if bits:
        return " / ".join(bits) + " " + muted("(예상)")
    return _after_peak(snap, day or start, bold)


def _after_peak(snap: Snapshot, day: dt.date, bold) -> str:
    """남은 예상 변화가 없을 때 — 절정이 얼마나 지났는지(사실)로 채움. 늦가을 내내 빈말이 되지 않게."""
    fresh, old = past_peak(snap, day)
    if fresh:
        names = " · ".join(f"{bold(n)} {short_date(d)}" for n, d in fresh[:FRESH_SHOWN])
        more = f" 외 {len(fresh) - FRESH_SHOWN}곳" if len(fresh) > FRESH_SHOWN else ""
        return f"예상된 변화 없음 · 절정 2주 안 {names}{more}"
    if old and old == len(MOUNTAINS):
        return "예상된 변화 없음 · 모든 산이 절정 뒤 2주를 넘겼습니다"
    return "예상된 변화가 없습니다"
