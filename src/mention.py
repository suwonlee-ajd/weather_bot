"""`@주간 날씨 부산` 처럼 멘션으로 지역 날씨를 물어보는 봇. (Socket Mode)

Socket Mode 를 씀 — 나가는 WebSocket 연결 하나뿐이라 인바운드 포트·리버스 프록시·TLS 인증서·
Signing Secret 이 필요 없고, 서버에 이미 떠 있는 다른 서비스의 ingress 를 건드리지 않음.

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
from dataclasses import dataclass, replace

from .cache import get_or_set
from .config import KST
from .forecast import day_label, range_text, short_date
from .logsetup import setup
from .dong import DongError, fetch_dong, find_wide, search_dong
from .foliage import KMA_PAGE as KMA_FOLIAGE_PAGE
from .foliage import (
    CRITERIA_TEXT, KINDS, NOT_STARTED_TEXT, OUTLOOK_SOURCE, SEASON_TEXT, STAGES,
    FoliageError, Snapshot, fetch_snapshot, in_season, next_season,
)
from .mountains import MOUNTAINS, Mountain, find_mountain, in_region, in_zone, unknown_mountain
from .outlook import OutlookError, fetch_outlook
from .paragraph import bold
from .render_foliage import gap_text, observed_line, sources, week_changes, week_line
from .render_foliage import render_png as render_foliage_png
from .kma_scrape import (
    NATIONWIDE, REGION_HELP, ScrapeError, _resolve_date, extract_region,
    lines_for_dates, resolve_region, scrape_range,
)

log = logging.getLogger("weather-mention")

MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
CACHE_TTL_SEC = int(os.environ.get("MENTION_CACHE_TTL", "3600"))
# 워크스페이스 커스텀 이모지를 쓰되, 없는 워크스페이스에서는 표준 이모지로 물러섬.
LOADING_EMOJI = os.environ.get("LOADING_EMOJI", "")
LOADING_FALLBACK = ":hourglass_flowing_sand:"
LOADING_PREFERRED = (":loading:", ":loading2:", ":bearloading:")

# 못 한다고 답할 때 / 그렇다고 답할 때 붙이는 표정. 문장 끝에 둠 —
# 앞에 두면 내용보다 먼저 눈에 띄어 정작 읽어야 할 말을 가림.
# 자료가 없는 경우(수집 실패·예보 없음)에는 붙이지 않음 — 사용자가 잘못한 게 아님.
# NO_EMOJI / YES_EMOJI 로 갈아끼울 수 있음 — 유니코드 15.1 ZWJ 시퀀스라
# 오래된 클라이언트에서는 안 보일 수 있음.
NO_EMOJI = os.environ.get("NO_EMOJI", ":head_shaking_horizontally:")
YES_EMOJI = os.environ.get("YES_EMOJI", ":head_shaking_vertically:")

# 안내문의 예시에 쓰는 자기 멘션. 기동할 때 실제 user_id 로 채움.
# 하드코딩한 '@봇' 은 이름이 바뀌면 바로 어긋나고, 코드블록 안이라 링크도 안 됨.
_SELF = {"mention": "@날씨 알리미"}


def self_mention() -> str:
    return _SELF["mention"]
# 이 시간 안에 끝나면 로딩 메시지를 띄우지 않음 (캐시 적중은 0.3초면 끝남)
SLOW_REPLY_SEC = 2.0

# 하늘상태를 이모지로. 공백을 지우고 견줌 — 중기예보 "구름많음", 동네예보 "구름 많음" 처럼
# 표기가 갈림. 순서가 중요함 — 비/눈이 섞인 값이 먼저 걸려야 함.
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
    """하늘상태 문구를 이모지로. 모르는 값이면 원문을 그대로 둠."""
    if not sky:
        return ""
    flat = sky.replace(" ", "")
    for keyword, emoji in SKY_EMOJI:
        if keyword in flat:
            return emoji
    return sky

# 첫 인사만 돌려 씀. 아래 기능 안내는 고정임 — 무엇을 할 수 있는지가
# 날마다 달리 읽히면 곤란함.
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
        f"• *동네예보* (오늘~{DONG_MAX_DAYS}일) — 부산 · 역삼동 · 봉담 처럼 시도/동 이름\n"
        f"   행정동코드 10자리를 직접 적어도 됩니다. 예: {me} 1168064000\n"
        "• *산* — 설악산 · 주말 지리산 등산 처럼 21개 명산 이름 (산 아래 마을 동네예보)\n"
        "• *단풍* (9월 둘째 주 ~ 11월 둘째 주) — 단풍 · 설악산 단풍 · 주말 내장산 단풍\n"
        "   이 기간에는 지역 날씨에도 그 지역 산의 단풍을 한 줄 붙입니다.\n"
        f"\n_광역은 최대 {MAX_FORECAST_DAYS}일, 동 단위는 {DONG_MAX_DAYS}일까지입니다. "
        "그보다 먼 날은 기상청도 예보하지 않습니다._"
    )


NEXT_WEEK_RE = re.compile(r"다음\s*주|담주|next", re.I)
THIS_WEEK_RE = re.compile(r"이번\s*주|금주")
# 인사·감사·잡담. 지역으로 오해해 "아는 지역이 아닙니다" 라고 답하면 무안함.
THANKS_RE = re.compile(r"고마|감사|땡큐|thank|수고", re.I)
GREETING_RE = re.compile(
    r"안녕|하이|헬로|hello|hi\b|반가|좋은\s*아침|굿모닝|고마|감사|땡큐|thank|수고"
    r"|뭐해|누구|정체|소개|도움말|help|사용법|어떻게\s*써|잘\s*자|바이|잘\s*있어",
    re.I,
)
# 10일 예보 너머. 1개월 전망(주 단위 확률)으로 답할 수 있는 범위.
OUTLOOK_RE = re.compile(
    r"다음\s*달|한\s*달|1개월|한달|[0-9]+\s*주\s*뒤|앞으로\s*한\s*달"
    r"|(올|이번|내년|다음)?\s*(봄|여름|가을|겨울)"
    r"|장기\s*예보|장기\s*전망|중장기|[0-9]{1,2}\s*월\s*(날씨|기온|예보)",
    re.I,
)
# 1개월 전망으로도 못 다루는 먼 미래. 확률조차 없음.
TOO_FAR_RE = re.compile(
    r"[2-9]\s*개월|[0-9]{2,}\s*개월|내년|재작년|분기"
)
# 과거. 미래 분기보다 먼저 봄 — 계절 표현과 겹칠 수 있음('지난 해 여름').
# 과거 관측 안내 링크. 최종 주소를 씀 — /obs-climate/ 경로는 여기로 리다이렉트됨.
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
# 월이 없으면 오늘 기준 가까운 쪽으로 해석함(_resolve_date).
#
# 뒤에 붙는 요일 표기 "(금)" · "(금요일)" 까지 한 덩어리로 삼음 — 요일만 남으면 지역 해석이
# 그 찌꺼기를 지역 이름으로 읽어 «역삼동 9/18(금)» 이 "아는 지역이 아닙니다" 로 빠짐.
# 봇의 답(«09/16(수)» 형식)을 복사해 다시 묻는 사람이 많음. 날짜 해석은 요일이 있든 없든 같음.
_WEEKDAY_SUFFIX = r"(?:\s*[(（]\s*[월화수목금토일](?:요일)?\s*[)）])?"
EXPLICIT_DATE_RE = re.compile(
    r"(?:"
    r"(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일(?!\s*간)"      # 9월 18일 / 18일
    r"|(?:(\d{1,2})\s*[/-]\s*(\d{1,2}))(?!\d)"            # 9/18 · 09-18
    r")" + _WEEKDAY_SUFFIX                                  # 양쪽 다 요일을 달 수 있음
)
# 지역 해석 전에 걷어낼 말. 조언 표현("뭐 입지", "우산 필요해")이 남으면
# 지역으로 오해해 "아는 지역이 아닙니다" 로 빠짐.
NOISE_RE = re.compile(
    r"날씨|알려줘|어때|어떄|알려|좀|주세요|해줘|괜찮|될까|갈만|갈\s*만|필요"
    r"|뭐\s*입|입을|입지|입어|옷차림|복장|우산|등산|산행|캠핑|나들이|소풍|피크닉"
    r"|운동|러닝|자전거|골프|낚시|산책|빨래|세탁|건조|세차|야외"
    r"|[?.,!~]",
    re.I,
)
FORWARD_DAYS = 7
# 캐시에 담을 구간. 광역 예보의 상한(오늘~10일)이라 어떤 질문이든 이 안에 듦.
MAX_FORECAST_DAYS = 10
# 동네예보(시도·동 단위)가 닿는 범위. 그 너머는 광역 구역만 답할 수 있음.
DONG_MAX_DAYS = 5


def _dong_advice(summary, region: str = "") -> list:
    """동네예보 일별 요약(날짜, 최저, 최고, 하늘, 강수)을 조언 입력 형태로 맞춤."""
    from types import SimpleNamespace

    days = [
        SimpleNamespace(date=d, tmin_lo=lo, tmin_hi=lo, tmax_lo=hi, tmax_hi=hi, sky=sky, pop=pop)
        for d, lo, hi, sky, pop in summary
    ]
    return build_advice(days, region=region)


def _dong_reply(zone: str, name: str, days: int = 4, start: dt.date | None = None,
                *, quiet: bool = False, today: dt.date | None = None) -> str:
    """동·시도 단위 동네예보. 닿는 날까지만 보여주고, 더 필요하면 광역으로 안내함.

    quiet 이면 실패하거나 그날 예보가 없을 때 안내문 대신 빈 문자열 — 다른 답(산 단풍)
    뒤에 덧붙일 때 도움말 전문이 끼어들지 않게.
    today 를 주면 단풍철에 그 동네 산의 단풍 한 줄을 붙임 — 예보를 보여 줬을 때만,
    보여 준 날짜 범위로.
    """
    try:
        fc = fetch_dong(zone, name)
    except DongError as exc:
        log.warning("동네예보 실패: %s", exc)
        if quiet:
            return ""
        return (
            f"*{name}* 동네예보를 가져오지 못했습니다.\n"
            f"광역 구역으로는 7일치를 볼 수 있습니다 — 예: {self_mention()} 수도권\n\n{help_text()}"
        )

    summary = fc.daily_summary()
    if start is not None:
        summary = [row for row in summary if row[0] >= start][:max(1, days)]
        if not summary:
            if quiet:
                return ""
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
    tips = _dong_advice(summary, fc.name)
    if tips:
        lines.append("")
        lines += [f"{t.emoji} {t.text}" for t in tips]
    lines.append(f"_기상청 동네예보 · {fc.issued} 발표_")
    # 광역 안내는 «닿는 데까지 왔을 때» 만 함. 하루치 답에서는 쓸모없이 두 줄 본문의
    # 절반을 차지하고, 같은 꼬리말 탓에 다른 지역을 물은 두 답이 같은 메시지로 읽힘.
    if len(summary) >= DONG_MAX_DAYS:
        lines.append(f"_더 먼 날이 필요하시면 광역 구역으로 불러 주세요 (최대 10일). "
                     f"예: {self_mention()} 수도권_")
    if today is not None:
        lines += _foliage_note(in_zone(zone), summary[0][0], summary[-1][0], today)
    return "\n".join(lines)


def resolve_loading_emoji(client) -> str:
    """쓸 수 있는 로딩 이모지를 고름.

    emoji:read 로 실제로 있는지 확인하고, 없거나 스코프가 빠졌으면 표준 이모지로 물러섬.
    커스텀 이모지는 워크스페이스마다 달라서, 없는 코드를 쓰면 슬랙에 `:loading:` 이 날것으로
    노출됨.
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


