"""날씨 답에 덧붙이는 첫눈 한 줄 — 11월~1월에, 그 지역 지점에 말할 것이 있을 때만."""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence

from src.common.text import bold, short_date, short_day_label
from src.season import snow
from src.season.snow import SnowError, Status, in_note_season
from src.season.snow_text import gap_text, observed_line, sources, waiting_text
from src.season.stations import STATIONS, Station

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


def _snow_note(stations: tuple[Station, ...], shown: Sequence[tuple[dt.date, str | None]],
               today: dt.date) -> list[str]:
    """shown 은 답에 보인 (날짜, 하늘상태). 최근 관측이 있거나, 아직인 곳에 눈 예보가 있을 때만 붙임."""
    if not stations or not in_note_season(today) or not (status := _status_quietly(today)):
        return []
    snowy = [d for d, sky in shown if d >= today and "눈" in (sky or "")]
    recent = [(st, d) for st in stations
              if (d := status.first.get(st.name)) and (today - d).days < RECENT_DAYS]
    waiting = [st for st in stations if st.name not in status.first]
    if not recent and not (snowy and waiting):
        return []

    # 전국은 지점마다 적지 않고 첫눈 현황 답과 같은 요약 — 스무 곳이 넘음
    if len(stations) == len(STATIONS):
        brief = observed_line(status, bold)
    else:
        bits = [f"*{st.name}* {short_date(d)} 첫눈 관측" + (f" ({gap})" if (gap := gap_text(st, d)) else "")
                for st, d in recent]
        if snowy:
            bits += [f"*{st.name}* 아직" + (f" ({wait})" if (wait := waiting_text(st, status)) else "")
                     for st in waiting]
        brief = " · ".join(bits)
    if snowy and waiting:
        brief += f" — {' · '.join(short_day_label(d) for d in snowy)} 눈 예보"
    return ["", f":snowflake: *첫눈* — {brief}", f"_{sources()}_"]
