"""예보 수치에서 생활 조언을 뽑아냄.

문구를 손볼 때는 `docs/writing-style.md` 의 기준을 함께 봄 —
톤(담백한 존댓말), 조언 개수(두세 개까지), 근거 없으면 침묵, 같은 말 반복 금지가
거기 적혀 있음. 사람·모델이 쓰는 답변과 이 파일이 내는 문구가 따로 놀면 봇이
둘로 보임 — 기준은 하나.

일반 예보와 다르게 "그래서 뭘 하면 되는지"를 한두 줄 덧붙이는 것이 목적.
규칙 기반이라 비용이 0 이고, 근거가 되는 수치가 없으면 그냥 말하지 않음 —
지어낸 조언은 안 하느니만 못함.

임계값은 아래 상수 정의에 한 벌만 둠 — 숫자를 여기 다시 적으면 한쪽만
고쳐져 어긋남. 무엇을 왜 그 값으로 잡았는지는 그 자리 주석에 있음.
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

# 같은 조건이라도 문장을 «날짜 + 지역» 으로 골라 돌려 씀. 문구가 하나뿐이면
# 날씨가 매일 비슷해 날짜와 숫자만 바뀐 같은 말이 매번 나감. 이 기준이라 —
#   * 같은 날 같은 곳을 두 번 물어도 같은 답이 나오고(일관성),
#   * 날이 바뀌면 표현이 바뀌고,
#   * 같은 날이라도 서울과 부산은 다른 문장을 받음.
# 지역이 빠지면 한 채널에서 여러 사람이 각자 다른 지역을 물었을 때
# 봇이 같은 말을 되풀이하는 것처럼 읽힘(실제로 그랬음).
# 무작위로 고르면 같은 질문에 다른 답이 나와 봇이 미덥지 않아 보임.
def _pick(options: tuple[T, ...], date: dt.date, region: str = "") -> T | str:
    if not options:               # 표를 손보다 문구를 다 지운 경우
        return ""                 # 조용히 넘어감 — 이 모듈은 말 없는 쪽이 기본
    # 지역은 이름 그대로가 아니라 해시로 섞음. hash() 는 쓰지 않음 — 프로세스마다
    # 값이 달라(PYTHONHASHSEED) 같은 날 재기동하면 문구가 바뀜.
    # 글자 코드의 합도 안 됨 — 한글 지명은 유니코드 한 블록에 몰려 있어
    # 합이 비슷하게 나옴(서울·부산·대구가 표 길이 3에서 겹쳤음).
    # 지역을 안 넘긴 호출부는 날짜만 봄 (소금 0).
    salt = (int.from_bytes(hashlib.blake2b(region.encode(), digest_size=4).digest(), "big")
            if region else 0)
    return options[(date.toordinal() + salt) % len(options)]


def first_three(labels: list[str], sep: str = ", ") -> str:
    """날짜 표기 몇 개를 이음. 셋까지만 적음 — 그 이상은 읽히지 않음.

    다만 잘렸다는 사실은 밝힘. 닷새 비가 오는데 사흘만 적으면 나머지 이틀을 맑은 날로 읽음.
    """
    shown = sep.join(labels[:3])
    rest = len(labels) - 3
    return f"{shown} 외 {rest}일" if rest > 0 else shown


def _days_text(ds) -> str:
    """날짜 몇 개를 슬랙 볼드로 묶어 적음."""
    return first_three([f"*{d.date:%m/%d}*" for d in ds])


# 두 값 사이의 «아무 말도 안 하는» 구간은 메우지 않음 — 짚을 것이 없으면 침묵하는
# 것이 이 모듈의 규칙. 아침 11도에 일교차 11도 같은 초가을의 평범한 날이 거기 듦.
# 빈칸을 채우려고 문턱을 낮추면 매일 걸리던 옛날로 돌아감.
BIG_SPREAD = 12.0      # 일교차 (도) — 평년 대비의 대용물
COLD_MORNING = 5.0     # 아침 최저 (도) — 한파 대비, 기상청 기준이므로 고정
HEAT_WAVE = 33.0       # 폭염주의보 기준 (도) — 기상청 기준이므로 고정
WARM_DAY = 30.0        # 낮 기온 (도) — 평년 대비의 대용물
RAIN_LIKELY = 60       # 강수확률 (%)
CHILLY_MORNING = 10.0  # 아침 최저 (도) — 평년 대비의 대용물


# 사용자가 묻는 관심사. 같은 예보라도 무엇을 물었느냐에 따라 짚어줄 것이 다름.
TOPICS: dict[str, tuple[str, ...]] = {
    # '입' 은 자주 오는 활용형만 넣어 둠 — 입고/입어/입나/입지/입을… 어미를 일일이
    # 적을 수는 없음. "어떻게 입고 가야 할까" 가 안 걸려서 늘렸음.
    "옷차림": ("뭐 입", "옷", "입고", "입어", "입을", "입나", "입지", "입어야", "입야",
             "복장", "차림", "겉옷", "코트", "패딩", "반팔", "우비"),
    "우산": ("우산", "비 와", "비와", "비 올", "비올", "장화", "방수"),
    "야외": ("등산", "산행", "캠핑", "나들이", "소풍", "피크닉", "運動", "운동", "러닝",
             "자전거", "골프", "낚시", "바다", "해변", "야외", "산책", "축제"),
    "빨래": ("빨래", "세탁", "건조"),
    "세차": ("세차",),
}


def detect_topic(text: str) -> str | None:
    """질문에서 관심사를 하나 고름. 없으면 None (기본 조언만 나감)."""
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
    # 아래는 build_advice 의 기온·비 조언에만 채움. 주간 본문이 여러 조언을 한 문단으로
    # 엮을 때 씀(writer.theme_paragraph).
    kind: str = ""        # TEMP_STEMS 의 키 또는 RAIN
    dates: tuple[dt.date, ...] = ()
    value: float | None = None

    @property
    def text(self) -> str:
        """한 줄로 보일 때의 문장 (멘션은 이것만 봄)."""
        return f"{self.fact} {self.act}".strip()


def _spread(day) -> float | None:
    lows = [v for v in (day.tmin_lo, day.tmin_hi) if v is not None]
    highs = [v for v in (day.tmax_lo, day.tmax_hi) if v is not None]
    if not lows or not highs:
        return None
    return sum(highs) / len(highs) - sum(lows) / len(lows)


def topic_advice(topic: str, days, region: str = "") -> list[Advice]:
    """관심사에 맞춘 조언. 근거가 되는 수치가 없으면 빈 목록."""
    usable = [d for d in days if d.tmin_lo is not None and d.tmax_hi is not None]
    if not usable:
        return []

    rainy = [d for d in usable if (d.pop or 0) >= RAIN_LIKELY
             or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))]
    clear = [d for d in usable if "맑" in (d.sky or "") and (d.pop or 0) < 30]
    coldest = min(usable, key=lambda d: d.tmin_lo)
    hottest = max(usable, key=lambda d: d.tmax_hi)
    # 문구는 목록 순서가 아니라 가장 이른 날로 고름 — 같은 기간을 물으면
    # 몇 번을 물어도 같은 문장이 돌아옴.
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
    """하루에 묶이는 기온 조언. 멘션 한 줄은 «*10/07* 사실. 권하는 말.» 모양.

    더움·쌀쌀의 멘션 문구는 원래 날짜 없이 나감(labeled=False). 주간 본문은 dates 를 씀.
    표를 비웠으면 None — 짝을 풀다 죽지 않고 그 조언만 말하지 않음(_pick 과 같은 규칙).
    """
    picked = _pick(lines, date, region)
    if not picked:
        return None
    fact, act = picked
    fact = fact.format(gap=value, t=value)
    if labeled:
        fact = f"*{date:%m/%d}* {fact}"
    return Advice(emoji, fact, act, kind, (date,), value)


def build_advice(days, narratives=None, region: str = "") -> list[Advice]:
    """수치에서 짚이는 것만 고름. 없으면 빈 목록."""
    usable = [d for d in days if d.tmin_lo is not None and d.tmax_hi is not None]
    if not usable:
        return []

    out: list[Advice | None] = []
    spreads = [(d, s) for d in usable if (s := _spread(d)) is not None]
    coldest = min(usable, key=lambda d: d.tmin_lo)
    hottest = max(usable, key=lambda d: d.tmax_hi)
    rainy = [d for d in usable if (d.pop or 0) >= RAIN_LIKELY
             or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))]

    # 1) 일교차 — 가장 흔하고, 건강 조언으로 이어지는 신호
    if spreads:
        worst, gap = max(spreads, key=lambda pair: pair[1])
        if gap >= BIG_SPREAD:
            out.append(_dated(":thermometer:", "일교차", SPREAD_LINES, worst.date, gap, region))

    # 2) 추위 / 더위 — 둘 다 해당하면 더 극단적인 쪽만
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

    # 3) 비
    if rainy and (picked := _pick(RAIN_LINES, rainy[0].date, region)):
        fact, act = picked
        out.append(Advice(":umbrella_with_rain_drops:", fact.format(days=_days_text(rainy)), act,
                          RAIN, tuple(d.date for d in rainy)))

    # 4) 예보관이 짚은 특이사항 — 수치로는 안 잡히는 것 (풍랑·건조·태풍 등)
    #
    # 이것들이 앞섬. 태풍·한파는 «낮에 덥습니다» 보다 먼저 알아야 할 일인데,
    # 뒤에 붙이면 out[:3] 에서 잘려 정작 위험한 쪽이 사라짐.
    ref = usable[0].date          # usable 은 위 가드로 비어 있지 않음
    hits: list[tuple[int, Advice]] = []
    for line in narratives or []:
        for keyword, (emoji, lines) in SPECIAL.items():
            if keyword in line and not any(k == keyword for k, _ in hits):
                hits.append((keyword, Advice(emoji, _pick(lines, ref, region))))
    # 급한 것부터 고름 — 같은 서술에 여러 특보가 섞여 옴(«건조·황사·태풍»).
    hits.sort(key=lambda pair: SPECIAL_ORDER.index(pair[0]))
    special = [advice for _, advice in hits]

    return (special + [tip for tip in out if tip])[:3]      # 너무 많으면 잔소리가 됨


# 급한 순서. 사람 목숨·안전에 가까운 것이 앞. SPECIAL 에 키를 더하면
# 여기에도 넣음 — 빠지면 ValueError 로 바로 드러남(조용히 뒤로 밀리지 않게).
SPECIAL_ORDER = ("태풍", "한파", "폭염", "너울", "풍랑", "황사", "안개", "건조")

