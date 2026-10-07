"""단풍을 물었을 때의 답 — 전국 현황, 산 하나, 산 아래 마을 날씨."""
from __future__ import annotations

import datetime as dt
import logging

from src.advice.rules import detect_topic
from src.common.text import bold, short_date
from src.kma.regions import extract_region
from src.mention.dong_reply import _dong_reply
from src.mention.foliage_note import _snapshot_quietly
from src.mention.parse import (
    DONG_MAX_DAYS,
    FLOWER_RE,
    FOLIAGE_RE,
    FORWARD_DAYS,
    TRIP_SPANS,
    WEATHER_ASK_RE,
    _period,
)
from src.mention.texts import NO_EMOJI
from src.season import foliage
from src.season.foliage import (
    CRITERIA_TEXT,
    KINDS,
    NOT_STARTED_TEXT,
    SEASON_TEXT,
    STAGES,
    FoliageError,
    Snapshot,
    in_season,
    next_season,
)
from src.season.foliage import KMA_PAGE as KMA_FOLIAGE_PAGE
from src.season.foliage_text import gap_text, observed_line, sources, week_line
from src.season.mountains import (
    MOUNTAINS,
    Mountain,
    find_mountain,
    unknown_mountain,
)
from src.season.sources import OUTLOOK_SOURCE

log = logging.getLogger("weather-mention")


FLOWER_URL = "https://www.weather.go.kr/w/forecast/life/seasonal-observation/spring-flower.do"


def _stage_line(snap: Snapshot, kind: str, name: str, today: dt.date) -> str:
    label = STAGES[KINDS.index(kind) + 1]
    day, observed = snap.when(kind, name)
    if observed and day is None:
        return f"• {label} — *관측* (촬영일은 아직 올라오지 않았습니다)"
    if day is None:
        return f"• {label} — 예상 없음 ({OUTLOOK_SOURCE} 예상에 없는 산입니다)"
    if observed:
        gap = gap_text(snap.predicted(kind, name), day, show_date=True)
        return f"• {label} — *{short_date(day)} 관측*" + (f" · {gap}" if gap else "")
    if day < today:
        return f"• {label} — {short_date(day)} 예상이었지만 아직 관측되지 않았습니다"
    return f"• {label} — {short_date(day)} 예상"


def _mountain_text(snap: Snapshot, m: Mountain, today: dt.date) -> str:
    if snap.status.in_service:
        head = f"*{m.name}* 단풍 — 지금 *{STAGES[snap.stage(m.name)]}* (기상청 관측)"
    else:
        head = f"*{m.name}* 단풍 — {NOT_STARTED_TEXT}"
    return "\n".join([
        head,
        *(_stage_line(snap, kind, m.name, today) for kind in KINDS),
        f"_{sources(snap)} · {CRITERIA_TEXT}_",
    ])


def _overview_text(snap: Snapshot, today: dt.date, unknown: str | None) -> str:
    end = today + dt.timedelta(days=FORWARD_DAYS - 1)
    lines = []
    if unknown:
        lines += [
            f"'{unknown}' 은 기상청이 단풍을 관측하는 {len(MOUNTAINS)}곳에 없습니다. {NO_EMOJI}",
            "_관측하는 곳: " + " · ".join(m.name for m in MOUNTAINS) + "_",
            "",
        ]
    lines += [
        f"*단풍 현황* ({short_date(today)} 기준)",
        f"• 관측 — {observed_line(snap, bold)}",
        f"• 앞으로 7일 — {week_line(snap, today, end, bold, muted=lambda s: s)}",
        f"_{sources(snap)} · 산 이름을 함께 불러 주시면 그 산만 자세히 알려드려요_",
    ]
    return "\n".join(lines)


def _theme(query: str, now: dt.datetime) -> tuple[str, Snapshot | None] | None:
    """단풍·꽃 질문이면 (답, 지도로 그릴 현황), 아니면 None. 지도가 필요 없으면 현황은 None."""
    today = now.date()
    asks_weather = bool(WEATHER_ASK_RE.search(query))
    if FLOWER_RE.search(query) and not FOLIAGE_RE.search(query):
        if asks_weather:
            return None                   # 꽃구경 가는 날의 날씨 — 날씨로 답함
        return (f"꽃 개화 소식은 다루지 않습니다. {NO_EMOJI}\n"
                f"기상청 봄꽃 개화 현황(3월 초~5월 하순)에서 보실 수 있어요 — {FLOWER_URL}"), None
    if not FOLIAGE_RE.search(query):
        return None

    mountain = find_mountain(query)
    # 산이 아니라 지역의 날씨를 물었으면 날씨 질문임 ("단풍 구경 가는데 강원도 날씨 어때")
    if mountain is None and asks_weather and extract_region(query)[0] is not None:
        return None

    if not in_season(today):
        start, _ = next_season(today)
        # 기간은 늘 월요일에 시작함 (9월 둘째 월요일)
        when = (f"올해는 {short_date(start)}(월)부터입니다" if start.year == today.year
                else f"다음은 {start.year}년 {short_date(start)}(월)부터입니다")
        return f"단풍 소식은 *{SEASON_TEXT}* 에만 전해드립니다. {NO_EMOJI}\n_{when}._", None

    try:
        snap = foliage.fetch_snapshot(today)
    except FoliageError as exc:
        log.warning("단풍 현황 실패: %s", exc)
        return ("기상청 단풍 현황을 가져오지 못했습니다. 잠시 뒤 다시 불러 주세요.\n"
                f"기상청에서 직접 보실 수 있어요 — {KMA_FOLIAGE_PAGE}"), None

    if mountain is None:
        return _overview_text(snap, today, unknown_mountain(query)), snap

    text = _mountain_text(snap, mountain, today)
    start, days, title = _period(query, now)
    trip = title in TRIP_SPANS
    if trip or asks_weather or detect_topic(query):
        if not trip:
            start, days = today, DONG_MAX_DAYS - 1
        text += f"\n\n{_mountain_weather(mountain, start, days)}"
    return text, None


def _mountain_weather(m: Mountain, start: dt.date, days: int) -> str:
    """산 아래 마을 동네예보. 산 위가 아니라는 것을 밝혀 둠."""
    weather = _dong_reply(m.zone, f"{m.name} 아래 {m.zone_name}", days, start, quiet=True)
    return (f"{weather}\n_산 아래 마을 예보입니다. 산 위는 이보다 춥고 바람이 셉니다._" if weather
            else f"_산 아래 마을 날씨는 가져오지 못했습니다 (동네예보는 오늘부터 {DONG_MAX_DAYS}일까지)._")


def _mountain_reply(m: Mountain, start: dt.date, days: int, title: str, today: dt.date) -> str:
    """단풍 말 없이 산 이름으로 물은 답 ("설악산", "주말 지리산 등산").

    산 아래 마을 예보가 먼저임 — 날씨를 물은 것. 단풍철이면 그 산의 단풍을 덧붙임.
    기간을 콕 집지 않았으면 단풍 갈래의 산 날씨와 같은 기간을 보여줌.
    """
    if title.startswith("앞으로"):
        start, days = today, DONG_MAX_DAYS - 1
    text = _mountain_weather(m, start, days)
    if in_season(today) and (snap := _snapshot_quietly(today)):
        text += f"\n\n{_mountain_text(snap, m, today)}"
    return text
