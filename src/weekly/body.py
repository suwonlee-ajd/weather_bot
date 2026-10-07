"""규칙 기반 주간 본문 — 모델 없이 카드 문구와 두 문단 본문을 만듦."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from src.advice.phrases import TEMP_STEMS
from src.advice.rules import BIG_SPREAD, RAIN, Advice, build_advice, first_three
from src.common.text import short_day_label
from src.weekly.forecast import Section, Source, WeekForecast


@dataclass
class Written:
    lead: str
    sections: list[Section] = field(default_factory=list)
    alerts: list[dict[str, str]] = field(default_factory=list)
    body: str = ""


def _rainy_days(week: WeekForecast):
    return [
        d
        for d in week.days
        if (d.pop or 0) >= 60 or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))
    ]


# 카드 불릿 최대 개수. 원본 캡처가 3개였고, 너무 많으면 캡처처럼 보이지 않음.
MAX_SECTIONS = 5


# 예보관 서술 한 줄. 예: "○ (기온) 이번 예보기간 아침 기온은 14~21℃, ..."
NARRATIVE_RE = re.compile(r"^[□○]\s*\(([^)]+)\)\s*(.+)$")


def official_sections(week: WeekForecast) -> list[Section]:
    """기상청 예보관이 쓴 문장을 그대로 카드 불릿으로 만듦.

    모델에게 다시 쓰게 하는 것보다 나음 — 사람이 쓴 정확한 문장이고, 비용이 들지 않으며,
    지어낼 여지가 아예 없음. "(기온)", "(하늘상태)" 같은 괄호 머리말은 그대로 라벨로 씀 —
    마침 원본 캡처의 "초반 (9월 1일~2일):" 형식과 같은 모양.
    """
    sections: list[Section] = []
    seen: set[str] = set()
    # 가까운 날(통보문)을 먼저, 그 다음 중기예보
    ordered = sorted(week.narratives, key=lambda n: 0 if "통보문" in n.title else 1)
    for narrative in ordered:
        source = [Source(narrative.title, narrative.url)]
        for line in narrative.lines:
            m = NARRATIVE_RE.match(line)
            if not m:
                continue
            head_text, text = m.group(1).strip(), m.group(2).strip()
            # "종합"·"기온" 은 카드에서 뺌 — 각각 본문 1문단과 카드 리드에 이미 들어감.
            if head_text.startswith(("종합", "기온")) or text in seen:
                continue
            seen.add(text)
            # "오늘~그글피, 10~14일" 처럼 머리말에 기간이 붙어 오는 경우를 나눔
            label, _, period = head_text.partition(",")
            sections.append(Section(label.strip(), period.strip(), text, source))
    return sections[:MAX_SECTIONS]


def fallback(week: WeekForecast) -> Written:
    """모델 없이 만드는 문구. 카드는 예보관 원문, 본문은 규칙 기반 2문단."""
    morning, noon = week.morning_range, week.noon_range
    if morning and noon:
        lead = (
            f"이번 주 {week.area} 아침 기온은 {morning[0]:.0f}~{morning[1]:.0f}℃, "
            f"낮 기온은 {noon[0]:.0f}~{noon[1]:.0f}℃ 분포가 예상됩니다."
        )
    else:
        lead = f"이번 주 {week.area} 예보입니다."

    sections = official_sections(week)
    if not sections:
        # 예보관 서술을 못 얻었을 때만 수치로 구간을 만듦
        for label, lo, hi in (("초반", 0, 2), ("중후반", 2, 5), ("주말 전망", 5, 7)):
            chunk = [d for d in week.days[lo:hi] if d.is_complete]
            if not chunk:
                continue
            mins = [v for d in chunk for v in (d.tmin_lo, d.tmin_hi) if v is not None]
            maxs = [v for d in chunk for v in (d.tmax_lo, d.tmax_hi) if v is not None]
            sections.append(
                Section(
                    label,
                    f"{chunk[0].date:%-m월 %-d일}~{chunk[-1].date:%-d일}",
                    f"아침 기온은 {min(mins):.0f}~{max(mins):.0f}℃, "
                    f"낮 기온은 {max(maxs):.0f}℃ 안팎까지 오르겠습니다.",
                    week.sources,
                )
            )

    # --- 본문: 1문단 날씨 / 2문단 테마 ---
    # 여기서는 1문단을 문장으로 맺음. 모델은 원본처럼 «~사오니» 로 열어 두고 2문단에서
    # 이어받지만(SYSTEM), 규칙 기반 2문단은 «사실. 권하는 말.» 로 시작하는 조언이라
    # 이어받지 못함 — 열어 두면 글이 끊겨 읽힘.
    spreads = [
        d.tmax_mid - d.tmin_mid for d in week.days if d.tmin_mid is not None and d.tmax_mid is not None
    ]
    rainy = _rainy_days(week)

    weather: list[str] = []
    if morning and noon:
        weather.append(
            f"이번 주 {week.area} 출/퇴근 날씨는 아침 *{morning[0]:.0f}~{morning[1]:.0f}℃*, "
            f"낮 *{noon[0]:.0f}~{noon[1]:.0f}℃* 분포가 예상됩니다."
        )
    headline = next(
        (
            re.sub(r"^[□○]\s*\(종합\)\s*", "", n.lines[0]).strip()
            for n in week.narratives
            if n.lines and n.lines[0].startswith("□")
        ),
        "",
    )
    if headline:
        # 통보문 (종합)은 인용으로 실음 — «…쌀쌀, 해상 높은 물결 유의» 같은 개조식.
        weather.append(f'기상청은 "*{headline}*"{quote_josa(headline)} 전하고 있습니다.')
    elif spreads and max(spreads) >= BIG_SPREAD:
        weather.append("낮과 아침의 기온차가 큰 한 주가 되겠습니다.")
    elif rainy:
        weather.append("중간중간 비가 지나가겠습니다.")
    else:
        weather.append("날씨는 큰 변화 없이 이어지겠습니다.")

    tips = build_advice(week.days, [line for n in week.narratives for line in n.lines])
    body = " ".join(weather) + "\n\n" + theme_paragraph(tips)
    return Written(lead=lead, sections=sections, alerts=[], body=body)


def quote_josa(text: str) -> str:
    """인용 조사. 끝 글자에 받침이 있으면 «이라고», 없으면 «라고» — «기온차 큼"이라고», «유의"라고».

    괄호·숫자 같은 꼬리는 건너뛰고 마지막 한글로 고름.
    """
    last = next((c for c in reversed(text) if "가" <= c <= "힣"), "")
    return "이라고" if last and (ord(last) - ord("가")) % 28 else "라고"


_TEMP_ORDER = tuple(TEMP_STEMS)   # 앞선 조언의 권하는 말과 이모지를 씀


THEME_SENTENCES = 2               # 2문단에 담는 조언 묶음 수. 많으면 잔소리가 됨.


def theme_paragraph(tips: list[Advice]) -> str:
    """조언을 한 문단으로 엮음.

    날짜와 권하는 말이 겹치지 않게 묶음 — 멘션은 한 줄에 하나씩이라 «*10/07* 일교차가 …» 의
    날짜가 머리표로 읽히지만, 그냥 이어 붙이면 같은 날짜와 권하는 말(겉옷·껴입기)이 거듭 나옴.
      * 기온 조언(advice.TEMP_STEMS)은 날이 달라도 한 문장으로 합치고, 날짜 순으로 적음.
        같은 날은 날짜를 한 번만 씀. 권하는 말은 앞선 조언의 것 하나만 남김.
        «*10/7(수)에는* 아침 최저 4도까지 내려가고 일교차가 14도 안팎으로 벌어지겠습니다.»
      * 비는 권하는 말이 달라(우산) 따로 두되, 바로 앞과 같은 날이면 «같은 날은» 으로 받음.
      * 날짜 없는 조언(특이사항)은 원래 문장 그대로, 맨 앞에 둠. 이모지가 같으면(풍랑·너울)
        같은 종류라 앞선 하나만 — 두 자리를 다 차지하면 기온·비 조언이 밀려남.
      * 담을 묶음은 build_advice 의 우선순위로 고르고, 보이는 순서는 날짜 순.
      * 이모지는 문단 끝에 하나만 — 가장 앞선 묶음의 것. 문장마다 붙이면 산만해짐.
    굵게 표시는 조사까지 감쌈(*10/7(수)에는*) — 닫는 별표 바로 뒤에 글자가 붙으면
    슬랙이 굵게로 읽지 않을 수 있음.
    """
    groups: dict[object, list[Advice]] = {}
    for i, tip in enumerate(tips):
        key = "기온" if tip.kind in TEMP_STEMS else i if tip.dates else tip.emoji
        groups.setdefault(key, []).append(tip)
    if not groups:
        return "이번 주도 무탈하게 보내시길 바랍니다. :sunny:"

    picked = [sorted(g, key=lambda t: _TEMP_ORDER.index(t.kind)) if g[0].kind in TEMP_STEMS else g
              for g in list(groups.values())[:THEME_SENTENCES]]
    emoji = picked[0][0].emoji
    picked.sort(key=lambda g: min((t.dates[0] for t in g if t.dates), default=dt.date.min))

    sentences: list[str] = []
    prev: tuple = ()
    for group in picked:
        lead = group[0]
        if lead.kind == RAIN:
            label = first_three([short_day_label(d) for d in lead.dates], "·")
            when = "같은 날은" if lead.dates == prev else f"*{label}에는*"
            sentences.append(f"{when} 비가 오겠습니다. {lead.act}")
            prev = lead.dates
        elif lead.kind in TEMP_STEMS:
            by_day: dict[dt.date, list[Advice]] = {}
            for t in sorted(group, key=lambda t: (t.dates[0], _TEMP_ORDER.index(t.kind))):
                by_day.setdefault(t.dates[0], []).append(t)
            clause = "고, ".join(
                f"*{short_day_label(day)}에는* "
                + "고 ".join(TEMP_STEMS[t.kind].format(v=t.value) for t in same_day)
                for day, same_day in by_day.items()
            )
            sentences.append(f"{clause}겠습니다. {lead.act}")
            prev = tuple(by_day) if len(by_day) == 1 else ()
        else:
            sentences.append(lead.text)
            prev = ()
    return f"{' '.join(sentences)} {emoji}"
