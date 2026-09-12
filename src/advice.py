"""예보 수치에서 생활 조언을 뽑아낸다.

문구를 손볼 때는 `.claude/skills/weather-reply/SKILL.md` 의 기준을 함께 본다 —
톤(담백한 존댓말), 조언 개수(두세 개까지), 근거 없으면 침묵, 같은 말 반복 금지가
거기 적혀 있다. 사람이 쓰는 답변과 이 파일이 내는 문구가 따로 놀면 봇이 둘로
보인다. 스킬은 Claude Code 가 읽고, 이 파일은 런타임이 읽을 뿐 기준은 하나다.

일반 예보와 다르게 "그래서 뭘 하면 되는지"를 한두 줄 덧붙이는 것이 목적이다.
규칙 기반이라 비용이 0 이고, 근거가 되는 수치가 없으면 그냥 말하지 않는다 —
지어낸 조언은 안 하느니만 못하다.

임계값은 아래 상수 정의에 한 벌만 둔다 — 숫자를 여기 다시 적으면 한쪽만
고쳐져 어긋난다. 무엇을 왜 그 값으로 잡았는지는 그 자리 주석에 있다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# 같은 조건이라도 문장을 돌려 쓴다. 날씨는 매일 비슷해서 문구가 하나뿐이면
# 날짜와 숫자만 바뀐 같은 말이 매번 나간다. 고르는 기준은 날짜라서 —
#   * 같은 날 두 번 물어도 같은 답이 나오고(일관성),
#   * 날이 바뀌면 표현이 바뀐다.
# 무작위로 고르면 같은 질문에 다른 답이 나와 봇이 미덥지 않아 보인다.
def _pick(options: tuple[str, ...], date: dt.date) -> str:
    if not options:               # 표를 손보다 문구를 다 지운 경우
        return ""                 # 조용히 넘어간다 — 이 모듈은 말 없는 쪽이 기본이다
    return options[date.toordinal() % len(options)]


def _days_text(ds) -> str:
    """날짜 몇 개를 슬랙 볼드로 묶어 적는다.

    셋까지만 적는다 — 그 이상은 읽히지 않는다. 다만 잘렸다는 사실은 밝힌다.
    닷새 비가 오는데 사흘만 적으면 나머지 이틀을 맑은 날로 읽는다.
    """
    shown = ", ".join(f"*{d.date:%m/%d}*" for d in ds[:3])
    rest = len(ds) - 3
    return f"{shown} 외 {rest}일" if rest > 0 else shown


SPREAD_LINES = (
    "일교차가 {gap:.0f}도까지 벌어집니다. 겉옷 하나 걸치시고 환절기 감기 조심하세요.",
    "아침저녁으로 {gap:.0f}도 차이가 납니다. 낮 기준으로만 입으면 아침에 춥습니다.",
    "낮과 아침의 기온차가 {gap:.0f}도입니다. 얇은 겉옷을 챙기시면 하루가 편합니다.",
    "{gap:.0f}도 일교차라 체감이 크게 달라집니다. 벗기 쉬운 옷으로 맞춰 입으세요.",
)
HEAT_LINES = (
    "낮 최고 {t:.0f}도입니다. 한낮 바깥일은 피하시고 물 자주 드세요. 온열질환 주의 구간입니다.",
    "낮에 {t:.0f}도까지 오릅니다. 가장 더운 한두 시는 실내에서 보내시는 편이 좋습니다.",
    "{t:.0f}도 더위입니다. 그늘과 물을 가까이 두시고 무리한 일정은 미루세요.",
)
WARM_LINES = (
    "낮에는 {t:.0f}도까지 올라 덥습니다. 얇게 입고 수분 챙기세요.",
    "낮 기온이 {t:.0f}도로 제법 높습니다. 통풍 잘 되는 옷이 좋겠습니다.",
    "한낮은 {t:.0f}도라 움직이면 덥습니다. 물 한 병 챙기시면 든든합니다.",
)
COLD_LINES = (
    "아침 최저 {t:.0f}도까지 내려갑니다. 따뜻하게 껴입으시고 실내 온도도 살펴 주세요.",
    "아침 기온이 {t:.0f}도입니다. 장갑과 목도리까지 챙기시는 편이 좋습니다.",
    "{t:.0f}도까지 떨어지는 아침입니다. 얇게 여러 겹 껴입으면 덜 춥습니다.",
)
CHILLY_LINES = (
    "아침 최저 {t:.0f}도로 쌀쌀합니다. 출근길 겉옷 하나 걸치시면 딱 좋겠습니다.",
    "아침 공기가 {t:.0f}도로 서늘합니다. 얇은 겉옷 하나면 충분하겠습니다.",
    "{t:.0f}도 아침이라 초반에 손이 시립니다. 가벼운 겉옷을 권합니다.",
)
RAIN_LINES = (
    "{days}에 비 소식이 있어요. 나가시기 전에 우산 꼭 챙기세요.",
    "{days}에 비가 옵니다. 우산 없이 나서면 곤란하겠습니다.",
    "{days}에 비가 예보됐습니다. 우산과 함께 신발도 한 번 보세요.",
    "{days}에 비 예보가 있습니다. 접이식 우산 하나면 충분하겠습니다.",
)
FOG_LINES = (
    "안개가 끼겠습니다. 출근길 차간거리 넉넉히 두세요.",
    "안개로 시야가 나쁘겠습니다. 평소보다 일찍 나서시는 편이 좋습니다.",
    "안개가 짙겠습니다. 운전하신다면 속도를 줄여 주세요.",
)

# 임계값 — «매일 걸리는 조언은 조언이 아니다» 를 기준으로 잡는다.
# 9월 전국 예보로 재어 보니 WARM_DAY=28 은 이레 내내, BIG_SPREAD=10 은 닷새가
# 걸렸다. 부산은 7일 중 7일이 «일교차+더움» 이라 매일 같은 말이 나갔다.
#
# 아래 값들은 «평년보다 더운가» 를 절대 기온으로 흉내 낸 대용물이다. 진짜
# 기준은 평년 대비여야 한다 — 9월의 30도는 짚을 만하지만 8월의 30도는 예사고,
# 1월의 일교차 10도는 크지만 10월의 12도는 그렇지 않다. 그래서 이 숫자들은
# «맞는 값» 이 아니라 «지금 계절에 그럭저럭 맞는 값» 이고, 철이 바뀌면 또 어긋난다.
# 기상청 서술에 평년값(평년 최저/최고)이 들어 있으니 나중에 그걸 읽어
# 편차로 바꾸는 것이 제대로 된 수정이다. 그때까지의 임시 기준이다.
#
# 특보 기준(HEAT_WAVE·COLD_MORNING)은 다르다. 기상청이 정한 정의라 절대값이
# 맞고, 계절에 따라 움직여서도 안 된다.
# 두 값 사이에는 «아무 말도 안 하는» 구간이 있다. 아침 11도에 일교차 11도 같은
# 초가을의 평범한 날이 거기 든다 — 짚을 것이 없으면 침묵하는 것이 이 모듈의
# 규칙이므로 메우지 않는다. 빈칸을 채우려고 문턱을 낮추면 매일 걸리던 옛날로
# 돌아간다.
BIG_SPREAD = 12.0      # 일교차 (도) — 평년 대비의 대용물
COLD_MORNING = 5.0     # 아침 최저 (도) — 한파 대비, 기상청 기준이므로 고정
HEAT_WAVE = 33.0       # 폭염주의보 기준 (도) — 기상청 기준이므로 고정
WARM_DAY = 30.0        # 낮 기온 (도) — 평년 대비의 대용물
RAIN_LIKELY = 60       # 강수확률 (%)
CHILLY_MORNING = 10.0  # 아침 최저 (도) — 평년 대비의 대용물


# 사용자가 묻는 관심사. 같은 예보라도 무엇을 물었느냐에 따라 짚어줄 것이 다르다.
TOPICS: dict[str, tuple[str, ...]] = {
    "옷차림": ("뭐 입", "옷", "입을", "복장", "차림", "겉옷", "코트", "패딩", "반팔", "우비"),
    "우산": ("우산", "비 와", "비와", "비 올", "비올", "장화", "방수"),
    "야외": ("등산", "산행", "캠핑", "나들이", "소풍", "피크닉", "運動", "운동", "러닝",
             "자전거", "골프", "낚시", "바다", "해변", "야외", "산책", "축제"),
    "빨래": ("빨래", "세탁", "건조"),
    "세차": ("세차",),
}


def detect_topic(text: str) -> str | None:
    """질문에서 관심사를 하나 고른다. 없으면 None (기본 조언만 나간다)."""
    flat = (text or "").replace(" ", "")
    for topic, words in TOPICS.items():
        if any(w.replace(" ", "") in flat for w in words):
            return topic
    return None


@dataclass
class Advice:
    emoji: str
    text: str


def _spread(day) -> float | None:
    lows = [v for v in (day.tmin_lo, day.tmin_hi) if v is not None]
    highs = [v for v in (day.tmax_lo, day.tmax_hi) if v is not None]
    if not lows or not highs:
        return None
    return sum(highs) / len(highs) - sum(lows) / len(lows)


def topic_advice(topic: str, days) -> list[Advice]:
    """관심사에 맞춘 조언. 근거가 되는 수치가 없으면 빈 목록."""
    usable = [d for d in days if d.tmin_lo is not None and d.tmax_hi is not None]
    if not usable:
        return []

    rainy = [d for d in usable if (d.pop or 0) >= RAIN_LIKELY
             or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))]
    clear = [d for d in usable if "맑" in (d.sky or "") and (d.pop or 0) < 30]
    coldest = min(usable, key=lambda d: d.tmin_lo)
    hottest = max(usable, key=lambda d: d.tmax_hi)

    if topic == "우산":
        if rainy:
            return [Advice(":umbrella_with_rain_drops:",
                           f"{_days_text(rainy)}에 비 소식이 있어요. 우산 챙기시는 게 좋겠습니다.")]
        return [Advice(":sunny:", "당분간 비 소식은 없습니다. 우산은 두고 다니셔도 되겠어요.")]

    if topic == "옷차림":
        out = []
        spread = max((v for d in usable if (v := _spread(d)) is not None), default=0)
        if spread >= BIG_SPREAD:
            out.append(Advice(":thermometer:",
                              f"아침 {coldest.tmin_lo:.0f}도, 낮 {hottest.tmax_hi:.0f}도로 "
                              f"{spread:.0f}도 차이가 납니다. 껴입고 벗기 편한 옷이 낫겠어요."))
        elif coldest.tmin_lo <= COLD_MORNING:
            out.append(Advice(":cold_face:",
                              f"아침 최저 {coldest.tmin_lo:.0f}도입니다. 두껍게 입으세요."))
        elif hottest.tmax_hi >= WARM_DAY:
            out.append(Advice(":sunny:",
                              f"낮 최고 {hottest.tmax_hi:.0f}도까지 오릅니다. 얇게 입으세요."))
        else:
            out.append(Advice(":relieved:",
                              f"아침 {coldest.tmin_lo:.0f}도, 낮 {hottest.tmax_hi:.0f}도로 "
                              "무난합니다. 가볍게 입으셔도 되겠어요."))
        if rainy:
            out.append(Advice(":umbrella_with_rain_drops:",
                              f"{_days_text(rainy)}에는 비가 있어 신발도 신경 쓰시면 좋겠습니다."))
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


def build_advice(days, narratives=None) -> list[Advice]:
    """수치에서 짚이는 것만 고른다. 없으면 빈 목록."""
    usable = [d for d in days if d.tmin_lo is not None and d.tmax_hi is not None]
    if not usable:
        return []

    out: list[Advice] = []
    spreads = [(d, s) for d in usable if (s := _spread(d)) is not None]
    coldest = min(usable, key=lambda d: d.tmin_lo)
    hottest = max(usable, key=lambda d: d.tmax_hi)
    rainy = [d for d in usable if (d.pop or 0) >= RAIN_LIKELY
             or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))]

    # 1) 일교차 — 가장 흔하고, 건강 조언으로 이어지는 신호
    if spreads:
        worst, gap = max(spreads, key=lambda pair: pair[1])
        if gap >= BIG_SPREAD:
            out.append(Advice(
                ":thermometer:",
                f"*{worst.date:%m/%d}* " + _pick(SPREAD_LINES, worst.date).format(gap=gap),
            ))

    # 2) 추위 / 더위 — 둘 다 해당하면 더 극단적인 쪽만
    if coldest.tmin_lo <= COLD_MORNING:
        out.append(Advice(
            ":cold_face:",
            f"*{coldest.date:%m/%d}* "
            + _pick(COLD_LINES, coldest.date).format(t=coldest.tmin_lo),
        ))
    elif hottest.tmax_hi >= HEAT_WAVE:
        out.append(Advice(
            ":sun_with_face:",
            f"*{hottest.date:%m/%d}* "
            + _pick(HEAT_LINES, hottest.date).format(t=hottest.tmax_hi),
        ))
    elif hottest.tmax_hi >= WARM_DAY:
        out.append(Advice(
            ":sunny:",
            _pick(WARM_LINES, hottest.date).format(t=hottest.tmax_hi),
        ))
    elif coldest.tmin_lo <= CHILLY_MORNING:
        out.append(Advice(
            ":fallen_leaf:",
            _pick(CHILLY_LINES, coldest.date).format(t=coldest.tmin_lo),
        ))

    # 3) 비
    if rainy:
        out.append(Advice(
            ":umbrella_with_rain_drops:",
            _pick(RAIN_LINES, rainy[0].date).format(days=_days_text(rainy)),
        ))

    # 4) 예보관이 짚은 특이사항 — 수치로는 안 잡히는 것 (풍랑·건조·태풍 등)
    #
    # 이것들이 앞선다. 태풍·한파는 «낮에 덥습니다» 보다 먼저 알아야 할 일인데,
    # 뒤에 붙이면 out[:3] 에서 잘려 정작 위험한 쪽이 사라진다.
    ref = usable[0].date          # usable 은 위 가드로 비어 있지 않다
    hits: list[tuple[int, Advice]] = []
    for line in narratives or []:
        for keyword, (emoji, lines) in SPECIAL.items():
            if keyword in line and not any(k == keyword for k, _ in hits):
                hits.append((keyword, Advice(emoji, _pick(lines, ref))))
    # 같은 서술에 여러 특보가 섞여 오므로(«건조·황사·태풍») 급한 것부터 고른다.
    hits.sort(key=lambda pair: SPECIAL_ORDER.index(pair[0]))
    special = [advice for _, advice in hits]

    return (special + out)[:3]      # 너무 많으면 잔소리가 된다


# 급한 순서. 사람 목숨·안전에 가까운 것이 앞이다. SPECIAL 에 키를 더하면
# 여기에도 넣는다 — 빠지면 ValueError 로 바로 드러난다(조용히 뒤로 밀리지 않게).
SPECIAL_ORDER = ("태풍", "한파", "폭염", "너울", "풍랑", "황사", "안개", "건조")

# 값은 (이모지, 문구 후보) — 문구가 하나뿐이면 1-튜플로 둔다. 덕분에 변형을
# 더할 때 이 표만 고치면 되고, _pick 은 길이 1 에서도 그대로 동작한다.
SPECIAL: dict[str, tuple[str, tuple[str, ...]]] = {
    "태풍": (":cyclone:", ("태풍 영향이 예보돼 있어요. 이동 시간 넉넉히 잡으시고 창문 주변도 정리해 두세요.",)),
    "풍랑": (":ocean:", ("해상에 풍랑이 일겠습니다. 해안가는 오늘만큼은 피해 주세요.",)),
    "너울": (":ocean:", ("너울성 파도가 높겠습니다. 방파제·갯바위 근처는 정말 위험합니다.",)),
    "건조": (":droplet:", ("건조한 날이 이어집니다. 실내 가습하시고 화기 취급도 조심하세요.",)),
    "안개": (":fog:", FOG_LINES),
    "황사": (":mask:", ("황사가 예보돼 있어요. 나가실 때 마스크 챙기시는 게 좋겠습니다.",)),
    "한파": (":snowflake:", ("한파가 예보돼 있습니다. 수도 동파 주의하시고 따뜻하게 입으세요.",)),
    "폭염": (":sun_with_face:", ("폭염이 예보돼 있어요. 한낮 야외 활동은 잠시 미루시는 게 좋겠습니다.",)),
}
