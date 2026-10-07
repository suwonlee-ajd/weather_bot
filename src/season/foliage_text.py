"""단풍 현황을 문장으로 — 관측 한 줄 · 그 주 변화 · 출처. 지도(HTML)와 슬랙 답이 함께 씀."""
from __future__ import annotations

import datetime as dt

from src.common.text import short_date
from src.season.foliage import KINDS, NOT_STARTED_TEXT, STAGES, Snapshot
from src.season.mountains import MOUNTAINS
from src.season.sources import OUTLOOK_SOURCE


def gap_text(predicted: dt.date | None, observed: dt.date, *, show_date: bool = False) -> str:
    """관측이 예상과 얼마나 어긋났는지. 같거나 예상이 없으면 빈 문자열."""
    if not predicted or predicted == observed:
        return ""
    gap = (predicted - observed).days
    shown = f"({short_date(predicted)})" if show_date else ""
    return f"예상{shown}보다 {abs(gap)}일 {'빠름' if gap > 0 else '늦음'}"


def sources(snap: Snapshot, *, detail: bool = False) -> str:
    """출처 한 줄. detail 이면 지도 꼬리말처럼 관측 시점과 예상 곳 수까지."""
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
    """그 주에 예상된 변화 {'first': [(산, 날짜)], 'peak': [...]}. 이미 지난 단계는 뺌."""
    out: dict[str, list[tuple[str, dt.date]]] = {}
    for stage, kind in enumerate(KINDS, start=1):
        out[kind] = sorted(
            ((m.name, d) for m in MOUNTAINS
             if snap.stage(m.name) < stage and (d := snap.predicted(kind, m.name)) and start <= d <= end),
            key=lambda x: x[1],
        )
    return out


def _html_bold(text: str) -> str:
    return f"<b>{text}</b>"


def observed_line(snap: Snapshot, bold=_html_bold) -> str:
    """관측 한 줄. 물든 곳이 적으면 이름과 날짜를, 많아지면 개수와 최근 변화를 씀.

    지도(HTML)와 멘션 답(슬랙)이 같은 문장을 씀. 굵게 쓰는 방법만 bold 로 갈아 끼움.
    """
    s = snap.status
    if not s.in_service:
        return NOT_STARTED_TEXT
    counts = [sum(1 for m in MOUNTAINS if s.stage(m.name) == k) for k in (2, 1, 0)]
    if not counts[0] and not counts[1]:
        return f"아직 물든 곳이 없습니다 — {len(MOUNTAINS)}곳 모두 단풍 전"

    # 물든 산마다 지금 단계 하나. 촬영일이 아직 안 올라온 산도 빠뜨리지 않음.
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

    def latest(e):
        return e[0] or dt.date.min       # 날짜 없는 산은 '최근' 에서 뒤로

    if len(events) <= 2:
        head = " · ".join(event_text(e) for e in sorted(events, key=latest))
        return f"{head}, 나머지 {counts[2]}곳은 단풍 전" if counts[2] else head
    tally = " · ".join(f"{STAGES[k]} {n}곳" for k, n in zip((2, 1, 0), counts) if n)
    return f"{tally} — 최근 " + " · ".join(event_text(e) for e in sorted(events, key=latest, reverse=True)[:2])


def week_line(snap: Snapshot, start: dt.date, end: dt.date, bold=_html_bold,
              muted=lambda s: f'<span class="muted">{s}</span>') -> str:
    """그 주에 예상된 변화 한 줄."""
    if snap.outlook is None:
        return (f"{OUTLOOK_SOURCE} 예상을 읽지 못해 현황만 표시합니다" if snap.outlook_error
                else "올해 예상이 아직 나오지 않았습니다")
    bits = [f"{STAGES[stage]} " + " · ".join(f"{bold(n)} {short_date(d)}" for n, d in changes)
            for stage, changes in enumerate(week_changes(snap, start, end).values(), start=1) if changes]
    return (" / ".join(bits) + " " + muted("(예상)")) if bits else "예상된 변화가 없습니다"