def _explicit_date(query: str, today: dt.date) -> dt.date | None:
    """"9월 18일" / "18일" / "9/18" 을 실제 날짜로. 없으면 None.

    월을 안 적었으면 오늘 기준 가장 가까운 같은 일(日)로 봄 — 월말에 "2일"을
    물으면 다음 달. _resolve_date 가 그 계산을 이미 갖고 있음.

    예보가 없는 과거·먼 미래는 여기서 걸러내지 않음. 뒤에서 자료가 없으면
    "예보 없음" 으로 답하므로, 날짜 해석만 하고 판단은 그쪽에 맡김.
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
    # 월까지 적었으면 그 월로. 해가 바뀌는 경계(12월에 "1월 5일")를 살핌.
    for year in (today.year, today.year + 1):
        try:
            cand = dt.date(year, month, day)
        except ValueError:
            return None
        if cand >= today - dt.timedelta(days=1):
            return cand
    return None


def _period(query: str, now: dt.datetime) -> tuple[dt.date, int, str]:
    """질문에서 기간을 읽음 → (시작일, 일수, 머리글)."""
    today = now.date()
    days = FORWARD_DAYS
    monday = today - dt.timedelta(days=today.weekday())
    explicit = _explicit_date(query, today)
    if explicit is not None:
        start, title, days = explicit, f"{explicit:%-m월 %-d일}", 1
    elif NEXT_WEEK_RE.search(query):
        start, title = monday + dt.timedelta(weeks=1), "다음 주"
    elif THIS_WEEK_RE.search(query):
        start, title = monday, "이번 주"
    elif TODAY_RE.search(query):
        start, title, days = today, "오늘", 1
    elif TOMORROW_RE.search(query):
        ahead = 2 if "모레" in query else 1
        start, title, days = today + dt.timedelta(days=ahead), \
            ("모레" if ahead == 2 else "내일"), 1
    else:
        start, title = today, f"앞으로 {FORWARD_DAYS}일"

    # 주말을 물으면 토·일만 보여줌 — '주말 등산 괜찮아?' 에 한 주 전체를 보여주면 답이 묻힘.
    if WEEKEND_RE.search(query):
        saturday = monday + dt.timedelta(days=5)
        # '다음 주 주말' · '다음주 토요일' 은 다음 주의 토·일, 이미 지난 주말이어도 다음 주말
        if NEXT_WEEK_RE.search(query) or saturday < today:
            saturday += dt.timedelta(days=7)
        start, days, title = saturday, 2, "주말"
    return start, days, title


# --- 단풍 ---------------------------------------------------------------------
# 단풍은 9월 둘째 주 ~ 11월 둘째 주에만 답함(src/foliage.py). 꽃 개화는 다루지 않음.
FOLIAGE_RE = re.compile(r"단풍|물들|물드")
FLOWER_RE = re.compile(
    r"벚꽃|벚나무|봄꽃|꽃\s*구경|꽃\s*놀이|꽃\s*축제|꽃이?\s*피|개화|만개|철쭉|진달래|개나리"
)
FLOWER_URL = "https://www.weather.go.kr/w/forecast/life/seasonal-observation/spring-flower.do"
# 날씨를 묻는 말. 단풍·꽃 말이 섞여 있어도 이게 있으면 날씨 질문으로 봄
# ("꽃구경 가는데 내일 서울 날씨", "단풍 구경 가는데 강원도 날씨 어때").
# 산 이름과 함께면 산 아래 마을 날씨를 붙임. 활동·우산 같은 관심사(advice.TOPICS)는 따로 봄.
WEATHER_ASK_RE = re.compile(r"날씨|기온|춥|추워|덥|더워|바람")
# 산 단풍에 날씨를 붙이는 기간 표현. '지금'·'현재' 와 '10/25' 같은 날짜는 뺌 — 앞은 단풍 상태를
# 묻는 말이고, 뒤는 대개 단풍 날짜를 되묻는 말임 ("설악산 단풍 절정 10/25 맞아?").
TRIP_SPANS = ("주말", "내일", "모레", "이번 주", "다음 주")


@dataclass
class Reply:
    """멘션 답. 단풍 현황을 물으면 지도가 함께 감."""
    text: str
    image: bytes | None = None


def _stage_line(snap: Snapshot, kind: str, name: str, today: dt.date) -> str:
    label = STAGES[KINDS.index(kind) + 1]
    day, observed = snap.when(kind, name)
    if observed and day is None:
        return f"• {label} — *관측* (촬영일은 아직 올라오지 않았습니다)"
    if day is None:
        return f"• {label} — 예상 없음 ({OUTLOOK_SOURCE} 예상에 없는 산입니다)"
    if observed:
        gap = gap_text(snap.predicted(kind, name), day, show_date=True)
        return f"• {label} — *{short_date(day)} 관측*" + (f" · {gap}" if gap else "")
    if day < today:
        return f"• {label} — {short_date(day)} 예상이었지만 아직 관측되지 않았습니다"
    return f"• {label} — {short_date(day)} 예상"


def _mountain_text(snap: Snapshot, m: Mountain, today: dt.date) -> str:
    if snap.status.in_service:
        head = f"*{m.name}* 단풍 — 지금 *{STAGES[snap.stage(m.name)]}* (기상청 관측)"
    else:
        head = f"*{m.name}* 단풍 — {NOT_STARTED_TEXT}"
    return "\n".join([
        head,
        *(_stage_line(snap, kind, m.name, today) for kind in KINDS),
        f"_{sources(snap)} · {CRITERIA_TEXT}_",
    ])


def _overview_text(snap: Snapshot, today: dt.date, unknown: str | None) -> str:
    end = today + dt.timedelta(days=FORWARD_DAYS - 1)
    lines = []
    if unknown:
        lines += [
            f"'{unknown}' 은 기상청이 단풍을 관측하는 {len(MOUNTAINS)}곳에 없습니다. {NO_EMOJI}",
            "_관측하는 곳: " + " · ".join(m.name for m in MOUNTAINS) + "_",
            "",
        ]
    lines += [
        f"*단풍 현황* ({short_date(today)} 기준)",
        f"• 관측 — {observed_line(snap, bold)}",
        f"• 앞으로 7일 — {week_line(snap, today, end, bold, muted=lambda s: s)}",
        f"_{sources(snap)} · 산 이름을 함께 불러 주시면 그 산만 자세히 알려드려요_",
    ]
    return "\n".join(lines)


def _theme(query: str, now: dt.datetime) -> tuple[str, Snapshot | None] | None:
    """단풍·꽃 질문이면 (답, 지도로 그릴 현황), 아니면 None. 지도가 필요 없으면 현황은 None."""
    today = now.date()
    asks_weather = bool(WEATHER_ASK_RE.search(query))
    if FLOWER_RE.search(query) and not FOLIAGE_RE.search(query):
        if asks_weather:
            return None                   # 꽃구경 가는 날의 날씨 — 날씨로 답함
        return (f"꽃 개화 소식은 다루지 않습니다. {NO_EMOJI}\n"
                f"기상청 봄꽃 개화 현황(3월 초~5월 하순)에서 보실 수 있어요 — {FLOWER_URL}"), None
    if not FOLIAGE_RE.search(query):
        return None

    mountain = find_mountain(query)
    # 산이 아니라 지역의 날씨를 물었으면 날씨 질문임 ("단풍 구경 가는데 강원도 날씨 어때")
    if mountain is None and asks_weather and extract_region(query)[0] is not None:
        return None

    if not in_season(today):
        start, _ = next_season(today)
        # 기간은 늘 월요일에 시작함 (9월 둘째 월요일)
        when = (f"올해는 {short_date(start)}(월)부터입니다" if start.year == today.year
                else f"다음은 {start.year}년 {short_date(start)}(월)부터입니다")
        return f"단풍 소식은 *{SEASON_TEXT}* 에만 전해드립니다. {NO_EMOJI}\n_{when}._", None

    try:
        snap = fetch_snapshot(today)
    except FoliageError as exc:
        log.warning("단풍 현황 실패: %s", exc)
        return ("기상청 단풍 현황을 가져오지 못했습니다. 잠시 뒤 다시 불러 주세요.\n"
                f"기상청에서 직접 보실 수 있어요 — {KMA_FOLIAGE_PAGE}"), None

    if mountain is None:
        return _overview_text(snap, today, unknown_mountain(query)), snap

    text = _mountain_text(snap, mountain, today)
    start, days, title = _period(query, now)
    trip = title in TRIP_SPANS
    if trip or asks_weather or detect_topic(query):
        if not trip:
            start, days = today, DONG_MAX_DAYS - 1
        text += f"\n\n{_mountain_weather(mountain, start, days)}"
    return text, None


def _mountain_weather(m: Mountain, start: dt.date, days: int) -> str:
    """산 아래 마을 동네예보. 산 위가 아니라는 것을 밝혀 둠."""
    weather = _dong_reply(m.zone, f"{m.name} 아래 {m.zone_name}", days, start, quiet=True)
    return (f"{weather}\n_산 아래 마을 예보입니다. 산 위는 이보다 춥고 바람이 셉니다._" if weather
            else f"_산 아래 마을 날씨는 가져오지 못했습니다 (동네예보는 오늘부터 {DONG_MAX_DAYS}일까지)._")


def _mountain_reply(m: Mountain, start: dt.date, days: int, title: str, today: dt.date) -> str:
    """단풍 말 없이 산 이름으로 물은 답 ("설악산", "주말 지리산 등산").

    산 아래 마을 예보가 먼저임 — 날씨를 물은 것. 단풍철이면 그 산의 단풍을 덧붙임.
    기간을 콕 집지 않았으면 단풍 갈래의 산 날씨와 같은 기간을 보여줌.
    """
    if title.startswith("앞으로"):
        start, days = today, DONG_MAX_DAYS - 1
    text = _mountain_weather(m, start, days)
    if in_season(today) and (snap := _snapshot_quietly(today)):
        text += f"\n\n{_mountain_text(snap, m, today)}"
    return text


def _snapshot_quietly(today: dt.date) -> Snapshot | None:
    """날씨 답에 덧붙일 단풍 현황. 못 받으면 None — 덤 때문에 날씨 답까지 막지 않음."""
    try:
        return fetch_snapshot(today)
    except FoliageError as exc:            # 점검·형식 변경 — 예상된 실패라 한 줄로
        log.warning("단풍 현황 실패 — 날씨만 답합니다: %s", exc)
    except Exception:
        log.warning("단풍 현황 실패 — 날씨만 답합니다", exc_info=True)
    return None


def _foliage_brief(snap: Snapshot, mountains: tuple[Mountain, ...], start: dt.date, end: dt.date) -> str:
    """물든 산과 그 기간에 예상된 변화. 둘 다 없으면 빈 문자열.

    전국은 단풍 현황 답과 같은 요약을 씀 — 산마다 적으면 스무 곳이 넘음.
    """
    if len(mountains) == len(MOUNTAINS):
        parts = []
        if any(snap.stage(m.name) for m in MOUNTAINS):
            parts.append(observed_line(snap, bold))
        if any(week_changes(snap, start, end).values()):
            parts.append(week_line(snap, start, end, bold, muted=lambda s: s))
        return " / ".join(parts)

    changes = week_changes(snap, start, end)
    bits = []
    for m in mountains:
        stage = snap.stage(m.name)
        steps = []
        if stage:
            day, _ = snap.when(KINDS[stage - 1], m.name)
            steps.append(f"{STAGES[stage]} {short_date(day)}" if day else STAGES[stage])
        ahead = [f"{STAGES[i]} {short_date(d)}" for i, kind in enumerate(KINDS, start=1)
                 for name, d in changes[kind] if name == m.name]
        if ahead:
            steps.append(" · ".join(ahead) + " (예상)")
        if steps:
            bits.append(f"*{m.name}* " + " → ".join(steps))
    return " · ".join(bits)


def _foliage_note(mountains: tuple[Mountain, ...], start: dt.date, end: dt.date,
                  today: dt.date) -> list[str]:
    """지역 날씨 끝에 붙이는 단풍 한 줄. 단풍철에, 그 지역에 말할 것이 있을 때만.

    단풍을 못 받아 와도 날씨 답은 그대로 나감 — 날씨를 물은 사람에게 주는 덤.
    """
    if not mountains or not in_season(today) or not (snap := _snapshot_quietly(today)):
        return []
    # 이미 지난 날의 예상은 꺼내지 않음 — 그날 물들었으면 관측으로 나옴
    brief = _foliage_brief(snap, mountains, max(start, today), end)
    if not brief:
        return []
    return ["", f":maple_leaf: *단풍* — {brief}", f"_{sources(snap)}_"]


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

    # Socket Mode 는 서명 검증이 필요 없음 (Slack 과의 인증된 WebSocket 위로만 이벤트가 옴)
    app = App(token=bot_token)
    loading = resolve_loading_emoji(app.client)
    log.info("로딩 표시: %s", loading)

    # 안내문 예시가 실제 봇을 가리키게 함. <@U…> 는 슬랙이 표시 이름으로 렌더링하므로
    # 콘솔에서 이름을 바꿔도 문구를 고칠 필요가 없음.
    try:
        _SELF["mention"] = f"<@{app.client.auth_test()['user_id']}>"
    except Exception:
        log.info("봇 user_id 를 얻지 못해 기본 표기를 씁니다")

    @app.event("app_mention")
    def on_mention(event, say, client, logger):
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        channel = event["channel"]
        # 질문 원문과 어느 스레드였는지를 함께 남김 — 실패했을 때 재현할 수 있어야 함.
        ctx = f"user={event.get('user')} ch={channel} ts={thread_ts}"
        started = time.monotonic()
        logger.info("멘션 수신 %s query=%r", ctx, text[:200])

        # 로딩 메시지는 느릴 때만 띄우고 지움. 동 단위 첫 조회는 전국 목록을 받느라 20초 가까이
        # 걸려 반응이 없으면 죽은 줄 알지만, 캐시가 맞으면 0.3초면 끝남.
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
            res = answer(text)
            reply = res.text
            logger.info("응답 완료 %s %.1fs %d자%s", ctx, time.monotonic() - started, len(reply),
                        f" + 지도 {len(res.image):,}B" if res.image else "")
        except Exception:
            # 질문을 같은 줄에 붙임 — 트레이스백만으로는 무엇을 물었는지 알 수 없음.
            logger.exception("응답 생성 실패 %s query=%r", ctx, text[:200])
            reply = "예보를 정리하는 중에 문제가 생겼습니다. 잠시 뒤 다시 불러 주세요."
            res = Reply(reply)
        finally:
            # 로딩 메시지를 올리는 중이었다면 끝날 때까지 기다림 — 아니면 그 메시지가
            # 아래에서 holder 를 본 뒤에 올라와 지워지지도 바뀌지도 않고 남음.
            timer.cancel()
            timer.join()

        # 지도가 있으면 글을 지도에 붙여 한 번에 올림. 로딩 메시지는 지움 —
        # 파일 업로드는 기존 메시지를 고쳐서 붙일 수 없음.
        if res.image:
            try:
                client.files_upload_v2(
                    channel=channel, thread_ts=thread_ts, initial_comment=reply,
                    file=res.image, filename=f"foliage-{dt.datetime.now(tz=KST):%Y%m%d}.png", title="단풍 지도",
                )
                if holder["ts"]:
                    try:
                        client.chat_delete(channel=channel, ts=holder["ts"])
                    except Exception:
                        logger.debug("로딩 메시지 삭제 실패", exc_info=True)
                return
            except Exception as exc:
                # 슬랙 오류든 네트워크 시간 초과든, 지도를 못 올리면 글로라도 답함
                error = exc.response.get("error") if isinstance(exc, SlackApiError) else repr(exc)
                logger.warning("지도 업로드 실패 — 글로만 답합니다 %s error=%s", ctx, error)

        # 로딩 메시지를 띄웠으면 그 자리를 결과로 바꿈 — 채널에 흔적을 남기지 않음
        if holder["ts"]:
            try:
                client.chat_update(channel=channel, ts=holder["ts"], text=reply)
                return
            except Exception:
                logger.debug("로딩 메시지 교체 실패 — 새 메시지로 보냅니다", exc_info=True)
        try:
            say(text=reply, thread_ts=thread_ts)
        except SlackApiError as exc:
            # 원인 코드를 그대로 남김 — not_in_channel / missing_scope 는 코드가 아니라
            # 슬랙 설정 문제라, 그 코드를 보면 콘솔에서 무엇을 고칠지 바로 앎.
            logger.error("슬랙 전송 실패 %s error=%s", ctx, exc.response.get("error"))

    @app.event("message")
    def ignore_messages(logger):
        """app_mention 과 함께 오는 message 이벤트를 조용히 흘려보냄."""

    log.info("Socket Mode 연결 시작 (캐시 TTL %d초)", CACHE_TTL_SEC)
    SocketModeHandler(app, app_token).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
