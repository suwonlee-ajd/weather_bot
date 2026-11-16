"""태풍 문장 — 주간 게시의 «현재»·«예상» 줄과 출처를 예상 경로 지도의 머리 줄·꼬리말이 같은 말로 씀."""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Sequence

from src.common.text import bold, short_date
from src.season.typhoon.data import Typhoon

SOURCE = "기상청 태풍정보"

Style = Callable[[str], str]


def now_line(storm: Typhoon, strong: Style = bold, reach: bool = False, plain: Style = str) -> str:
    """«*제2호 태풍 우딥(WUTIP)* · 괌 남동쪽 … · 중심기압 990hPa (2/20(수) 15시 기준)».

    reach 면 현재 위치의 바람 반경까지, plain 은 경로표에서 온 글자에 씀(지도는 html.escape).
    """
    weakened = f" {storm.weakened}" if storm.weakened else ""
    winds = (("강풍반경", storm.now.gale), ("폭풍반경", storm.now.storm)) if reach else ()
    radii = "".join(f" · {name} {r.text}" for name, r in winds if r)
    return f"{strong(plain(storm.title))}{plain(weakened)} · {plain(storm.now.summary)}{radii} ({storm.now.when} 기준)"


def ahead_line(storm: Typhoon, end: dt.date, named: bool = False) -> str:
    """end 안의 마지막 예상 위치. 태풍이 여럿이면(named) 이름을 앞에. 없으면 빈 문자열."""
    ahead = [p for p in storm.forecast if p.at.date() <= end]
    if not ahead:
        return ""
    return (f"{storm.name} " if named else "") + f"{ahead[-1].when} {ahead[-1].place}"


def issued_text(storms: Sequence[Typhoon]) -> str:
    """«기상청 태풍정보(11/16 16시 발표)» — 가장 늦은 발표시각, 모르면 이름만."""
    issued = max((s.issued for s in storms if s.issued), default=None)
    return SOURCE + (f"({short_date(issued)} {issued.hour}시 발표)" if issued else "")


def sources(storms: Sequence[Typhoon], quoted: Iterable[str]) -> str:
    """실린 것의 출처만 — 태풍정보(받았으면)와 인용한 예보관 서술 이름(겹치지 않게)."""
    return " · ".join([*([issued_text(storms)] if storms else []), *dict.fromkeys(quoted)])
