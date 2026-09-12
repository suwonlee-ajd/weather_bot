"""기상청 원문과 수치를 받아 카드 문구와 슬랙 본문을 쓴다.

모델을 한 번만 불러 네 가지를 한꺼번에 받는다 — 카드 리드 문장, 구간별 서술(초반/중후반/주말),
특이사항, 그리고 슬랙 본문. 같은 자료를 두 번 넘기지 않아 싸고, 목소리도 일관된다.

수치는 이미 기상청 원문이라 모델이 지어낼 여지가 없다. 모델이 하는 일은 '옮겨 쓰기'뿐이다.

백엔드는 두 가지다 (WRITER 환경변수).
  gemini (기본) — Google 검색 그라운딩과 달리 **순수 생성은 무료 티어로 동작한다**. 결제 불필요.
                  gemini-3.8-flash 는 이 작업에 90초가 지나도 응답이 없어 3.5-flash 를 쓴다.
  claude        — ANTHROPIC_API_KEY 가 있을 때. 문장 품질이 가장 낫지만 선불 크레딧이 필요하다.

어느 쪽도 못 쓰거나 호출이 실패하면 규칙 기반 문구로 폴백한다 — 주 1회뿐인 게시를 거르지 않기 위해서다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from dataclasses import dataclass, field

from .advice import BIG_SPREAD, build_advice
from .forecast import Section, Source, WeekForecast

log = logging.getLogger(__name__)

SYSTEM = """\
너는 사내 슬랙 채널에 매주 월요일 아침 '이번 주 날씨'를 올리는 사람이다.
기상청 예보 통보문·중기예보 원문과 요일별 수치를 받아, 카드 이미지 문구와 슬랙 본문을 쓴다.

절대 규칙:
- 주어진 자료에 없는 수치·태풍 이름·특보를 지어내지 않는다. 기온은 준 값을 그대로 쓴다.
- 기온은 '지역 간 분포 범위'다. "아침 기온은 14~22℃" 는 하루의 최저/최고가 아니라
  전국 각지의 아침 최저값이 그 범위에 걸쳐 있다는 뜻이다. 이 의미를 헷갈리게 쓰지 않는다.

카드 문구(lead, sections):
- lead 는 이번 주 기온·날씨를 요약한 한 문장. 아침/낮 기온 범위를 숫자로 넣는다.
- sections 는 초반/중후반/주말 전망 세 구간. 각 2~3문장. 지역차(남부지방·제주도·강원 영동 등)가
  자료에 있으면 함께 적는다. period 는 "9월 7일~8일" 형식.
- **자료가 없는 구간은 sections 에서 통째로 뺀다.** "정보가 제공되지 않습니다" 같은 문장을 쓰지 않는다.

특이사항(alerts):
- 태풍·호우·강풍·폭염·한파·풍랑·너울처럼 주의가 필요한 것이 원문에 있으면 담는다. 없으면 빈 배열.

슬랙 본문(body) — **반드시 두 문단**으로, 사이에 빈 줄 하나:

  1문단은 **날씨**다. 출퇴근 시간대 체감으로 시작해, 왜 그런지(정체전선·대륙고기압·태풍 간접영향
  같은 기압계 배경)를 원문에서 가져와 붙인다. 문장을 끝맺지 말고 "~사오니", "~하겠으니" 처럼
  다음 문단으로 이어지는 연결어미로 닫는다.

  2문단은 **테마**다. 1문단의 날씨에서 곧바로 나오는 행동 하나를 권한다.
  겉옷·우산·양산·방수처럼 손에 잡히는 것으로 쓰고, 태풍·강풍·호우가 있으면 그에 맞는 대응
  (이동 시간 여유, 우비, 창문 근처 정리)으로 바꾼다. 이모지 1~2개로 맺는다.

