"""게시 전 점검 — 슬랙은 필수, 기상청·Chromium 은 결과만 남김.

기상청이 죽으면 1번 날씨가 실패해 게시가 저절로 빠지고, Chromium 이 없으면 카드·지도 없이 글만 올림.
tests/check_credentials 도 같은 함수로 점검함. 토큰 값은 남기지 않음.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from src.common.config import UA, Config
from src.kma.page import BASE

log = logging.getLogger(__name__)

KMA_URL = f"{BASE}/w/index.do"


@dataclass(frozen=True)
class Health:
    slack: bool
    kma: bool
    chromium: bool


def check_slack(token: str, channel: str) -> tuple[bool, str]:
    """(통과, 설명). 봇에 channels:read 가 없어 채널 초대 여부는 못 봄 — 게시 때 not_in_channel 로 드러남."""
    if not token:
        return False, "SLACK_BOT_TOKEN 미설정"
    if not token.startswith("xoxb-"):
        return False, "SLACK_BOT_TOKEN 이 봇 토큰(xoxb-)이 아닙니다. OAuth & Permissions 의 Bot User OAuth Token 을 쓰세요"
    if not channel:
        return False, "SLACK_CHANNEL_ID 미설정"
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    try:
        res = WebClient(token=token, timeout=15).auth_test()
    except SlackApiError as exc:
        return False, f"슬랙 인증 실패: {exc.response.get('error')}"
    except Exception as exc:              # 네트워크 오류 — 슬랙 SDK 가 urllib 예외를 그대로 올림
        return False, f"슬랙 접속 실패: {type(exc).__name__}"
    # auth_test 의 user 는 앱 생성 당시 내부 식별자 — 바꾼 표시 이름이 반영되지 않음
    return True, f"Slack: {res['team']} / 봇 {res['user_id']} (내부 식별자 {res['user']}) · 채널 {channel}"


def check_kma() -> tuple[bool, str]:
    try:
        resp = requests.get(KMA_URL, headers={"User-Agent": UA}, timeout=15)
    except requests.RequestException as exc:
        return False, f"기상청 접속 실패: {type(exc).__name__}"
    if resp.status_code != 200:
        return False, f"기상청 응답 {resp.status_code}"
    return True, "기상청 날씨누리 접속"


def check_chromium() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright 미설치 — uv sync 후 .venv/bin/python -m playwright install chromium"
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:
        return False, f"Chromium 실행 실패 — python -m playwright install chromium 이 필요합니다 ({type(exc).__name__})"
    return True, "Chromium: 카드·지도 렌더링 가능"


def check(cfg: Config) -> Health:
    results = {
        "slack": check_slack(cfg.slack_bot_token, cfg.slack_channel_id),
        "kma": check_kma(),
        "chromium": check_chromium(),
    }
    for ok, text in results.values():
        if ok:
            log.info("점검 통과 — %s", text)
        else:
            log.warning("점검 실패 — %s", text)
    return Health(**{name: ok for name, (ok, _) in results.items()})
