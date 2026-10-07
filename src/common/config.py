"""환경변수 기반 설정."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")

UA = "weather-bot/1.0 (+Slack bot)"


def _env(key: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"환경변수 {key} 가 필요합니다.")
    return val or ""


@dataclass(frozen=True)
class Config:
    slack_bot_token: str = field(default_factory=lambda: _env("SLACK_BOT_TOKEN", required=True))
    slack_channel_id: str = field(default_factory=lambda: _env("SLACK_CHANNEL_ID", required=True))

    region: str = field(default_factory=lambda: _env("REGION", "전국"))
    # 비우면 지역의 정식 이름(예: "부산·울산·경남")
    area_label: str = field(default_factory=lambda: _env("AREA_LABEL", ""))

    # 기상청 상품 코드: surf = 지상일기도, ghmd_s24 = 지상 24시간 예상일기도
    chart_product: str = field(default_factory=lambda: _env("CHART_PRODUCT", "surf"))

    card_scale: int = field(default_factory=lambda: int(_env("CARD_SCALE", "2")))

    # gemini: 무료 티어로 충분(검색 없이 글쓰기만) / claude: 선불 크레딧 필요 / none: 규칙 기반
    writer: str = field(default_factory=lambda: _env("WRITER", "none"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.5-flash"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-5"))
    writer_timeout_sec: int = field(default_factory=lambda: int(_env("WRITER_TIMEOUT_SEC", "90")))

    data_dir: str = field(default_factory=lambda: _env("DATA_DIR", "data"))
    img_dir: str = field(default_factory=lambda: _env("IMG_DIR", "img"))

    # 보존 일수. 0 이면 지우지 않음
    card_keep_days: int = field(default_factory=lambda: int(_env("CARD_KEEP_DAYS", "14")))
    # 카드보다 길게 — 기상청이 일기도를 2일치만 보관해 지나면 다시 받을 수 없음
    chart_keep_days: int = field(default_factory=lambda: int(_env("CHART_KEEP_DAYS", "30")))

    post_at: str = field(default_factory=lambda: _env("POST_AT", "08:00"))  # KST, 빈 값이면 즉시
    dry_run: bool = field(default_factory=lambda: _env("DRY_RUN", "false").lower() == "true")
