"""멘션 한 줄을 받아 답을 고름 — 인사·단풍·산·동네·광역·전망."""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
from dataclasses import dataclass, replace

from src.advice.rules import build_advice, detect_topic, topic_advice
from src.common.cache import get_or_set
from src.common.config import KST
from src.common.text import day_label, range_text
from src.kma.dong_zone import find_wide, search_dong
from src.kma.notice import lines_for_dates
from src.kma.outlook import OutlookError, fetch_outlook
from src.kma.page import ScrapeError
from src.kma.regions import NATIONWIDE, extract_region, resolve_region
from src.kma.scrape import scrape_range
from src.mention.dong_reply import _dong_reply
from src.mention.foliage_note import _foliage_note
from src.mention.foliage_reply import _mountain_reply, _theme
from src.mention.parse import (
    DONG_MAX_DAYS,
    EXPLICIT_DATE_RE,
    GREETING_RE,
    MAX_FORECAST_DAYS,
    MENTION_RE,
    NEXT_WEEK_RE,
    NOISE_RE,
    OUTLOOK_RE,
    PAST_OBS_URL,
    PAST_RE,
    THANKS_RE,
    THIS_WEEK_RE,
    TODAY_RE,
    TOMORROW_RE,
    TOO_FAR_RE,
    _period,
)
from src.mention.texts import (
    NO_EMOJI,
    YES_EMOJI,
    about,
    help_text,
    self_mention,
    sky_emoji,
)
from src.season.foliage_map import render_png as render_foliage_png
from src.season.mountains import (
    MOUNTAINS,
    find_mountain,
    in_region,
)

log = logging.getLogger("weather-mention")


CACHE_TTL_SEC = int(os.environ.get("MENTION_CACHE_TTL", "3600"))


def _outlook_reply(region, query: str) -> str:
    """1개월 전망. 값이 아니라 확률이라는 점을 분명히 해 둠."""
    try:
        o = fetch_outlook(region.key if region else "전국")
    except OutlookError as exc:
        log.warning("1개월 전망 실패: %s", exc)
        return (
            f"1개월 전망을 가져오지 못했습니다. {NO_EMOJI}\n"
            "기상청에서 직접 보실 수 있어요 — "
            "https://www.weather.go.kr/w/climate/montr-prediction/month1.do"
        )

    label = region.label if region else "전국"
    lines = [
        f"*{label}* 1개월 전망 ({o.period})",
        "_10일 뒤부터는 날씨를 콕 집어 말할 수 없어, 평년과 견준 *확률* 로 나옵니다._",
        "",
    ]
    for w in o.weeks:
        lines.append(f"• `{w.period}` {w.summary}")
        detail = f"   기온 평년({w.temp_normal}℃) 대비 *{w.temp_text}*"
        if w.rain_text:
            detail += f" · 강수 *{w.rain_text}*"
        lines.append(detail)
    lines.append("")
    lines.append(f"_기상청 1개월 전망 · {o.issued} 발표_")
    lines.append(f"_주 단위라 하루하루의 기온은 없습니다. 10일 안쪽은 `{self_mention()} {label}` 로 보세요._")
    return "\n".join(lines)


@dataclass
class Reply:
    """멘션 답. 단풍 현황을 물으면 지도가 함께 감."""
    text: str
    image: bytes | None = None


def answer(text: str, now: dt.datetime | None = None) -> Reply:
    """멘션 진입점. 단풍·꽃은 여기서 먼저 가르고, 나머지 날씨 질문은 build_reply 로 보냄.

    단풍은 인사·과거·전망보다 먼저 봐야 함 — "설악산 단풍 물들었나" 의 '었나' 는 과거로,
    "올가을 단풍" 의 '가을' 은 1개월 전망으로, "안녕 단풍 어때" 는 자기소개로 빠짐.
    """
    now = now or dt.datetime.now(tz=KST)
    theme = _theme(MENTION_RE.sub(" ", text).strip(), now)
    if theme is None:
        return Reply(build_reply(text, now))
    reply, snap = theme
    if snap is None:
        return Reply(reply)
    try:
        # 같은 현황이면 같은 그림 — 물을 때마다 Chromium 을 띄우지 않게. 키에 현황 내용을
        # 넣음 — 글(방금 받은 현황)과 그림(캐시)이 어긋나지 않게.
        image = get_or_set(
            ("foliage-map", now.date(), snap.signature()), CACHE_TTL_SEC,
            lambda: render_foliage_png(snap, now.date(), span_label="앞으로 7일"),
        )
        return Reply(reply, image)
    except Exception:
        # 지도가 안 그려져도 글로는 답함
        log.warning("단풍 지도 렌더링 실패 — 글로만 답합니다", exc_info=True)
        return Reply(reply)


