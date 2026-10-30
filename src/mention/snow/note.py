"""날씨 답에 덧붙이는 첫눈 한 줄 — 11월~1월에, 그 지역 지점에 말할 것이 있을 때만."""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence

from src.common.text import bold
from src.kma.regions import NATIONWIDE, Region
from src.season.snow import data as snow
from src.season.snow.data import SnowError, Status, in_note_season
from src.season.snow.stations import STATIONS, stations_in_region, stations_in_zone
from src.season.snow.text import (
    SOURCES,
    is_snowy,
    observed_line,
    snow_forecast,
    station_text,
)

log = logging.getLogger("weather-mention")

RECENT_DAYS = 7    # 관측 소식을 붙여 두는 날수 — 그 뒤로는 답마다 되풀이하면 잔소리임


def _status_quietly(today: dt.date) -> Status | None:
    try:
        return snow.fetch_status(today)
    except SnowError as exc:               # 점검·형식 변경 — 예상된 실패라 traceback 없이
        log.warning("첫눈 관측 실패 — 날씨만 답합니다: %s", exc)
    except Exception:
        log.warning("첫눈 관측 실패 — 날씨만 답합니다", exc_info=True)
    return None


def _snow_note(where: Region | str, shown: Sequence[tuple[dt.date, str | None]], today: dt.date) -> list[str]:
    """where 는 광역 구역 또는 동네예보 코드, shown 은 답에 보인 (날짜, 하늘상태).
    그 안 지점에 최근 관측이 있거나, 아직인 곳에 눈 예보가 있을 때만 붙임."""
    nationwide = where is NATIONWIDE
    if isinstance(where, str):
        stations = stations_in_zone(where)
    else:
        stations = STATIONS if nationwide else stations_in_region(where.key)
    if not stations or not in_note_season(today) or not (status := _status_quietly(today)):
        return []
    snowy = [d for d, sky in shown if d >= today and is_snowy(sky)]
    recent = [st for st in stations
              if (d := status.first.get(st.name)) and (today - d).days < RECENT_DAYS]
    waiting = [st for st in stations if st.name not in status.first]
    if not recent and not (snowy and waiting):
        return []

    if nationwide:                         # 지점마다 적지 않고 첫눈 현황 답과 같은 요약 — 스무 곳이 넘음
        brief = observed_line(status, bold)
    else:
        brief = " · ".join(station_text(st, status, bold) for st in recent + (waiting if snowy else []))
    if snowy and waiting:
        brief += f" — {snow_forecast(snowy)}"
    return ["", f":snowflake: *첫눈* — {brief}", f"_{SOURCES}_"]
