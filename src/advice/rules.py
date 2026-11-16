"""예보 수치에서 생활 조언을 뽑아냄 — 규칙 기반이라 근거 수치가 없으면 말하지 않음.

문구 기준(톤·개수·반복 금지)은 docs/writing-style.md 와 하나로 맞춤.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
from dataclasses import dataclass
from typing import TypeVar

from src.advice.phrases import (
    CHILLY_LINES,
    COLD_LINES,
    HEAT_LINES,
    RAIN_LINES,
    SPECIAL,
    SPREAD_LINES,
    WARM_LINES,
)

T = TypeVar("T")

# «날짜 + 지역» 으로 고름 — 같은 날 같은 곳은 같은 답, 날이나 지역이 바뀌면 다른 문장.
# 무작위면 같은 질문에 답이 바뀌고, 지역을 빼면 한 채널에서 여럿이 물을 때 같은 말이 되풀이됨.
def _pick(options: tuple[T, ...], date: dt.date, region: str = "", shift: int = 0) -> T | str:
    if not options:
        return ""
    # blake2b 로 섞음 — hash() 는 PYTHONHASHSEED 로 재기동마다 바뀌고,
    # 글자 코드 합은 한 유니코드 블록에 몰린 한글 지명끼리 겹침
    salt = (int.from_bytes(hashlib.blake2b(region.encode(), digest_size=4).digest(), "big")
            if region else 0)
    return options[(date.toordinal() + salt + shift) % len(options)]


# 권하는 말은 두 길이의 최소공배수 일마다 한 칸 더 밀어 모든 짝이 돌아오게 함 — 같은 날짜로만 돌리면 같은 줄끼리 묶임
def _pick_pair(lines: tuple[tuple[str, ...], tuple[str, ...]], date: dt.date,
               region: str = "") -> tuple[str, str] | None:
    facts, acts = lines
    if not facts or not acts:
        return None
    shift = date.toordinal() // math.lcm(len(facts), len(acts))
    return _pick(facts, date, region), _pick(acts, date, region, shift)


def first_three(labels: list[str], sep: str = ", ") -> str:
    """셋까지만 잇고 나머지는 «외 N일» 로 밝힘 — 잘린 날을 맑은 날로 읽지 않게."""
    shown = sep.join(labels[:3])
    rest = len(labels) - 3
    return f"{shown} 외 {rest}일" if rest > 0 else shown


def _days_text(ds) -> str:
    return first_three([f"*{d.date:%m/%d}*" for d in ds])


# 문턱 사이의 평범한 날은 침묵 — 문턱을 낮추면 매일 걸려 조언이 아니게 됨.
# «평년 대비 대용물» 은 9월에 맞춘 절대 기온이라 철이 바뀌면 어긋남(제대로는 기상청 평년값과의 편차).
BIG_SPREAD = 12.0      # 일교차 (도) — 평년 대비의 대용물
COLD_MORNING = 5.0     # 아침 최저 (도) — 방한 조언 기준. 기상청 한파특보 기준이 아니라 자체 기준
HEAT_WAVE = 33.0       # 폭염일 기준 (도) — 기상청 기후통계 정의라 고정. 폭염특보는 체감온도 기준이라 다름
WARM_DAY = 30.0        # 낮 기온 (도) — 평년 대비의 대용물
RAIN_LIKELY = 60       # 강수확률 (%)
CHILLY_MORNING = 10.0  # 아침 최저 (도) — 평년 대비의 대용물


RAIN = "비"


@dataclass
class Advice:
    emoji: str
    fact: str             # 사실. 관심사 조언은 한 줄 전부가 여기 듦
    act: str = ""         # 권하는 말
    # 아래는 build_advice 의 기온·비 조언만 채움 — 주간 본문이 한 문단으로 엮을 때 씀
    kind: str = ""        # TEMP_STEMS 의 키 또는 RAIN
    dates: tuple[dt.date, ...] = ()
    value: float | None = None

    @property
    def text(self) -> str:
        return f"{self.fact} {self.act}".strip()


def _spread(day) -> float | None:
    lows = [v for v in (day.tmin_lo, day.tmin_hi) if v is not None]
    highs = [v for v in (day.tmax_lo, day.tmax_hi) if v is not None]
    if not lows or not highs:
        return None
    return sum(highs) / len(highs) - sum(lows) / len(lows)


def rainy_days(days) -> list:
    """강수확률이 높거나 하늘상태에 비·눈이 든 날."""
    return [d for d in days if (d.pop or 0) >= RAIN_LIKELY
            or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))]


@dataclass(frozen=True)
class _Temp:
    """기온 조언 한 갈래."""
    emoji: str
    kind: str                                      # TEMP_STEMS 의 키
    lines: tuple[tuple[str, ...], tuple[str, ...]]
    labeled: bool = True                           # 사실 앞에 날짜를 붙임


def _dated(temp: _Temp, date: dt.date, value: float, region: str) -> Advice | None:
    picked = _pick_pair(temp.lines, date, region)
    if not picked:
        return None
    fact, act = picked
    fact = fact.format(gap=value, t=value)
    if temp.labeled:
        fact = f"*{date:%m/%d}* {fact}"
    return Advice(temp.emoji, fact, act, temp.kind, (date,), value)


def build_advice(days, narratives=None, region: str = "") -> list[Advice]:
    usable = [d for d in days if d.tmin_lo is not None and d.tmax_hi is not None]
    if not usable:
        return []

    out: list[Advice | None] = []
    spreads = [(d, s) for d in usable if (s := _spread(d)) is not None]
    coldest = min(usable, key=lambda d: d.tmin_lo)
    hottest = max(usable, key=lambda d: d.tmax_hi)
    rainy = rainy_days(usable)

    if spreads:
        worst, gap = max(spreads, key=lambda pair: pair[1])
        if gap >= BIG_SPREAD:
            out.append(_dated(_Temp(":thermometer:", "일교차", SPREAD_LINES), worst.date, gap, region))

    if coldest.tmin_lo <= COLD_MORNING:
        out.append(_dated(_Temp(":cold_face:", "추위", COLD_LINES), coldest.date, coldest.tmin_lo, region))
    elif hottest.tmax_hi >= HEAT_WAVE:
        out.append(_dated(_Temp(":sun_with_face:", "더위", HEAT_LINES), hottest.date, hottest.tmax_hi, region))
    elif hottest.tmax_hi >= WARM_DAY:
        out.append(_dated(_Temp(":sunny:", "더움", WARM_LINES, labeled=False),
                          hottest.date, hottest.tmax_hi, region))
    elif coldest.tmin_lo <= CHILLY_MORNING:
        out.append(_dated(_Temp(":fallen_leaf:", "쌀쌀", CHILLY_LINES, labeled=False),
                          coldest.date, coldest.tmin_lo, region))

    if rainy and (picked := _pick_pair(RAIN_LINES, rainy[0].date, region)):
        fact, act = picked
        out.append(Advice(":umbrella_with_rain_drops:", fact.format(days=_days_text(rainy)), act,
                          RAIN, tuple(d.date for d in rainy)))

    # 예보관 특이사항(태풍·한파 등)이 앞섬 — 뒤에 붙이면 [:3] 에서 잘려 위험한 쪽이 사라짐
    ref = usable[0].date
    hits: list[tuple[int, Advice]] = []
    for line in narratives or []:
        for keyword, (emoji, lines) in SPECIAL.items():
            if keyword in line and not any(k == keyword for k, _ in hits):
                fact, act = _pick_pair(lines, ref, region)
                hits.append((keyword, Advice(emoji, fact, act)))
    hits.sort(key=lambda pair: SPECIAL_ORDER.index(pair[0]))
    special = [advice for _, advice in hits]

    return (special + [tip for tip in out if tip])[:3]      # 너무 많으면 잔소리가 됨


# 안전에 가까운 것이 앞. SPECIAL 에 키를 더하면 여기에도 — 빠지면 ValueError
SPECIAL_ORDER = ("태풍", "한파", "폭염", "너울", "풍랑", "황사", "안개", "건조")

