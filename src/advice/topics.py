"""관심사(옷차림 · 우산 · 야외 · 빨래 · 세차)를 물었을 때의 조언 — 질문에서 관심사를 알아보고 수치로 답함."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from src.advice.phrases import (
    UMBRELLA_NO_LINES,
    UMBRELLA_YES_LINES,
    WEAR_COLD_LINES,
    WEAR_MILD_LINES,
    WEAR_RAIN_LINES,
    WEAR_SPREAD_LINES,
    WEAR_WARM_LINES,
)
from src.advice.rules import (
    BIG_SPREAD,
    COLD_MORNING,
    HEAT_WAVE,
    WARM_DAY,
    Advice,
    _days_text,
    _pick,
    _spread,
    rainy_days,
)

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


@dataclass(frozen=True)
class _Days:
    """조언의 근거 — 기온이 다 있는 날들과 거기서 뽑은 날."""
    usable: list
    rainy: list
    clear: list
    low: float            # 가장 추운 아침
    high: float           # 가장 더운 낮
    ref: dt.date          # 문장을 고르는 날짜
    region: str


def _umbrella(w: _Days) -> list[Advice]:
    if w.rainy:
        return [Advice(":umbrella_with_rain_drops:",
                       _pick(UMBRELLA_YES_LINES, w.ref, w.region).format(days=_days_text(w.rainy)))]
    return [Advice(":sunny:", _pick(UMBRELLA_NO_LINES, w.ref, w.region))]


def _wear(w: _Days) -> list[Advice]:
    lo, hi = w.low, w.high
    spread = max((v for d in w.usable if (v := _spread(d)) is not None), default=0)
    if spread >= BIG_SPREAD:
        out = [Advice(":thermometer:", _pick(WEAR_SPREAD_LINES, w.ref, w.region).format(lo=lo, hi=hi, gap=spread))]
    elif lo <= COLD_MORNING:
        out = [Advice(":cold_face:", _pick(WEAR_COLD_LINES, w.ref, w.region).format(t=lo))]
    elif hi >= WARM_DAY:
        out = [Advice(":sunny:", _pick(WEAR_WARM_LINES, w.ref, w.region).format(t=hi))]
    else:
        out = [Advice(":relieved:", _pick(WEAR_MILD_LINES, w.ref, w.region).format(lo=lo, hi=hi))]
    if w.rainy:
        out.append(Advice(":umbrella_with_rain_drops:",
                          _pick(WEAR_RAIN_LINES, w.ref, w.region).format(days=_days_text(w.rainy))))
    return out


def _outdoor(w: _Days) -> list[Advice]:
    if w.rainy:
        fine = [d for d in w.usable if d not in w.rainy]
        tip = f"{_days_text(w.rainy)}에 비 소식이 있습니다."
        if fine:
            tip += f" {_days_text(fine)}이 나아 보여요."
        return [Advice(":umbrella_with_rain_drops:", tip)]
    if w.high >= HEAT_WAVE:
        return [Advice(":sun_with_face:",
                       f"낮 최고 {w.high:.0f}도까지 올라 한낮 활동은 무리입니다. "
                       "이른 아침이나 해질 무렵이 낫겠어요.")]
    best = w.clear or w.usable
    return [Advice(":sunny:",
                   f"{_days_text(best)}이 좋겠습니다. "
                   f"아침 {w.low:.0f}도로 쌀쌀하니 겉옷 하나 챙기세요.")]


def _chores(w: _Days, topic: str) -> list[Advice]:
    if w.rainy:
        fine = [d for d in w.usable if d not in w.rainy]
        tip = f"{_days_text(w.rainy)}에 비 소식이 있어 피하시는 게 좋겠습니다."
        if fine:
            tip += f" {_days_text(fine)}을 노려보세요."
        return [Advice(":umbrella_with_rain_drops:", tip)]
    if w.clear:
        what = "잘 마르겠습니다" if topic == "빨래" else "괜찮겠습니다"
        return [Advice(":sunny:", f"{_days_text(w.clear)}이 맑아 {what}.")]
    return [Advice(":cloud:", "당분간 흐리지만 비 소식은 없습니다.")]


def topic_advice(topic: str, days, region: str = "") -> list[Advice]:
    usable = [d for d in days if d.tmin_lo is not None and d.tmax_hi is not None]
    if not usable:
        return []
    w = _Days(
        usable=usable,
        rainy=rainy_days(usable),
        clear=[d for d in usable if "맑" in (d.sky or "") and (d.pop or 0) < 30],
        low=min(d.tmin_lo for d in usable),
        high=max(d.tmax_hi for d in usable),
        # 가장 이른 날로 고름 — 같은 기간이면 몇 번 물어도 같은 문장
        ref=min(d.date for d in usable),
        region=region,
    )
    if topic == "우산":
        return _umbrella(w)
    if topic == "옷차림":
        return _wear(w)
    if topic == "야외":
        return _outdoor(w)
    if topic in ("빨래", "세차"):
        return _chores(w, topic)
    return []
