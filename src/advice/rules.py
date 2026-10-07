"""예보 수치에서 생활 조언을 뽑아냄 — 규칙 기반이라 근거 수치가 없으면 말하지 않음.

문구 기준(톤·개수·반복 금지)은 docs/writing-style.md 와 하나로 맞춤.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import TypeVar

from src.advice.phrases import (
    CHILLY_LINES,
    COLD_LINES,
    HEAT_LINES,
    RAIN_LINES,
    SPECIAL,
    SPREAD_LINES,
    UMBRELLA_NO_LINES,
    UMBRELLA_YES_LINES,
    WARM_LINES,
    WEAR_COLD_LINES,
    WEAR_MILD_LINES,
    WEAR_RAIN_LINES,
    WEAR_SPREAD_LINES,
    WEAR_WARM_LINES,
)

T = TypeVar("T")

# «날짜 + 지역» 으로 고름 — 같은 날 같은 곳은 같은 답, 날이나 지역이 바뀌면 다른 문장.
# 무작위면 같은 질문에 답이 바뀌고, 지역을 빼면 한 채널에서 여럿이 물을 때 같은 말이 되풀이됨.
def _pick(options: tuple[T, ...], date: dt.date, region: str = "") -> T | str:
    if not options:
        return ""
    # blake2b 로 섞음 — hash() 는 PYTHONHASHSEED 로 재기동마다 바뀌고,
    # 글자 코드 합은 한 유니코드 블록에 몰린 한글 지명끼리 겹침
    salt = (int.from_bytes(hashlib.blake2b(region.encode(), digest_size=4).digest(), "big")
            if region else 0)
    return options[(date.toordinal() + salt) % len(options)]


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
HEAT_WAVE = 33.0       # 폭염주의보 기준 (도) — 기상청 기준이므로 고정
WARM_DAY = 30.0        # 낮 기온 (도) — 평년 대비의 대용물
RAIN_LIKELY = 60       # 강수확률 (%)
CHILLY_MORNING = 10.0  # 아침 최저 (도) — 평년 대비의 대용물


TOPICS: dict[str, tuple[str, ...]] = {
    # '입' 은 자주 오는 활용형만 — 어미를 일일이 적을 수는 없음
    "옷차림": ("뭐 입", "옷", "입고", "입어", "입을", "입나", "입지", "입어야", "입야",
             "복장", "차림", "겉옷", "코트", "패딩", "반팔", "우비"),
    "우산": ("우산", "비 와", "비와", "비 올", "비올", "장화", "방수"),
    "야외": ("등산", "산행", "캠핑", "나들이", "소풍", "피크닉", "운동", "러닝",
             "자전거", "골프", "낚시", "바다", "해변", "야외", "산책", "축제"),
    "빨래": ("빨래", "세탁", "건조"),
    "세차": ("세차",),
}


def detect_topic(text: str) -> str | None:
    flat = (text or "").replace(" ", "")
    for topic, words in TOPICS.items():
        if any(w.replace(" ", "") in flat for w in words):
            return topic
    return None


RAIN = "비"


@dataclass
class Advice:
    emoji: str
    fact: str             # 사실. 특이사항·관심사 조언은 한 줄 전부가 여기 듦
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


def topic_advice(topic: str, days, region: str = "") -> list[Advice]:
    usable = [d for d in days if d.tmin_lo is not None and d.tmax_hi is not None]
    if not usable:
        return []

    rainy = [d for d in usable if (d.pop or 0) >= RAIN_LIKELY
             or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))]
    clear = [d for d in usable if "맑" in (d.sky or "") and (d.pop or 0) < 30]
    coldest = min(usable, key=lambda d: d.tmin_lo)
    hottest = max(usable, key=lambda d: d.tmax_hi)
    # 가장 이른 날로 고름 — 같은 기간이면 몇 번 물어도 같은 문장
    ref = min(d.date for d in usable)

    if topic == "우산":
        if rainy:
            return [Advice(":umbrella_with_rain_drops:",
                           _pick(UMBRELLA_YES_LINES, ref, region).format(days=_days_text(rainy)))]
        return [Advice(":sunny:", _pick(UMBRELLA_NO_LINES, ref, region))]

    if topic == "옷차림":
        out = []
        spread = max((v for d in usable if (v := _spread(d)) is not None), default=0)
        if spread >= BIG_SPREAD:
            out.append(Advice(":thermometer:", _pick(WEAR_SPREAD_LINES, ref, region).format(
                lo=coldest.tmin_lo, hi=hottest.tmax_hi, gap=spread)))
        elif coldest.tmin_lo <= COLD_MORNING:
            out.append(Advice(":cold_face:",
                              _pick(WEAR_COLD_LINES, ref, region).format(t=coldest.tmin_lo)))
        elif hottest.tmax_hi >= WARM_DAY:
            out.append(Advice(":sunny:",
                              _pick(WEAR_WARM_LINES, ref, region).format(t=hottest.tmax_hi)))
        else:
            out.append(Advice(":relieved:", _pick(WEAR_MILD_LINES, ref, region).format(
                lo=coldest.tmin_lo, hi=hottest.tmax_hi)))
        if rainy:
            out.append(Advice(":umbrella_with_rain_drops:",
                              _pick(WEAR_RAIN_LINES, ref, region).format(days=_days_text(rainy))))
        return out

    if topic == "야외":
        if rainy:
            fine = [d for d in usable if d not in rainy]
            tip = f"{_days_text(rainy)}에 비 소식이 있습니다."
            if fine:
                tip += f" {_days_text(fine)}이 나아 보여요."
            return [Advice(":umbrella_with_rain_drops:", tip)]
        if hottest.tmax_hi >= HEAT_WAVE:
            return [Advice(":sun_with_face:",
                           f"낮 최고 {hottest.tmax_hi:.0f}도까지 올라 한낮 활동은 무리입니다. "
                           "이른 아침이나 해질 무렵이 낫겠어요.")]
        best = clear or usable
        return [Advice(":sunny:",
                       f"{_days_text(best)}이 좋겠습니다. "
                       f"아침 {coldest.tmin_lo:.0f}도로 쌀쌀하니 겉옷 하나 챙기세요.")]

    if topic in ("빨래", "세차"):
        if rainy:
            fine = [d for d in usable if d not in rainy]
            tip = f"{_days_text(rainy)}에 비 소식이 있어 피하시는 게 좋겠습니다."
            if fine:
                tip += f" {_days_text(fine)}을 노려보세요."
            return [Advice(":umbrella_with_rain_drops:", tip)]
        if clear:
            what = "잘 마르겠습니다" if topic == "빨래" else "괜찮겠습니다"
            return [Advice(":sunny:", f"{_days_text(clear)}이 맑아 {what}.")]
        return [Advice(":cloud:", "당분간 흐리지만 비 소식은 없습니다.")]

    return []


def _dated(emoji: str, kind: str, lines, date: dt.date, value: float, region: str,
           *, labeled: bool = True) -> Advice | None:
    picked = _pick(lines, date, region)
    if not picked:
        return None
    fact, act = picked
    fact = fact.format(gap=value, t=value)
    if labeled:
        fact = f"*{date:%m/%d}* {fact}"
    return Advice(emoji, fact, act, kind, (date,), value)


def build_advice(days, narratives=None, region: str = "") -> list[Advice]:
    usable = [d for d in days if d.tmin_lo is not None and d.tmax_hi is not None]
    if not usable:
        return []

    out: list[Advice | None] = []
    spreads = [(d, s) for d in usable if (s := _spread(d)) is not None]
    coldest = min(usable, key=lambda d: d.tmin_lo)
    hottest = max(usable, key=lambda d: d.tmax_hi)
    rainy = [d for d in usable if (d.pop or 0) >= RAIN_LIKELY
             or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))]

    if spreads:
        worst, gap = max(spreads, key=lambda pair: pair[1])
        if gap >= BIG_SPREAD:
            out.append(_dated(":thermometer:", "일교차", SPREAD_LINES, worst.date, gap, region))

    if coldest.tmin_lo <= COLD_MORNING:
        out.append(_dated(":cold_face:", "추위", COLD_LINES, coldest.date, coldest.tmin_lo, region))
    elif hottest.tmax_hi >= HEAT_WAVE:
        out.append(_dated(":sun_with_face:", "더위", HEAT_LINES, hottest.date, hottest.tmax_hi, region))
    elif hottest.tmax_hi >= WARM_DAY:
        out.append(_dated(":sunny:", "더움", WARM_LINES, hottest.date, hottest.tmax_hi, region,
                          labeled=False))
    elif coldest.tmin_lo <= CHILLY_MORNING:
        out.append(_dated(":fallen_leaf:", "쌀쌀", CHILLY_LINES, coldest.date, coldest.tmin_lo, region,
                          labeled=False))

    if rainy and (picked := _pick(RAIN_LINES, rainy[0].date, region)):
        fact, act = picked
        out.append(Advice(":umbrella_with_rain_drops:", fact.format(days=_days_text(rainy)), act,
                          RAIN, tuple(d.date for d in rainy)))

    # 예보관 특이사항(태풍·한파 등)이 앞섬 — 뒤에 붙이면 [:3] 에서 잘려 위험한 쪽이 사라짐
    ref = usable[0].date
    hits: list[tuple[int, Advice]] = []
    for line in narratives or []:
        for keyword, (emoji, lines) in SPECIAL.items():
            if keyword in line and not any(k == keyword for k, _ in hits):
                hits.append((keyword, Advice(emoji, _pick(lines, ref, region))))
    hits.sort(key=lambda pair: SPECIAL_ORDER.index(pair[0]))
    special = [advice for _, advice in hits]

    return (special + [tip for tip in out if tip])[:3]      # 너무 많으면 잔소리가 됨


# 안전에 가까운 것이 앞. SPECIAL 에 키를 더하면 여기에도 — 빠지면 ValueError
SPECIAL_ORDER = ("태풍", "한파", "폭염", "너울", "풍랑", "황사", "안개", "건조")

