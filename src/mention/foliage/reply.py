"""단풍을 물었을 때의 답 — 전국 현황, 산 하나, 산 아래 마을 날씨."""
from __future__ import annotations

import datetime as dt
import logging

from src.advice.rules import detect_topic
from src.common.text import bold, short_date
from src.kma.regions import extract_region
from src.mention.foliage.note import _snapshot_quietly
from src.mention.parse import (
    DONG_MAX_DAYS,
    FLOWER_RE,
    FOLIAGE_RE,
    FORWARD_DAYS,
    RECENT_RE,
    TRIP_SPANS,
    WEATHER_ASK_RE,
    _period,
)
from src.mention.reply import Reply, with_map
from src.mention.texts import NO_EMOJI
from src.mention.weather.dong import _dong_reply
from src.season.foliage import data as foliage
from src.season.foliage import map as foliage_map
from src.season.foliage.data import (
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
from src.season.foliage.data import KMA_PAGE as KMA_FOLIAGE_PAGE
from src.season.foliage.mountains import (
    MOUNTAINS,
    Mountain,
    find_mountain,
    unknown_mountain,
)
from src.season.foliage.text import gap_text, observed_line, sources, week_line
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


def foliage_theme(query: str, now: dt.datetime) -> Reply | None:
    """단풍·꽃 질문이면 답(전국 현황은 지도와 함께), 아니면 None."""
    today = now.date()
    asks_weather = bool(WEATHER_ASK_RE.search(query))
    if FLOWER_RE.search(query) and not FOLIAGE_RE.search(query):
        if asks_weather:
            return None                   # 꽃구경 날의 날씨 — 날씨로 답함
        return Reply(f"꽃 개화 소식은 다루지 않습니다. {NO_EMOJI}\n"
                     f"기상청 봄꽃 개화 현황(3월 초~5월 하순)에서 보실 수 있어요 — {FLOWER_URL}")
    if not FOLIAGE_RE.search(query):
        return None

    mountain = find_mountain(query)
    # 산 없이 지역 날씨를 물으면 날씨 질문 ("단풍 구경 가는데 강원도 날씨 어때")
    if mountain is None and asks_weather and extract_region(query)[0] is not None:
        return None

    if not in_season(today):
        start, _ = next_season(today)
        # 단풍철은 늘 월요일(9월 둘째 월요일)에 시작
        when = (f"올해는 {short_date(start)}(월)부터입니다" if start.year == today.year
                else f"다음은 {start.year}년 {short_date(start)}(월)부터입니다")
        return Reply(f"단풍 소식은 *{SEASON_TEXT}* 에만 전해드립니다. {NO_EMOJI}\n_{when}._")

    try:
        snap = foliage.fetch_snapshot(today)
    except FoliageError as exc:
        log.warning("단풍 현황 실패: %s", exc)
        return Reply("기상청 단풍 현황을 가져오지 못했습니다. 잠시 뒤 다시 불러 주세요.\n"
                     f"기상청에서 직접 보실 수 있어요 — {KMA_FOLIAGE_PAGE}")

    if mountain is None:
        return with_map(_overview_text(snap, today, unknown_mountain(query)), foliage_map.INFO,
                        ("foliage-map", today, snap.signature()),
                        lambda: foliage_map.render_png(snap, today, span_label="앞으로 7일"))

    text = _mountain_text(snap, mountain, today)
    # '요즘' 은 '지금' 처럼 단풍 상태를 묻는 말 — 이번 주로 읽어 날씨를 붙이지 않음
    start, days, title = _period(RECENT_RE.sub(" ", query), now)
    trip = title in TRIP_SPANS
    if trip or asks_weather or detect_topic(query):
        if not trip:
            start, days = today, DONG_MAX_DAYS - 1
        text += f"\n\n{_mountain_weather(mountain, start, days)}"
    return Reply(text)


def _mountain_weather(m: Mountain, start: dt.date, days: int) -> str:
    weather = _dong_reply(m.zone, f"{m.name} 아래 {m.zone_name}", days, start, quiet=True)
    return (f"{weather}\n_산 아래 마을 예보입니다. 산 위는 이보다 춥고 바람이 셉니다._" if weather
            else f"_산 아래 마을 날씨는 가져오지 못했습니다 (동네예보는 오늘부터 {DONG_MAX_DAYS}일까지)._")


def _mountain_reply(m: Mountain, start: dt.date, days: int, title: str, today: dt.date) -> str:
    """단풍 말 없이 산 이름으로 물은 답 ("설악산", "주말 지리산 등산") — 날씨가 먼저, 단풍은 덧붙임."""
    if title.startswith("앞으로"):
        start, days = today, DONG_MAX_DAYS - 1
    text = _mountain_weather(m, start, days)
    if in_season(today) and (snap := _snapshot_quietly(today)):
        text += f"\n\n{_mountain_text(snap, m, today)}"
    return text
