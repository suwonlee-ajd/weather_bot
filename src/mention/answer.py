"""멘션 한 줄을 받아 답을 고름 — 인사·단풍·산·동네·광역·전망."""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass

from src.advice.rules import detect_topic
from src.common.cache import get_or_set
from src.common.config import KST
from src.kma.dong_zone import find_wide, search_dong
from src.kma.outlook import OutlookError, fetch_outlook
from src.kma.regions import NATIONWIDE, Region, extract_region, resolve_region
from src.mention.dong_reply import _dong_reply
from src.mention.foliage_reply import _mountain_reply, _theme
from src.mention.parse import (
    DONG_MAX_DAYS,
    EXPLICIT_DATE_RE,
    GREETING_RE,
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
from src.mention.region_reply import CACHE_TTL_SEC, region_reply
from src.mention.texts import (
    NO_EMOJI,
    YES_EMOJI,
    about,
    help_text,
    self_mention,
)
from src.season.foliage_map import render_png as render_foliage_png
from src.season.mountains import (
    find_mountain,
)

log = logging.getLogger("weather-mention")




def _outlook_reply(region, query: str) -> str:
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
    text: str
    image: bytes | None = None


def answer(text: str, now: dt.datetime | None = None) -> Reply:
    """멘션 진입점. 단풍·꽃을 먼저 가르고 나머지는 build_reply 로.

    단풍을 인사·과거·전망보다 먼저 봄 — '물들었나' 는 과거로, '올가을' 은 전망으로 샘.
    """
    now = now or dt.datetime.now(tz=KST)
    theme = _theme(MENTION_RE.sub(" ", text).strip(), now)
    if theme is None:
        return Reply(build_reply(text, now))
    reply, snap = theme
    if snap is None:
        return Reply(reply)
    try:
        # 현황이 같으면 그림 재사용(Chromium 렌더링이 느림). 키에 현황을 넣어 글과 어긋나지 않게 함
        image = get_or_set(
            ("foliage-map", now.date(), snap.signature()), CACHE_TTL_SEC,
            lambda: render_foliage_png(snap, now.date(), span_label="앞으로 7일"),
        )
        return Reply(reply, image)
    except Exception:
        log.warning("단풍 지도 렌더링 실패 — 글로만 답합니다", exc_info=True)
        return Reply(reply)


def build_reply(text: str, now: dt.datetime | None = None) -> str:
    """단풍·꽃을 뺀 날씨 질문의 답. 진입점은 answer()."""
    now = now or dt.datetime.now(tz=KST)
    query = MENTION_RE.sub(" ", text).strip()
    if (reply := _small_talk(query)) is not None:
        return reply

    start, days, title = _period(query, now)
    if mountain := find_mountain(query):
        # 산은 지역 목록에 없음 — 산 아래 마을 예보로
        return _mountain_reply(mountain, start, days, title, now.date())

    for pattern in (EXPLICIT_DATE_RE, NEXT_WEEK_RE, THIS_WEEK_RE, TODAY_RE, TOMORROW_RE, NOISE_RE):
        query = pattern.sub(" ", query)
    query = query.strip()

    if (reply := _city_reply(query, start, days, title, now)) is not None:
        return reply
    topic = detect_topic(text)
    found = _find_region(query, text, topic, start, days, now)
    if isinstance(found, str):
        return found
    region, note = found
    return region_reply(region, note, title, start, days, topic, now)


def _small_talk(query: str) -> str | None:
    # 인사만 왔을 때만 — '부산 안녕' 은 날씨로 답함
    if GREETING_RE.search(query):
        stripped = NOISE_RE.sub(" ", GREETING_RE.sub(" ", query)).strip()
        if not stripped or resolve_region(stripped)[0] is None:
            if re.search(r"도움말|help|사용법|어떻게\s*써", query, re.I):
                return help_text()
            if THANKS_RE.search(query):
                return f"천만에요. 날씨 궁금하시면 언제든 불러 주세요. {YES_EMOJI}"
            return about()

    # 과거는 미래 표현보다 먼저 봄 — '지난 해 여름' 이 전망으로 새지 않게
    if PAST_RE.search(query):
        return (
            "지난 날씨는 제가 볼 수 없습니다. 기상청 예보만 다루고 있어서,\n"
            f"*오늘부터 앞으로* 만 알려드릴 수 있습니다. {NO_EMOJI}\n"
            "\n지난 날씨는 기상청에서 직접 보실 수 있어요 — 날짜와 지점을 골라 "
            "일별 기온·강수량을 확인할 수 있습니다.\n"
            f"{PAST_OBS_URL}"
        )
    if TOO_FAR_RE.search(query):
        return (
            "그만큼 먼 날씨는 기상청도 예보하지 않습니다. "
            f"1개월 전망까지가 한계예요. {NO_EMOJI}\n"
            f"\n_`{self_mention()} 다음 달` 로 4주치 확률 전망을 보실 수 있습니다._"
        )
    if OUTLOOK_RE.search(query):
        cleaned = NOISE_RE.sub(" ", OUTLOOK_RE.sub(" ", query)).strip()
        region, _ = resolve_region(cleaned) if cleaned else (NATIONWIDE, "")
        return _outlook_reply(region or NATIONWIDE, query)
    return None


def _city_reply(query: str, start: dt.date, days: int, title: str, now: dt.datetime) -> str | None:
    """시도를 물으면 동네예보로 답함(광역 '부산·울산·경남' 은 부산 값이 아님). 못 채우면 None → 광역."""
    wide = find_wide(query) or next(
        (w for tok in re.split(r"[\s,]+", query) if (w := find_wide(tok))), None)
    if not wide:
        return None
    last = now.date() + dt.timedelta(days=DONG_MAX_DAYS - 1)
    if start > last:
        return None
    if start + dt.timedelta(days=days - 1) <= last:
        reply = _dong_reply(wide[0], wide[1], days, start, today=now.date())
        # NO_EMOJI 가 있으면 거절 답 — 광역으로 넘김
        return None if NO_EMOJI in reply else reply
    if title.startswith("앞으로"):
        # 기간을 안 말했으면 닿는 데까지만 — 일수보다 «부산 값» 이 중요함
        return _dong_reply(wide[0], wide[1], (last - start).days + 1, start, today=now.date())
    return None                        # '이번 주'·'다음 주' 는 기간을 채우는 광역으로


def _find_region(query: str, text: str, topic: str | None, start: dt.date, days: int,
                 now: dt.datetime) -> tuple[Region, str] | str:
    """광역이면 (구역, 바꿔 읽은 안내), 아니면 동 단위로 찾은 답(str)."""
    region, note = resolve_region(query)
    if region is None and topic:
        # 조언 질문은 문장에서 지역을 집어냄 — NOISE 로 지우면 '무등산' 의 '등산' 이 잘림
        region, note = extract_region(text)
        if region is None:
            region, note = NATIONWIDE, ""
    if region is not None:
        return region, note
    hits = search_dong(query, limit=4)
    if len(hits) == 1 or (hits and hits[0].name.replace(" ", "") == query.replace(" ", "")):
        return _dong_reply(hits[0].code, hits[0].full_name, days, start, today=now.date())
    if hits:
        # 단정하지 않고 되물음 — 강릉에도 강남동이 있음
        listed = "\n".join(f"• {h.full_name}" for h in hits)
        return (
            f"*{query}* 로 찾은 곳이 여럿입니다. 하나만 골라 다시 불러 주세요. {NO_EMOJI}\n"
            f"{listed}\n\n_예: {self_mention()} {hits[0].short_name.split()[-1]}_"
        )
    return f"'{query}' 는 제가 아는 지역이 아닙니다. {NO_EMOJI}\n\n{help_text()}"
