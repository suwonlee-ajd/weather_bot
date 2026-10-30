"""단풍 현황 문장 — 지도(HTML)와 슬랙 답이 함께 씀."""
from __future__ import annotations

import datetime as dt

from src.common.text import html_bold, html_muted, short_date
from src.season.foliage.data import KINDS, NOT_STARTED_TEXT, STAGES, Snapshot
from src.season.foliage.mountains import MOUNTAINS
from src.season.sources import OUTLOOK_SOURCE
from src.season.summary import observed_summary


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


def observed_line(snap: Snapshot, bold=html_bold) -> str:
    """관측 한 줄 — 물든 곳이 적으면 이름·날짜, 많으면 개수·최근 변화. bold 로 HTML·슬랙을 가름."""
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

    tally = " · ".join(f"{STAGES[k]} {n}곳" for k, n in zip((2, 1, 0), counts) if n)
    return observed_summary([(e[0], event_text(e)) for e in events],
                            f"나머지 {counts[2]}곳은 단풍 전" if counts[2] else "", tally)


def week_line(snap: Snapshot, start: dt.date, end: dt.date, bold=html_bold, muted=html_muted) -> str:
    if snap.outlook is None:
        return (f"{OUTLOOK_SOURCE} 예상을 읽지 못해 현황만 표시합니다" if snap.outlook_error
                else "올해 예상이 아직 나오지 않았습니다")
    bits = [f"{STAGES[stage]} " + " · ".join(f"{bold(n)} {short_date(d)}" for n, d in changes)
            for stage, changes in enumerate(week_changes(snap, start, end).values(), start=1) if changes]
    return (" / ".join(bits) + " " + muted("(예상)")) if bits else "예상된 변화가 없습니다"
