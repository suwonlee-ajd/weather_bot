"""멘션 질문 해석 — 기간·날짜와 인사·과거·전망·단풍 신호."""
from __future__ import annotations

import datetime as dt
import re

from src.kma.page import _resolve_date

MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


NEXT_WEEK_RE = re.compile(r"다음\s*주|담주|next", re.I)


THIS_WEEK_RE = re.compile(r"이번\s*주|금주")


THANKS_RE = re.compile(r"고마|감사|땡큐|thank|수고", re.I)


# 인사·잡담 — 지역으로 읽어 «아는 지역이 아닙니다» 로 답하지 않게
GREETING_RE = re.compile(
    r"안녕|하이|헬로|hello|hi\b|반가|좋은\s*아침|굿모닝|고마|감사|땡큐|thank|수고"
    r"|뭐해|누구|정체|소개|도움말|help|사용법|어떻게\s*써|잘\s*자|바이|잘\s*있어",
    re.I,
)


# 10일 너머 ~ 1개월 — 주 단위 확률 전망으로 답함
OUTLOOK_RE = re.compile(
    r"다음\s*달|한\s*달|1개월|한달|[0-9]+\s*주\s*뒤|앞으로\s*한\s*달"
    r"|(올|이번|내년|다음)?\s*(봄|여름|가을|겨울)"
    r"|장기\s*예보|장기\s*전망|중장기|[0-9]{1,2}\s*월\s*(날씨|기온|예보)",
    re.I,
)


# 1개월 전망도 없는 먼 미래
TOO_FAR_RE = re.compile(
    r"[2-9]\s*개월|[0-9]{2,}\s*개월|내년|재작년|분기"
)


# 리다이렉트 뒤의 최종 주소 (/obs-climate/ 는 여기로 넘어감)
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


# 요일 «(금)» 까지 한 덩어리 — 남으면 지역 이름으로 읽힘. 봇 답의 «09/16(수)» 를 복사해 묻는 일이 많음
_WEEKDAY_SUFFIX = r"(?:\s*[(（]\s*[월화수목금토일](?:요일)?\s*[)）])?"


EXPLICIT_DATE_RE = re.compile(
    r"(?:"
    r"(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일(?!\s*간)"      # 9월 18일 / 18일
    r"|(?:(\d{1,2})\s*[/-]\s*(\d{1,2}))(?!\d)"            # 9/18 · 09-18
    r")" + _WEEKDAY_SUFFIX
)


# 지역 해석 전에 걷어낼 말 — 조언 표현("뭐 입지", "우산 필요해")이 남으면 지역으로 읽힘
NOISE_RE = re.compile(
    r"날씨|알려줘|어때|어떄|알려|좀|주세요|해줘|괜찮|될까|갈만|갈\s*만|필요"
    r"|뭐\s*입|입을|입지|입어|옷차림|복장|우산|등산|산행|캠핑|나들이|소풍|피크닉"
    r"|운동|러닝|자전거|골프|낚시|산책|빨래|세탁|건조|세차|야외"
    r"|[?.,!~]",
    re.I,
)


FORWARD_DAYS = 7


# 광역 예보의 상한(오늘~10일) — 캐시에 이 구간을 통째로 담음
MAX_FORECAST_DAYS = 10


# 동네예보가 닿는 날수 — 그 너머는 광역만
DONG_MAX_DAYS = 5


def _explicit_date(query: str, today: dt.date) -> dt.date | None:
    """예보 범위 밖이어도 거르지 않음 — 자료가 없으면 뒤에서 «예보 없음» 으로 답함."""
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
        return _resolve_date(day, today)          # 가장 가까운 그 일(日) — 월말의 "2일" 은 다음 달
    if not 1 <= month <= 12:
        return None
    # 12월의 "1월 5일" 은 내년
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

    # 주말은 토·일만 — 한 주 전체를 보이면 답이 묻힘
    if WEEKEND_RE.search(query):
        saturday = monday + dt.timedelta(days=5)
        if NEXT_WEEK_RE.search(query) or saturday < today:
            saturday += dt.timedelta(days=7)
        start, days, title = saturday, 2, "주말"
    return start, days, title


# --- 단풍 ---------------------------------------------------------------------
FOLIAGE_RE = re.compile(r"단풍|물들|물드")


FLOWER_RE = re.compile(
    r"벚꽃|벚나무|봄꽃|꽃\s*구경|꽃\s*놀이|꽃\s*축제|꽃이?\s*피|개화|만개|철쭉|진달래|개나리"
)


# 단풍·꽃 말이 섞여도 이게 있으면 날씨 질문 ("꽃구경 가는데 내일 서울 날씨")
WEATHER_ASK_RE = re.compile(r"날씨|기온|춥|추워|덥|더워|바람")


# 산 단풍에 날씨를 붙이는 기간. '지금'·날짜는 뺌 — 단풍 상태나 날짜를 되묻는 말임
# ("설악산 단풍 절정 10/25 맞아?")
TRIP_SPANS = ("주말", "내일", "모레", "이번 주", "다음 주")
