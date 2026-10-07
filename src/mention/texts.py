"""멘션 답의 고정 문구 — 거절·동의 표정, 하늘상태 이모지, 인사·도움말."""
from __future__ import annotations

import datetime as dt
import os

from src.advice.rules import _pick
from src.common.config import KST
from src.kma.regions import REGION_HELP
from src.mention.parse import DONG_MAX_DAYS, MAX_FORECAST_DAYS

# 문장 끝에 붙임(앞에 두면 내용을 가림). 자료가 없을 때는 안 붙임 — 사용자 잘못이 아님.
# 유니코드 15.1 ZWJ 라 오래된 클라이언트에서 안 보일 수 있어 환경변수로 바꿀 수 있게 함
NO_EMOJI = os.environ.get("NO_EMOJI", ":head_shaking_horizontally:")


YES_EMOJI = os.environ.get("YES_EMOJI", ":head_shaking_vertically:")


# 기동할 때 실제 user_id 로 채움 — 하드코딩한 이름은 봇 이름이 바뀌면 어긋남
_SELF = {"mention": "@날씨 알리미"}


def self_mention() -> str:
    return _SELF["mention"]


# 순서 중요 — 비/눈 섞인 값이 먼저. 공백은 지우고 견줌(중기 "구름많음" · 동네 "구름 많음")
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
    if not sky:
        return ""
    flat = sky.replace(" ", "")
    for keyword, emoji in SKY_EMOJI:
        if keyword in flat:
            return emoji
    return sky


# 인사만 날마다 돌려 씀 — 기능 안내는 고정
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