def build_reply(text: str, now: dt.datetime | None = None) -> str:
    """날씨 질문에 대한 답. 멘션 진입점은 answer() — 단풍·꽃은 거기서 먼저 가름."""
    now = now or dt.datetime.now(tz=KST)
    query = MENTION_RE.sub(" ", text).strip()

    # 기본 기간은 오늘부터 7일, "이번 주"/"다음 주"를 명시하면 그 주 월~일 — 멘션으로
    # 원하는 건 **앞으로의 날씨**라, 달력상 '이번 주'로 잡으면 주 중간엔 지난 요일 탓에
    # 이틀치만 나옴.
    # 지역 이름이 섞여 있지 않은 순수한 인사·잡담이면 자기소개로 답함.
    # ('부산 안녕' 처럼 지역이 함께 오면 날씨를 보여주는 쪽이 맞음)
    if GREETING_RE.search(query):
        stripped = GREETING_RE.sub(" ", query)
        stripped = NOISE_RE.sub(" ", stripped).strip()
        if not stripped or resolve_region(stripped)[0] is None:
            if re.search(r"도움말|help|사용법|어떻게\s*써", query, re.I):
                return help_text()
            # 감사 인사엔 한 줄로 답함 — 자기소개 전문은 과함
            if THANKS_RE.search(query):
                return f"천만에요. 날씨 궁금하시면 언제든 불러 주세요. {YES_EMOJI}"
            return about()

    # 과거는 관측 링크로 돌림 — 예보가 아니라 관측이라 이 봇의 자료에 없음. 미래 분기보다
    # 먼저 봄 — 계절 표현('지난 해 여름')과 겹쳐, 늦게 보면 과거 질문에 전망이 나감.
    if PAST_RE.search(query):
        return (
            "지난 날씨는 제가 볼 수 없습니다. 기상청 예보만 다루고 있어서,\n"
            f"*오늘부터 앞으로* 만 알려드릴 수 있습니다. {NO_EMOJI}\n"
            "\n지난 날씨는 기상청에서 직접 보실 수 있어요 — 날짜와 지점을 골라 "
            "일별 기온·강수량을 확인할 수 있습니다.\n"
            f"{PAST_OBS_URL}"
        )

    # 10일 예보 너머. 1개월 전망(주 단위 확률)으로 답할 수 있으면 답함.
    if TOO_FAR_RE.search(query):
        return (
            "그만큼 먼 날씨는 기상청도 예보하지 않습니다. "
            f"1개월 전망까지가 한계예요. {NO_EMOJI}\n"
            f"\n_`{self_mention()} 다음 달` 로 4주치 확률 전망을 보실 수 있습니다._"
        )

    if OUTLOOK_RE.search(query):
        cleaned = OUTLOOK_RE.sub(" ", query)
        cleaned = NOISE_RE.sub(" ", cleaned).strip()
        region, _ = resolve_region(cleaned) if cleaned else (NATIONWIDE, "")
        return _outlook_reply(region or NATIONWIDE, query)

    start, days, title = _period(query, now)

    # 산 이름이면 산 아래 마을 예보로 답함. 산은 지역 목록에 없어, 그냥 두면 '설악산' 은
    # "아는 지역이 아닙니다" 로, '주말 설악산 등산' 은 조언 갈래에서 전국으로 빠짐.
    mountain = find_mountain(query)
    if mountain:
        return _mountain_reply(mountain, start, days, title, now.date())

    # 탐지에 쓴 바로 그 패턴으로 지움 — 목록이 두 군데로 갈라지지 않게.
    for pattern in (EXPLICIT_DATE_RE, NEXT_WEEK_RE, THIS_WEEK_RE,
                    TODAY_RE, TOMORROW_RE, NOISE_RE):
        query = pattern.sub(" ", query)
    query = query.strip()

    topic = detect_topic(text)

    # '부산' 처럼 시도 하나를 물었으면 그 시도의 동네예보를 보여줌.
    # 광역 구역(부산·울산·경남)으로 답하면 기온이 경남내륙까지 아우른 분포라
    # 부산만 궁금한 사람에게는 남의 동네 숫자가 섞임.
    #
    # 동네예보가 닿지 않는 날(5일 너머)을 물었으면 광역으로 넘김 —
    # 좁게 답하려다 아예 답을 못 하는 것보다 나음.
    # 문장으로 물어도 낱말마다 도시명을 찾음 ("내일 부산 출장가는데 뭐 입지") — 기간·잡음을
    # 지운 query 통째로는 'X 날씨' 만 걸리고 긴 문장은 안 걸림.
    wide = find_wide(query) or next(
        (w for tok in re.split(r"[\s,]+", query) if (w := find_wide(tok))), None)
    if wide:
        last = now.date() + dt.timedelta(days=DONG_MAX_DAYS - 1)
        if start > last:
            pass                      # 동네예보가 닿지 않는 날 — 아래 광역으로
        elif start + dt.timedelta(days=days - 1) <= last:
            reply = _dong_reply(wide[0], wide[1], days, start, today=now.date())
            # 거절로 끝나면 막지 않고 광역으로 넘김 — 예보 끝자락은 값이 모자라
            # 거절되지만(조각난 날은 버림) 광역은 답할 수 있음.
            if NO_EMOJI not in reply:
                return reply
        elif title.startswith("앞으로"):
            # 기간을 따로 말하지 않았으면 닿는 데까지 좁게 답하고, 더 필요하면 광역으로
            # 안내함 — 며칠인지보다 «부산 값» 인지가 중요함.
            return _dong_reply(wide[0], wide[1], (last - start).days + 1, start, today=now.date())
        # '이번 주'·'다음 주' 처럼 기간을 콕 집어 물었으면 그 기간을 채울 수 있는
        # 광역으로 감. 이레를 물었는데 사흘만 주는 것이 더 불친절함.

    region, note = resolve_region(query)
    if region is None and topic:
        # 조언 질문은 문장에서 지역을 집어냄 — 문장이 길고 지역이 섞여 있어("주말 무등산
        # 등산 괜찮아?") 지우기로는 '무등산' 의 '등산' 까지 잘려 나감.
        region, note = extract_region(text)
        if region is None:
            region, note = NATIONWIDE, ""
    if region is None:
        # 광역에 없으면 동 단위인지 봄 (역삼동, 판교동, 행정동코드 …)
        hits = search_dong(query, limit=4)
        if len(hits) == 1 or (hits and hits[0].name.replace(' ', '') == query.replace(' ', '')):
            return _dong_reply(hits[0].code, hits[0].full_name, days, start, today=now.date())
        if hits:
            # 어느 곳인지 단정하지 않고 되물음 — 강릉에도 강남동이 있음
            listed = "\n".join(f"• {h.full_name}" for h in hits)
            return (
                f"*{query}* 로 찾은 곳이 여럿입니다. 하나만 골라 다시 불러 주세요. {NO_EMOJI}\n"
                f"{listed}\n\n_예: {self_mention()} {hits[0].short_name.split()[-1]}_"
            )
        return f"'{query}' 는 제가 아는 지역이 아닙니다. {NO_EMOJI}\n\n{help_text()}"

    # 캐시에는 자르기 전의 넓은 구간(오늘부터 열흘)을 담고, 물어본 기간으로 좁히기는 아래에서
    # 함. 캐시는 지역 하나당 한 항목이라 «물어본 기간» 과 무관해야 함 — scrape_range 가
    # window 로 자른 값을 담으면 «다음 주» 를 먼저 물은 뒤 «앞으로 7일» 에 오늘·내일이 빠짐.
    try:
        cached = get_or_set(
            region.key, CACHE_TTL_SEC,
            lambda: scrape_range(now, now.date(), MAX_FORECAST_DAYS, region),
        )
        window = {start + dt.timedelta(days=i) for i in range(days)}
        scrape = replace(cached, days={d: v for d, v in cached.days.items() if d in window})
    except ScrapeError as exc:
        log.warning("수집 실패: %s", exc)
        return "기상청 예보를 가져오지 못했습니다. 잠시 뒤 다시 불러 주세요."

    if not scrape.days:
        return f"*{region.label}* {start:%m/%d} 부터의 예보를 찾지 못했습니다."

    end = start + dt.timedelta(days=days - 1)
    # 머리글에는 실제로 예보가 있는 날까지만 적음. 중기예보는 오늘부터 열흘까지라
    # 주 초에 «다음 주» 를 물으면 사흘만 걸치는데, 이레라고 적으면 잘라먹은 것처럼 읽힘.
    have = max(scrape.days) if scrape.days else end
    shown_end = min(end, have)
    span_text = (day_label(start) if start == shown_end
                 else f"{day_label(start)} ~ {day_label(shown_end)}")
    lines = [f"*{region.label}* {title} ({span_text})"]
    if note:
        lines.append(f"_{note}_")
    # 그 주에서 가장 춥고 더운 날만 굵게 함. 전부 굵게 하면 강조가 사라짐.
    complete = [
        scrape.days[d] for d in sorted(scrape.days)
        if scrape.days[d].tmin_lo is not None and scrape.days[d].tmax_hi is not None
    ]
    coldest = min(complete, key=lambda d: d.tmin_lo).date if complete else None
    hottest = max(complete, key=lambda d: d.tmax_hi).date if complete else None

    for offset in range((shown_end - start).days + 1):
        date = start + dt.timedelta(days=offset)
        v = scrape.days.get(date)
        if v is None:
            continue
        morning = range_text(v.tmin_lo, v.tmin_hi) or "-"
        noon = range_text(v.tmax_lo, v.tmax_hi) or "-"
        parts = [
            f"아침 *{morning}*" if date == coldest else f"아침 {morning}",
            f"낮 *{noon}*" if date == hottest else f"낮 {noon}",
        ]
        if v.sky:
            parts.append(sky_emoji(v.sky))
        if v.pop is not None:
            parts.append(f"`{v.pop}%`")
        lines.append(f"• `{day_label(date)}` " + " · ".join(parts))

    # 물어본 기간을 다 채우지 못했으면 왜 짧은지 밝힘. 말없이 빠뜨리면
    # 봇이 잘라먹은 것으로 읽힘.
    if shown_end < end:
        lines.append(f"_{day_label(shown_end + dt.timedelta(days=1))} 이후는 "
                     f"아직 예보가 작성되지 않았습니다 {NO_EMOJI}_")

    shown = [scrape.days[d] for d in sorted(scrape.days)]
    # 조언은 화면에 보인 날만 근거로 삼음. 캐시는 열흘을 들고 있어서, 하루만 물었는데
    # 사흘 뒤 일교차를 말하면 물은 것과 다른 답이 됨.
    window = {start + dt.timedelta(days=i) for i in range(days)}
    scoped = [d for d in shown if d.date in window]
    narrative_lines = [line for n in scrape.narratives for line in n.lines]
    # 물어본 것에 먼저 답하고, 그 밖에 짚을 것이 있으면 덧붙임.
    tips = topic_advice(topic, scoped, region.key) if topic else []
    # 겹침은 이모지로 가림 — 문구가 날짜마다 달라지므로(advice.py _pick)
    # 문장을 비교하면 «우산 챙기세요» 와 «우산 없이 나서면» 이 서로 다른 말로
    # 보여 우산 조언이 두 줄 나감. 같은 이모지면 같은 종류의 조언.
    seen = {x.emoji for x in tips}
    tips += [t for t in build_advice(scoped, narrative_lines, region.key)
             if t.emoji not in seen][: 3 - len(tips)]
    if tips:
        lines.append("")
        lines += [f"{t.emoji} {t.text}" for t in tips]

    for narrative in sorted(scrape.narratives, key=lambda n: 0 if "통보문" in n.title else 1):
        # 물어본 날짜의 줄만 고름. 앞에서 2줄을 그냥 자르면 «모레» 를 물어도
        # «(오늘, 12일)» 이 붙어 질문과 어긋난 답이 됨.
        picked = lines_for_dates(narrative.lines, now.date(), window)
        for line in picked[:2]:
            lines.append(f"> {line}")
        stamp = f"{narrative.issued_at:%m/%d %H시}" if narrative.issued_at else "발표시각 미상"
        lines.append(f"_{narrative.title} · {stamp} 발표_")

    mountains = MOUNTAINS if region is NATIONWIDE else in_region(region.key)
    lines += _foliage_note(mountains, start, shown_end, now.date())   # 보여 준 날까지만
    return "\n".join(lines)
