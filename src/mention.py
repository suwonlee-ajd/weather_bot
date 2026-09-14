"""`@주간 날씨 부산` 처럼 멘션으로 지역 날씨를 물어보는 봇. (Socket Mode)

Socket Mode 를 쓰는 이유: 인바운드 포트도, 리버스 프록시도, TLS 인증서도, Signing Secret 도
필요 없다. 나가는 WebSocket 연결 하나뿐이라 서버에 이미 떠 있는 다른 서비스의 ingress 를
전혀 건드리지 않는다.

    SLACK_BOT_TOKEN=xoxb-...   (chat:write, files:write, app_mentions:read)
    SLACK_APP_TOKEN=xapp-...   (connections:write)

    python -m src.mention
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import sys
import threading
import time

from .advice import _pick, build_advice, detect_topic, topic_advice
from dataclasses import replace

from .cache import get_or_set
from .config import KST
from .forecast import day_label, range_text
from .logsetup import setup
from .dong import DongError, fetch_dong, find_wide, search_dong
from .outlook import OutlookError, fetch_outlook
from .kma_scrape import (
    NATIONWIDE, REGION_HELP, ScrapeError, _resolve_date, extract_region,
    lines_for_dates, resolve_region, scrape_range,
)

log = logging.getLogger("weather-mention")

MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
CACHE_TTL_SEC = int(os.environ.get("MENTION_CACHE_TTL", "3600"))
# 워크스페이스 커스텀 이모지를 쓰되, 없는 워크스페이스에서는 표준 이모지로 물러선다.
LOADING_EMOJI = os.environ.get("LOADING_EMOJI", "")
LOADING_FALLBACK = ":hourglass_flowing_sand:"
LOADING_PREFERRED = (":loading:", ":loading2:", ":bearloading:")

# 못 한다고 답할 때 / 그렇다고 답할 때 붙이는 표정. 문장 끝에 둔다 —
# 앞에 두면 내용보다 먼저 눈에 띄어 정작 읽어야 할 말을 가린다.
# 사용자가 뭘 잘못해서가 아니라 자료가 없는 경우(수집 실패·예보 없음)에는 붙이지 않는다.
# 유니코드 15.1 ZWJ 시퀀스라 오래된 클라이언트에서는 안 보일 수 있어
# NO_EMOJI / YES_EMOJI 로 갈아끼울 수 있게 해 둔다.
NO_EMOJI = os.environ.get("NO_EMOJI", ":head_shaking_horizontally:")
YES_EMOJI = os.environ.get("YES_EMOJI", ":head_shaking_vertically:")

# 안내문의 예시에 쓰는 자기 멘션. 기동할 때 실제 user_id 로 채운다.
# 하드코딩한 '@봇' 은 이름이 바뀌면 바로 어긋나고, 코드블록 안이라 링크도 안 된다.
_SELF = {"mention": "@날씨 알리미"}


def self_mention() -> str:
    return _SELF["mention"]
# 이 시간 안에 끝나면 로딩 메시지를 띄우지 않는다 (캐시 적중은 0.3초면 끝난다)
SLOW_REPLY_SEC = 2.0

# 하늘상태를 이모지로. 중기예보는 "구름많음", 동네예보는 "구름 많음" 처럼 표기가
# 갈려서 공백을 지우고 맞춘다. 비/눈이 섞인 값이 먼저 걸리도록 순서가 중요하다.
SKY_EMOJI: tuple[tuple[str, str], ...] = (
    ("소나기", ":umbrella_with_rain_drops:"),
    ("비/눈", ":snow_cloud:"),
    ("눈/비", ":snow_cloud:"),
    ("눈", ":snowflake:"),
    ("비", ":umbrella_with_rain_drops:"),
    ("흐림", ":cloud:"),
    ("구름많음", ":partly_sunny:"),
    ("구름조금", ":partly_sunny:"),
    ("맑음", ":sunny:"),
)


def sky_emoji(sky: str | None) -> str:
    """하늘상태 문구를 이모지로. 모르는 값이면 원문을 그대로 둔다."""
    if not sky:
        return ""
    flat = sky.replace(" ", "")
    for keyword, emoji in SKY_EMOJI:
        if keyword in flat:
            return emoji
    return sky

# 첫 인사만 돌려 쓴다. 아래 기능 안내는 고정이다 — 무엇을 할 수 있는지가
# 날마다 달리 읽히면 곤란하다.
HELLO_LINES = (
    "안녕하세요, 날씨 알리미입니다. :sunny:",
    "반갑습니다, 날씨 알리미예요. :sunny:",
    "안녕하세요. 날씨를 전해드리는 날씨 알리미입니다. :sunny:",
)


def about() -> str:
    me = self_mention()
    return (
        f"{_pick(HELLO_LINES, dt.datetime.now(tz=KST).date())}\n"
        "기상청 예보를 받아 매주 월요일 아침에 이번 주 날씨를 올리고,\n"
        "이렇게 불러 주시면 지역별 날씨도 바로 알려드려요.\n\n"
        "예를 들면 이렇게요 —\n"
        f"• {me} 수도권 — 앞으로 7일\n"
        f"• {me} 내일 부산 — 하루만\n"
        f"• {me} 역삼동 — 동네예보\n\n"
        "_전국 어느 동이든 찾아드립니다. 자세한 사용법은 `도움말` 이라고 불러 주세요._"
    )

def help_text() -> str:
    me = self_mention()
    return (
        "지역을 함께 적어 주세요.\n"
        f"• *광역* (7일) — {REGION_HELP}\n"
        "   중부 · 남부 · 영남 · 호남 · 충청 · 영동 · 영서 같은 말도 알아듣습니다.\n"
        "• *동네예보* (오늘~5일) — 부산 · 역삼동 · 봉담 처럼 시도/동 이름\n"
        f"   행정동코드 10자리를 직접 적어도 됩니다. 예: {me} 1168064000\n"
        "\n_광역은 최대 10일, 동 단위는 3일까지입니다. 그보다 먼 날은 기상청도 예보하지 않습니다._"
    )


NEXT_WEEK_RE = re.compile(r"다음\s*주|담주|next", re.I)
THIS_WEEK_RE = re.compile(r"이번\s*주|금주")
# 인사·감사·잡담. 지역으로 오해해 "아는 지역이 아닙니다" 라고 답하면 무안하다.
THANKS_RE = re.compile(r"고마|감사|땡큐|thank|수고", re.I)
GREETING_RE = re.compile(
    r"안녕|하이|헬로|hello|hi\b|반가|좋은\s*아침|굿모닝|고마|감사|땡큐|thank|수고"
    r"|뭐해|누구|정체|소개|도움말|help|사용법|어떻게\s*써|잘\s*자|바이|잘\s*있어",
    re.I,
)
# 10일 예보 너머. 1개월 전망(주 단위 확률)으로 답할 수 있는 범위다.
OUTLOOK_RE = re.compile(
    r"다음\s*달|한\s*달|1개월|한달|[0-9]+\s*주\s*뒤|앞으로\s*한\s*달"
    r"|(올|이번|내년|다음)?\s*(봄|여름|가을|겨울)"
    r"|장기\s*예보|장기\s*전망|중장기|[0-9]{1,2}\s*월\s*(날씨|기온|예보)",
    re.I,
)
# 1개월 전망으로도 못 다루는 먼 미래. 확률조차 없다.
TOO_FAR_RE = re.compile(
    r"[2-9]\s*개월|[0-9]{2,}\s*개월|내년|재작년|분기"
)
# 과거. 계절 표현과 겹칠 수 있어('지난 해 여름') 미래 분기보다 먼저 본다.
# 과거 관측 안내 링크. /obs-climate/ 경로는 여기로 리다이렉트되므로 최종 주소를 쓴다.
PAST_OBS_URL = "https://www.weather.go.kr/w/weather/land/past-obs/obs-by-day.do"
PAST_RE = re.compile(
    r"어제|그제|그저께|엊그제|작년|재작년|과거|예전|옛날"
    r"|지난\s*(해|주|달|여름|겨울|봄|가을|주말)|저번\s*(주|달|해)"
    r"|[0-9]{4}\s*년\s*(\d{1,2}\s*월)?\s*(날씨|기온)"
    r"|(했|였|았)어|었나|였나|이었"
)
TODAY_RE = re.compile(r"오늘|지금|현재|금일")
TOMORROW_RE = re.compile(r"내일|명일|모레")
WEEKEND_RE = re.compile(r"주말|토일|토요일|일요일")
# "9월 18일", "18일", "9/18", "09-18" 처럼 날짜를 콕 집어 묻는 경우.
# 월이 없으면 오늘 기준 가까운 쪽으로 해석한다(_resolve_date).
EXPLICIT_DATE_RE = re.compile(
    r"(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일(?!\s*간)"      # 9월 18일 / 18일
    r"|(?:(\d{1,2})\s*[/-]\s*(\d{1,2}))(?!\d)"            # 9/18 · 09-18
)
# 지역 해석 전에 걷어낼 말. 조언 표현("뭐 입지", "우산 필요해")이 남으면
# 지역으로 오해해 "아는 지역이 아닙니다" 로 빠진다.
NOISE_RE = re.compile(
    r"날씨|알려줘|어때|어떄|알려|좀|주세요|해줘|괜찮|될까|갈만|갈\s*만|필요"
    r"|뭐\s*입|입을|입지|입어|옷차림|복장|우산|등산|산행|캠핑|나들이|소풍|피크닉"
    r"|운동|러닝|자전거|골프|낚시|산책|빨래|세탁|건조|세차|야외"
    r"|[?.,!~]",
    re.I,
)
FORWARD_DAYS = 7
# 캐시에 담을 구간. 광역 예보의 상한(오늘~10일)이라 어떤 질문이든 이 안에 든다.
MAX_FORECAST_DAYS = 10
# 동네예보(시도·동 단위)가 닿는 범위. 그 너머는 광역 구역만 답할 수 있다.
DONG_MAX_DAYS = 5


def _dong_advice(summary) -> list:
    """동네예보 일별 요약(날짜, 최저, 최고, 하늘, 강수)을 조언 입력 형태로 맞춘다."""
    from types import SimpleNamespace

    days = [
        SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo, tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)
        for d, lo, hi, sky, pop in summary
    ]
    return build_advice(days)


def _dong_reply(zone: str, name: str, days: int = 4, start: dt.date | None = None) -> str:
    """동·시도 단위 동네예보. 닿는 날까지만 보여주고, 더 필요하면 광역으로 안내한다."""
    try:
        fc = fetch_dong(zone, name)
    except DongError as exc:
        log.warning("동네예보 실패: %s", exc)
        return (
            f"*{name}* 동네예보를 가져오지 못했습니다.\n"
            f"광역 구역으로는 7일치를 볼 수 있습니다 — 예: {self_mention()} 수도권\n\n{help_text()}"
        )

    summary = fc.daily_summary()
    if start is not None:
        summary = [row for row in summary if row[0] >= start][:max(1, days)]
        if not summary:
            return (
                f"*{name}* 동네예보는 오늘부터 {DONG_MAX_DAYS}일까지만 제공됩니다. {NO_EMOJI}\n"
                f"그 이후는 광역 구역으로 불러 주세요. 예: {self_mention()} 수도권"
            )
    else:
        summary = summary[:max(1, days)]
    scope = (day_label(summary[0][0]) if len(summary) == 1
             else f"{day_label(summary[0][0])} ~ {day_label(summary[-1][0])}")
    lines = [f"*{fc.name}* 동네예보 ({scope})"]
    coldest = min(summary, key=lambda r: r[1])[0] if summary else None
    hottest = max(summary, key=lambda r: r[2])[0] if summary else None
    for date, lo, hi, sky, pop in summary:
        temp = f"{lo:.0f}~{hi:.0f}℃"
        if date in (coldest, hottest):
            temp = f"*{temp}*"
        lines.append(
            f"• `{day_label(date)}` {temp} · {sky_emoji(sky)}"
            + (f" · `{pop}%`" if pop else "")
        )
    tips = _dong_advice(summary)
    if tips:
        lines.append("")
        lines += [f"{t.emoji} {t.text}" for t in tips]
    lines.append(f"_기상청 동네예보 · {fc.issued} 발표_")
    lines.append(f"_더 먼 날이 필요하시면 광역 구역으로 불러 주세요 (최대 10일). "
                 f"예: {self_mention()} 수도권_")
    return "\n".join(lines)


def resolve_loading_emoji(client) -> str:
    """쓸 수 있는 로딩 이모지를 고른다.

    커스텀 이모지는 워크스페이스마다 다르다. emoji:read 가 있으면 실제로 있는지
    확인하고, 없거나 스코프가 빠졌으면 표준 이모지로 물러선다 — 없는 코드를 쓰면
    슬랙에 `:loading:` 이 날것으로 노출된다.
    """
    if LOADING_EMOJI:
        return LOADING_EMOJI
    try:
        available = client.emoji_list()["emoji"]
    except Exception:
        log.info("커스텀 이모지를 확인할 수 없어 표준 이모지를 씁니다 (emoji:read 필요)")
        return LOADING_FALLBACK
    for name in LOADING_PREFERRED:
        if name.strip(":") in available:
            return name
    return LOADING_FALLBACK


def _outlook_reply(region, query: str) -> str:
    """1개월 전망. 값이 아니라 확률이라는 점을 분명히 해 둔다."""
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


def _explicit_date(query: str, today: dt.date) -> dt.date | None:
    """"9월 18일" / "18일" / "9/18" 을 실제 날짜로. 없으면 None.

    월을 안 적었으면 오늘 기준 가장 가까운 같은 일(日)로 본다 — 월말에 "2일"을
    물으면 다음 달이다. _resolve_date 가 그 계산을 이미 갖고 있다.

    예보가 없는 과거·먼 미래는 여기서 걸러내지 않는다. 뒤에서 자료가 없으면
    "예보 없음" 으로 답하므로, 날짜 해석만 하고 판단은 그쪽에 맡긴다.
    """
    m = EXPLICIT_DATE_RE.search(query)
    if not m:
        return None
    month_s, day_s, slash_m, slash_d = m.groups()
    if slash_m and slash_d:
        month, day = int(slash_m), int(slash_d)
    else:
        month, day = (int(month_s) if month_s else None), int(day_s)
    if not 1 <= day <= 31:
        return None
    if month is None:
        return _resolve_date(day, today)          # 가까운 쪽으로
    if not 1 <= month <= 12:
        return None
    # 월까지 적었으면 그 월로. 해가 바뀌는 경계(12월에 "1월 5일")를 살핀다.
    for year in (today.year, today.year + 1):
        try:
            cand = dt.date(year, month, day)
        except ValueError:
            return None
        if cand >= today - dt.timedelta(days=1):
            return cand
    return None


def build_reply(text: str, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(tz=KST)
    query = MENTION_RE.sub(" ", text).strip()

    # 멘션으로 물을 때 원하는 건 달력상 '이번 주'가 아니라 **앞으로의 날씨**다.
    # 주 중간에 "이번 주"로 잡으면 이미 지난 요일 때문에 이틀치만 나온다.
    # 그래서 기본은 오늘부터 7일. "이번 주"/"다음 주"를 명시하면 그 주 월~일로 맞춘다.
    # 지역 이름이 섞여 있지 않은 순수한 인사·잡담이면 자기소개로 답한다.
    # ('부산 안녕' 처럼 지역이 함께 오면 날씨를 보여주는 쪽이 맞다)
    if GREETING_RE.search(query):
        stripped = GREETING_RE.sub(" ", query)
        stripped = NOISE_RE.sub(" ", stripped).strip()
        if not stripped or resolve_region(stripped)[0] is None:
            if re.search(r"도움말|help|사용법|어떻게\s*써", query, re.I):
                return help_text()
            # 감사 인사에 자기소개 전문을 다시 보내면 과하다
            if THANKS_RE.search(query):
                return f"천만에요. 날씨 궁금하시면 언제든 불러 주세요. {YES_EMOJI}"
            return about()

    # 과거는 예보가 아니라 관측이라 이 봇이 다루는 자료에 없다. 계절 표현과 겹치므로
    # ('지난 해 여름') 미래 분기보다 먼저 본다 — 아니면 과거 질문에 전망이 나간다.
    if PAST_RE.search(query):
        return (
            "지난 날씨는 제가 볼 수 없습니다. 기상청 예보만 다루고 있어서,\n"
            f"*오늘부터 앞으로* 만 알려드릴 수 있습니다. {NO_EMOJI}\n"
            "\n지난 날씨는 기상청에서 직접 보실 수 있어요 — 날짜와 지점을 골라 "
            "일별 기온·강수량을 확인할 수 있습니다.\n"
            f"{PAST_OBS_URL}"
        )

    # 10일 예보 너머. 1개월 전망(주 단위 확률)으로 답할 수 있으면 답한다.
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

    days = FORWARD_DAYS
    monday = now.date() - dt.timedelta(days=now.weekday())
    weekend = bool(WEEKEND_RE.search(query))
    explicit = _explicit_date(query, now.date())
    if explicit is not None:
        start, title, days = explicit, f"{explicit:%-m월 %-d일}", 1
    elif NEXT_WEEK_RE.search(query):
        start, title = monday + dt.timedelta(weeks=1), "다음 주"
    elif THIS_WEEK_RE.search(query):
        start, title = monday, "이번 주"
    elif TODAY_RE.search(query):
        start, title, days = now.date(), "오늘", 1
    elif TOMORROW_RE.search(query):
        ahead = 2 if "모레" in query else 1
        start, title, days = now.date() + dt.timedelta(days=ahead), \
            ("모레" if ahead == 2 else "내일"), 1
    else:
        start, title = now.date(), f"앞으로 {FORWARD_DAYS}일"

    # 탐지에 쓴 바로 그 패턴으로 지운다 — 목록이 두 군데로 갈라지지 않게.
    for pattern in (EXPLICIT_DATE_RE, NEXT_WEEK_RE, THIS_WEEK_RE,
                    TODAY_RE, TOMORROW_RE, NOISE_RE):
        query = pattern.sub(" ", query)
    query = query.strip()

    # '주말 등산 괜찮아?' 는 토·일만 궁금한 것이다. 한 주 전체를 보여주면 답이 묻힌다.
    if weekend:
        saturday = monday + dt.timedelta(days=5)
        if saturday < now.date():          # 이미 지난 주말이면 다음 주말
            saturday += dt.timedelta(days=7)
        start, days, title = saturday, 2, "주말"

    topic = detect_topic(text)

    # '부산' 처럼 시도 하나를 물었으면 그 시도의 동네예보를 보여준다.
    # 광역 구역(부산·울산·경남)으로 답하면 기온이 경남내륙까지 아우른 분포라
    # 부산만 궁금한 사람에게는 남의 동네 숫자가 섞인다.
    #
    # 동네예보는 5일까지라, 그보다 먼 날을 물었으면 광역으로 넘긴다 —
    # 좁게 답하려다 아예 답을 못 하는 것보다 낫다.
    # 문장으로 물어도 도시명을 집어낸다 ("내일 부산 출장가는데 뭐 입지").
    # query 는 기간·잡음을 지운 뒤라 'X 날씨' 는 걸리지만 긴 문장은 안 걸린다.
    wide = find_wide(query) or next(
        (w for tok in re.split(r"[\s,]+", query) if (w := find_wide(tok))), None)
    if wide:
        last = now.date() + dt.timedelta(days=DONG_MAX_DAYS - 1)
        if start > last:
            pass                      # 동네예보가 닿지 않는 날 — 아래 광역으로
        elif start + dt.timedelta(days=days - 1) <= last:
            reply = _dong_reply(wide[0], wide[1], days, start)
            # 예보 끝자락은 값이 모자라 거절로 끝난다(조각난 날은 버린다).
            # 광역이라면 답할 수 있으므로 여기서 막지 않고 넘긴다.
            if NO_EMOJI not in reply:
                return reply
        elif title.startswith("앞으로"):
            # 기간을 따로 말하지 않았다면 며칠인지보다 «부산 값» 인지가 중요하다.
            # 닿는 데까지 좁게 답하고, 더 필요하면 광역으로 안내한다.
            return _dong_reply(wide[0], wide[1], (last - start).days + 1, start)
        # '이번 주'·'다음 주' 처럼 기간을 콕 집어 물었으면 그 기간을 채울 수 있는
        # 광역으로 간다. 이레를 물었는데 사흘만 주는 것이 더 불친절하다.

    region, note = resolve_region(query)
    if region is None and topic:
        # 조언을 물으면 문장이 길고 지역이 섞여 있다("주말 무등산 등산 괜찮아?").
        # 지우기로는 '무등산' 의 '등산' 까지 잘려 나가므로, 문장에서 지역을 집어낸다.
        region, note = extract_region(text)
        if region is None:
            region, note = NATIONWIDE, ""
    if region is None:
        # 광역에 없으면 동 단위인지 본다 (역삼동, 판교동, 행정동코드 …)
        hits = search_dong(query, limit=4)
        if len(hits) == 1 or (hits and hits[0].name.replace(' ', '') == query.replace(' ', '')):
            return _dong_reply(hits[0].code, hits[0].full_name, days, start)
        if hits:
            # 어느 곳인지 단정하지 않고 되묻는다 — 강릉에도 강남동이 있다
            listed = "\n".join(f"• {h.full_name}" for h in hits)
            return (
                f"*{query}* 로 찾은 곳이 여럿입니다. 하나만 골라 다시 불러 주세요. {NO_EMOJI}\n"
                f"{listed}\n\n_예: {self_mention()} {hits[0].short_name.split()[-1]}_"
            )
        return f"'{query}' 는 제가 아는 지역이 아닙니다. {NO_EMOJI}\n\n{help_text()}"

    # 캐시는 지역 하나당 한 항목이다. 그러려면 담기는 값이 «물어본 기간» 과
    # 무관해야 한다 — scrape_range 는 window 로 잘라 돌려주므로, 자르기 전의
    # 넓은 구간(오늘부터 열흘)을 캐시하고 좁히는 일은 아래에서 한다.
    # 잘린 값을 캐시하면 «다음 주» 를 먼저 물은 뒤 «앞으로 7일» 을 물었을 때
    # 오늘·내일이 빠진 채로 나온다.
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
    # 기상청 중기예보는 오늘부터 열흘까지다. 주 초에 «다음 주» 를 물으면 그
    # 한계에 사흘만 걸친다 — 머리글에 이레라고 적어 놓고 사흘만 보여주면
    # 봇이 잘라먹은 것처럼 읽힌다. 실제로 있는 날까지만 적는다.
    have = max(scrape.days) if scrape.days else end
    shown_end = min(end, have)
    span_text = (day_label(start) if start == shown_end
                 else f"{day_label(start)} ~ {day_label(shown_end)}")
    lines = [f"*{region.label}* {title} ({span_text})"]
    if note:
        lines.append(f"_{note}_")
    # 그 주에서 가장 춥고 더운 날만 굵게 한다. 전부 굵게 하면 강조가 사라진다.
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

    # 물어본 기간을 다 채우지 못했으면 왜 짧은지 밝힌다. 말없이 빠뜨리면
    # 봇이 잘라먹은 것으로 읽힌다.
    if shown_end < end:
        lines.append(f"_{day_label(shown_end + dt.timedelta(days=1))} 이후는 "
                     f"아직 예보가 작성되지 않았습니다 {NO_EMOJI}_")

    shown = [scrape.days[d] for d in sorted(scrape.days)]
    # 조언은 화면에 보인 날만 근거로 삼는다. 캐시는 7일을 들고 있어서, 하루만 물었는데
    # 사흘 뒤 일교차를 말하면 물은 것과 다른 답이 된다.
    window = {start + dt.timedelta(days=i) for i in range(days)}
    scoped = [d for d in shown if d.date in window]
    narrative_lines = [line for n in scrape.narratives for line in n.lines]
    # 물어본 것에 먼저 답하고, 그 밖에 짚을 것이 있으면 덧붙인다.
    tips = topic_advice(topic, scoped) if topic else []
    # 겹침은 이모지로 가린다 — 문구가 날짜마다 달라지므로(advice.py _pick)
    # 문장을 비교하면 «우산 챙기세요» 와 «우산 없이 나서면» 이 서로 다른 말로
    # 보여 우산 조언이 두 줄 나간다. 같은 이모지면 같은 종류의 조언이다.
    seen = {x.emoji for x in tips}
    tips += [t for t in build_advice(scoped, narrative_lines)
             if t.emoji not in seen][: 3 - len(tips)]
    if tips:
        lines.append("")
        lines += [f"{t.emoji} {t.text}" for t in tips]

    for narrative in sorted(scrape.narratives, key=lambda n: 0 if "통보문" in n.title else 1):
        # 물어본 날짜의 줄만 고른다. 앞에서 2줄을 그냥 자르면 «모레» 를 물어도
        # «(오늘, 12일)» 이 붙어 질문과 어긋난 답이 된다.
        picked = lines_for_dates(narrative.lines, now.date(), window)
        for line in picked[:2]:
            lines.append(f"> {line}")
        stamp = f"{narrative.issued_at:%m/%d %H시}" if narrative.issued_at else "발표시각 미상"
        lines.append(f"_{narrative.title} · {stamp} 발표_")

    return "\n".join(lines)


def main() -> int:
    setup("weather-mention")

    bot_token, app_token = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_APP_TOKEN")
    missing = [k for k, v in (("SLACK_BOT_TOKEN", bot_token), ("SLACK_APP_TOKEN", app_token)) if not v]
    if missing:
        print(
            f"{', '.join(missing)} 가 필요합니다.\n"
            "SLACK_APP_TOKEN 은 Slack 앱 > Basic Information > App-Level Tokens 에서\n"
            "connections:write 스코프로 발급한 xapp- 토큰입니다.",
            file=sys.stderr,
        )
        return 1

    from slack_bolt import App
    from slack_sdk.errors import SlackApiError
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    # Socket Mode 는 서명 검증이 필요 없다 (Slack 과의 인증된 WebSocket 위로만 이벤트가 온다)
    app = App(token=bot_token)
    loading = resolve_loading_emoji(app.client)
    log.info("로딩 표시: %s", loading)

    # 안내문 예시가 실제 봇을 가리키게 한다. <@U…> 는 슬랙이 표시 이름으로 렌더링하므로
    # 콘솔에서 이름을 바꿔도 문구를 고칠 필요가 없다.
    try:
        _SELF["mention"] = f"<@{app.client.auth_test()['user_id']}>"
    except Exception:
        log.info("봇 user_id 를 얻지 못해 기본 표기를 씁니다")

    @app.event("app_mention")
    def on_mention(event, say, client, logger):
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        channel = event["channel"]
        # 실패했을 때 재현할 수 있어야 한다 — 질문 원문과 어느 스레드였는지를 함께 남긴다.
        ctx = f"user={event.get('user')} ch={channel} ts={thread_ts}"
        started = time.monotonic()
        logger.info("멘션 수신 %s query=%r", ctx, text[:200])

        # 동 단위 첫 조회는 전국 목록을 받느라 20초 가까이 걸린다. 그동안 아무 반응이
        # 없으면 죽은 줄 안다. 다만 캐시가 맞으면 0.3초라, 느릴 때만 띄우고 지운다.
        holder = {"ts": None}
        def show_loading():
            try:
                res = client.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"{loading} 기상청 자료를 받아오는 중이에요…",
                )
                holder["ts"] = res["ts"]
            except Exception:
                logger.debug("로딩 메시지 실패", exc_info=True)

        timer = threading.Timer(SLOW_REPLY_SEC, show_loading)
        timer.start()
        try:
            reply = build_reply(text)
            logger.info("응답 완료 %s %.1fs %d자", ctx, time.monotonic() - started, len(reply))
        except Exception:
            # 트레이스백만으로는 무엇을 물었는지 알 수 없다. 질문을 같은 줄에 붙인다.
            logger.exception("응답 생성 실패 %s query=%r", ctx, text[:200])
            reply = "예보를 정리하는 중에 문제가 생겼습니다. 잠시 뒤 다시 불러 주세요."
        finally:
            timer.cancel()

        # 로딩 메시지를 띄웠으면 그 자리를 결과로 바꾼다 — 채널에 흔적을 남기지 않는다
        if holder["ts"]:
            try:
                client.chat_update(channel=channel, ts=holder["ts"], text=reply)
                return
            except Exception:
                logger.debug("로딩 메시지 교체 실패 — 새 메시지로 보냅니다", exc_info=True)
        try:
            say(text=reply, thread_ts=thread_ts)
        except SlackApiError as exc:
            # not_in_channel / missing_scope 는 코드가 아니라 슬랙 설정 문제다.
            # 원인 코드를 그대로 남겨야 콘솔에서 무엇을 고칠지 바로 안다.
            logger.error("슬랙 전송 실패 %s error=%s", ctx, exc.response.get("error"))

    @app.event("message")
    def ignore_messages(logger):
        """app_mention 과 함께 오는 message 이벤트를 조용히 흘려보낸다."""

    log.info("Socket Mode 연결 시작 (캐시 TTL %d초)", CACHE_TTL_SEC)
    SocketModeHandler(app, app_token).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
