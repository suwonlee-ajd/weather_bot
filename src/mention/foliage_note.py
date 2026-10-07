"""날씨 답에 덧붙이는 단풍 한 줄 — 단풍철에, 그 지역 산에 말할 것이 있을 때만."""
from __future__ import annotations

import datetime as dt
import logging

from src.common.text import bold, short_date
from src.season import foliage
from src.season.foliage import (
    KINDS,
    STAGES,
    FoliageError,
    Snapshot,
    in_season,
)
from src.season.foliage_map import (
    observed_line,
    sources,
    week_changes,
    week_line,
)
from src.season.mountains import (
    MOUNTAINS,
    Mountain,
)

log = logging.getLogger("weather-mention")


def _snapshot_quietly(today: dt.date) -> Snapshot | None:
    """날씨 답에 덧붙일 단풍 현황. 못 받으면 None — 덤 때문에 날씨 답까지 막지 않음."""
    try:
        return foliage.fetch_snapshot(today)
    except FoliageError as exc:            # 점검·형식 변경 — 예상된 실패라 한 줄로
        log.warning("단풍 현황 실패 — 날씨만 답합니다: %s", exc)
    except Exception:
        log.warning("단풍 현황 실패 — 날씨만 답합니다", exc_info=True)
    return None


def _foliage_brief(snap: Snapshot, mountains: tuple[Mountain, ...], start: dt.date, end: dt.date) -> str:
    """물든 산과 그 기간에 예상된 변화. 둘 다 없으면 빈 문자열.

    전국은 단풍 현황 답과 같은 요약을 씀 — 산마다 적으면 스무 곳이 넘음.
    """
    if len(mountains) == len(MOUNTAINS):
        parts = []
        if any(snap.stage(m.name) for m in MOUNTAINS):
            parts.append(observed_line(snap, bold))
        if any(week_changes(snap, start, end).values()):
            parts.append(week_line(snap, start, end, bold, muted=lambda s: s))
        return " / ".join(parts)

    changes = week_changes(snap, start, end)
    bits = []
    for m in mountains:
        stage = snap.stage(m.name)
        steps = []
        if stage:
            day, _ = snap.when(KINDS[stage - 1], m.name)
            steps.append(f"{STAGES[stage]} {short_date(day)}" if day else STAGES[stage])
        ahead = [f"{STAGES[i]} {short_date(d)}" for i, kind in enumerate(KINDS, start=1)
                 for name, d in changes[kind] if name == m.name]
        if ahead:
            steps.append(" · ".join(ahead) + " (예상)")
        if steps:
            bits.append(f"*{m.name}* " + " → ".join(steps))
    return " · ".join(bits)


def _foliage_note(mountains: tuple[Mountain, ...], start: dt.date, end: dt.date,
                  today: dt.date) -> list[str]:
    """지역 날씨 끝에 붙이는 단풍 한 줄. 단풍철에, 그 지역에 말할 것이 있을 때만.

    단풍을 못 받아 와도 날씨 답은 그대로 나감 — 날씨를 물은 사람에게 주는 덤.
    """
    if not mountains or not in_season(today) or not (snap := _snapshot_quietly(today)):
        return []
    # 이미 지난 날의 예상은 꺼내지 않음 — 그날 물들었으면 관측으로 나옴
    brief = _foliage_brief(snap, mountains, max(start, today), end)
    if not brief:
        return []
    return ["", f":maple_leaf: *단풍* — {brief}", f"_{sources(snap)}_"]