- 전체 300자 내외. 요일을 나열하지 않는다. 날짜는 행동이 갈리는 날만 짚는다.
- 강조는 슬랙 mrkdwn 인 *별표 하나*. **별표 두 개**나 마크다운 제목(#)은 쓰지 않는다.
- 인사말·서명·출처 표기는 넣지 않는다.
- 이모지는 슬랙 코드(`:relieved:`, `:umbrella:`, `:fallen_leaf:`, `:sunny:`)로 쓰고,
  앞뒤 콜론을 반드시 닫는다. 확실하지 않은 코드는 쓰지 않는다.

문체 참고:
이번 주 출/퇴근 날씨는 다소 가을처럼 느껴질 수 있으나, 한낮엔 아직 습하고 더우며
현재 중부지방에 정체 전선이 걸쳐 있어 당분간 비가 잦을 수 있사오니

가을옷은 아직 이르며 기온이 *20도 이하의 맑은 날씨*가 연속되면 꺼내시길 추천드립니다. :relieved: :fallen_leaf:

아래 JSON 만 출력한다. 코드펜스나 설명 문장을 붙이지 않는다.

{"lead": "...", "sections": [{"label": "초반", "period": "9월 7일~8일", "text": "..."}],
 "alerts": [{"kind": "태풍", "text": "..."}], "body": "슬랙 본문"}
"""


@dataclass
class Written:
    lead: str
    sections: list[Section] = field(default_factory=list)
    alerts: list[dict[str, str]] = field(default_factory=list)
    body: str = ""


def extract_json(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON을 찾지 못했습니다: {raw[:200]}")
    return json.loads(text[start : end + 1])


# --------------------------------------------------------------------------- #
# 규칙 기반 폴백 (Claude 없이도 게시는 된다)
# --------------------------------------------------------------------------- #

def _rainy_days(week: WeekForecast):
    return [
        d
        for d in week.days
        if (d.pop or 0) >= 60 or any(w in (d.sky or "") for w in ("비", "눈", "소나기"))
    ]



# 카드 불릿 최대 개수. 원본 캡처가 3개였고, 너무 많으면 캡처처럼 보이지 않는다.
MAX_SECTIONS = 5

# 예보관 서술 한 줄. 예: "○ (기온) 이번 예보기간 아침 기온은 14~21℃, ..."
NARRATIVE_RE = re.compile(r"^[□○]\s*\(([^)]+)\)\s*(.+)$")


def official_sections(week: WeekForecast) -> list[Section]:
    """기상청 예보관이 쓴 문장을 그대로 카드 불릿으로 만든다.

    모델에게 다시 쓰게 하는 것보다 낫다 — 사람이 쓴 정확한 문장이고, 비용이 들지 않으며,
    지어낼 여지가 아예 없다. "(기온)", "(하늘상태)" 같은 괄호 머리말이 마침 원본 캡처의
    "초반 (9월 1일~2일):" 형식과 같은 모양이라 그대로 라벨로 쓴다.
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
            # "종합" 은 본문 1문단에, "기온" 은 카드 리드에 이미 들어간다. 카드에서는 뺀다.
            if head_text.startswith(("종합", "기온")) or text in seen:
                continue
            seen.add(text)
            # "오늘~그글피, 10~14일" 처럼 머리말에 기간이 붙어 오는 경우를 나눈다
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
        # 예보관 서술을 못 얻었을 때만 수치로 구간을 만든다
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
    spreads = [
        d.tmax_mid - d.tmin_mid for d in week.days if d.tmin_mid is not None and d.tmax_mid is not None
    ]
    rainy = _rainy_days(week)

    weather: list[str] = []
    if morning and noon:
        weather.append(
            f"이번 주 {week.area} 출/퇴근 날씨는 아침 *{morning[0]:.0f}~{morning[1]:.0f}℃*, "
            f"낮 *{noon[0]:.0f}~{noon[1]:.0f}℃* 분포가 예상되며"
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
        weather.append(f"기상청 예보는 *{headline}*이라 전하고 있사오니")
    elif spreads and max(spreads) >= BIG_SPREAD:
        weather.append(f"일교차가 최대 {max(spreads):.0f}도까지 벌어지겠사오니")
    elif rainy:
        weather.append("중간중간 비가 지나가겠사오니")
    else:
        weather.append("큰 변화 없이 이어지겠사오니")

    tips = build_advice(week.days, [line for n in week.narratives for line in n.lines])
    if tips:
        theme = [t.text for t in tips[:2]]
        # 문단 끝에 하나만. 문장마다 붙이면 산만해진다.
        theme[-1] = f"{theme[-1]} {tips[0].emoji}"
    else:
        theme = ["오늘도 무탈한 한 주 되시길 바랍니다. :sunny:"]

    body = " ".join(weather) + "\n\n" + " ".join(theme)
    return Written(lead=lead, sections=sections, alerts=[], body=body)


# --------------------------------------------------------------------------- #
# Claude
# --------------------------------------------------------------------------- #

# 닫는 콜론이 빠진 이모지 조각(:falling_leaf_ 같은)만 걸러낸다.
# 앞의 (?<![\w:]) 가 "12:30" 의 :30 같은 시각 표기를 건드리지 않게 막아준다.
BROKEN_EMOJI_RE = re.compile(r"(?<![\w:]):[a-z][a-z0-9_+\-]*(?![a-z0-9_+\-]*:)")


def sanitize(text: str) -> str:
    """모델이 흘린 반쪽짜리 이모지 코드를 지운다. 슬랙에서 그대로 노출되면 지저분하다."""
    return re.sub(r"[ \t]{2,}", " ", BROKEN_EMOJI_RE.sub("", text)).strip()


def _parse(raw: str, week: WeekForecast) -> Written:
    data = extract_json(raw)
    sections = [
        Section(
            label=str(s.get("label", "")),
            period=str(s.get("period", "")),
            text=sanitize(str(s.get("text", ""))),
            sources=week.sources,
        )
        for s in data.get("sections", [])
        if s.get("text")
    ]
    written = Written(
        lead=sanitize(str(data.get("lead", ""))),
        sections=sections,
        alerts=[
            {"kind": str(a.get("kind", "특이사항")), "text": sanitize(str(a["text"]))}
            for a in data.get("alerts", [])
            if a.get("text")
        ],
        body=sanitize(str(data.get("body", ""))),
    )
    if not (written.lead and written.body):
        raise ValueError("lead 또는 body 가 비어 있습니다")
    return written


def _write_gemini(week: WeekForecast, prompt: str, model: str, timeout_sec: int) -> Written:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY") or None,
        http_options=types.HttpOptions(timeout=timeout_sec * 1000),
    )
    # 검색 도구를 붙이지 않는다. 그라운딩은 무료 티어 할당량이 0 이고, 자료는 이미 기상청 원문이다.
    interaction = client.interactions.create(model=model, input=f"{SYSTEM}\n\n---\n\n{prompt}")
    return _parse(interaction.output_text or "", week)


def _write_claude(week: WeekForecast, prompt: str, model: str) -> Written:
    import anthropic

    response = anthropic.Anthropic().beta.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": os.environ.get("ANTHROPIC_EFFORT", "low")},
        # 안전 분류기 거절에 대비한 서버사이드 폴백 (날씨 글에서 걸릴 일은 사실상 없다)
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("모델이 응답을 거절했습니다")
    return _parse("\n".join(b.text for b in response.content if b.type == "text"), week)


def write(week: WeekForecast, cfg=None) -> Written:
    """카드 문구와 슬랙 본문을 만든다. 무엇이 실패하든 규칙 기반 문구로는 반드시 돌아온다."""
    backend = (getattr(cfg, "writer", "") or os.environ.get("WRITER", "gemini")).lower()
    if backend == "none":
        return fallback(week)

    prompt = "다음 기상청 자료로 카드 문구와 슬랙 본문을 써줘.\n\n" + week.as_digest()

    if backend == "claude":
        if not any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")):
            log.info("ANTHROPIC_API_KEY 미설정 - 규칙 기반 문구를 사용합니다.")
            return fallback(week)
        model = getattr(cfg, "anthropic_model", "") or os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
        runner = lambda: _write_claude(week, prompt, model)  # noqa: E731
    else:
        if not os.environ.get("GEMINI_API_KEY"):
            log.info("GEMINI_API_KEY 미설정 - 규칙 기반 문구를 사용합니다.")
            return fallback(week)
        model = getattr(cfg, "gemini_model", "") or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
        timeout = int(getattr(cfg, "writer_timeout_sec", 0) or os.environ.get("WRITER_TIMEOUT_SEC", "90"))
        runner = lambda: _write_gemini(week, prompt, model, timeout)  # noqa: E731

    try:
        written = runner()
        log.info("문구 생성 완료 (%s / %s)", backend, model)
        return written
    except Exception:  # 문구 생성 실패로 게시를 거르지 않는다
        log.exception("%s 문구 생성 실패 - 규칙 기반 문구로 대체합니다.", backend)
        return fallback(week)
