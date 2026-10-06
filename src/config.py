"""환경변수 기반 설정."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")

# 기상청·웨더아이에 보내는 User-Agent. 누가 부르는지 밝혀 둠.
UA = "weather-bot/1.0 (+Slack bot)"


def _env(key: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"환경변수 {key} 가 필요합니다.")
    return val or ""


@dataclass(frozen=True)
class Config:
    # --- Slack (유일한 필수 자격증명) ---
    slack_bot_token: str = field(default_factory=lambda: _env("SLACK_BOT_TOKEN", required=True))
    slack_channel_id: str = field(default_factory=lambda: _env("SLACK_CHANNEL_ID", required=True))

    # --- 예보: 기상청 공개 페이지 스크래핑 (API 키·결제 불필요) ---
    # 전국 · 수도권 · 강원 · 충남 · 충북 · 전남 · 전북 · 경남 · 경북 · 제주
    region: str = field(default_factory=lambda: _env("REGION", "전국"))
    # 비워두면 지역의 정식 이름을 그대로 씀 (예: "부산·울산·경남")
    area_label: str = field(default_factory=lambda: _env("AREA_LABEL", ""))

    # --- 일기도 (인증 불필요한 공개 PNG) ---
    # surf = 지상일기도, ghmd_s24 = 지상 24시간 예상일기도
    chart_product: str = field(default_factory=lambda: _env("CHART_PRODUCT", "surf"))

    # --- 카드 이미지 ---
    card_scale: int = field(default_factory=lambda: int(_env("CARD_SCALE", "2")))

    # --- 문구 작성 ---
    # gemini: 무료 티어로 동작 (검색 없이 글쓰기만 하므로) / claude: 선불 크레딧 필요 / none: 규칙 기반
    writer: str = field(default_factory=lambda: _env("WRITER", "none"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.5-flash"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-5"))
    writer_timeout_sec: int = field(default_factory=lambda: int(_env("WRITER_TIMEOUT_SEC", "90")))

    # --- 산출물 보존 ---
    # 이미지는 data/img/ 한 자리에 모으고, 보존 기간은 파일명 패턴별로 줌(src/post.py 의
    # save_specs). 파일명이 weekly-weather-* 와 surf_* 로 이미 갈려 디렉터리까지 나눌 이유가 없음.
    data_dir: str = field(default_factory=lambda: _env("DATA_DIR", "data"))
    img_dir: str = field(default_factory=lambda: _env("IMG_DIR", "img"))

    # 며칠 뒤 지울지. 0 이면 지우지 않음.
    # logs/ 는 loguru 가 따로 관리함(src/logsetup.py).
    card_keep_days: int = field(default_factory=lambda: int(_env("CARD_KEEP_DAYS", "14")))
    # 일기도는 카드보다 길게 둠 — 기상청이 2일치만 보관해 지나면 다시 받을 수 없음.
    chart_keep_days: int = field(default_factory=lambda: int(_env("CHART_KEEP_DAYS", "30")))

    # --- 실행 ---
    post_at: str = field(default_factory=lambda: _env("POST_AT", "08:00"))  # KST, 빈 값이면 즉시
    dry_run: bool = field(default_factory=lambda: _env("DRY_RUN", "false").lower() == "true")
