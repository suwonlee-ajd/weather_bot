"""자격증명 4종이 실제로 동작하는지 확인한다. 값 자체는 절대 출력하지 않는다.

    set -a && . ./.env && set +a
    python -m tests.check_credentials
"""
from __future__ import annotations

import os
import sys

OK, FAIL, SKIP = "  ✅", "  ❌", "  ⏭️"


def _mask(token: str) -> str:
    return f"{token[:8]}…{token[-4:]}" if len(token) > 14 else "…"


def check_slack() -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("SLACK_CHANNEL_ID", "")
    if not token:
        print(f"{FAIL} SLACK_BOT_TOKEN 미설정")
        return False
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    try:
        res = WebClient(token=token).auth_test()
    except SlackApiError as exc:
        print(f"{FAIL} SLACK_BOT_TOKEN ({_mask(token)}): {exc.response.get('error')}")
        return False
    if not token.startswith("xoxb-"):
        print(f"{FAIL} SLACK_BOT_TOKEN 이 봇 토큰(xoxb-)이 아닙니다. OAuth & Permissions 에서 Bot User OAuth Token 을 쓰세요.")
        return False
    # auth_test 의 user 는 앱 생성 당시의 내부 식별자다. 콘솔에서 바꾼 표시 이름은
    # 여기 반영되지 않으므로, 이 값으로 "이름이 안 바뀌었다" 고 판단하면 안 된다.
    print(f"{OK} Slack: {res['team']} / 봇 {res['user_id']} (내부 식별자 {res['user']})")
    print(f"     채널 {channel or '(미설정)'} — 초대 여부는 아래 게시 확인으로 판정합니다")
    return bool(channel)


def check_kma_pages() -> bool:
    """기상청 공개 페이지가 여전히 파싱되는지 (키 불필요)."""
    import datetime as dt

    from src.config import KST
    from src.kma_scrape import ScrapeError, fetch_mid_term, fetch_notice

    ok = True
    for name, fn in (("예보 통보문", fetch_notice), ("중기예보", fetch_mid_term)):
        try:
            days, nar = fn(dt.datetime.now(tz=KST))
        except Exception as exc:
            print(f"{FAIL} 기상청 {name}: {type(exc).__name__}: {str(exc)[:120]}")
            ok = False
            continue
        stamp = f"{nar.issued_at:%m/%d %H시}" if nar.issued_at else "발표시각 미상"
        print(f"{OK} 기상청 {name}: {len(days)}일치 · {stamp} 발표 · 서술 {len(nar.lines)}줄")
    return ok


def check_writer() -> bool:
    """문구 작성 백엔드가 실제로 응답하는지. 실패해도 규칙 기반 폴백은 남는다."""
    backend = os.environ.get("WRITER", "gemini").lower()
    if backend == "none":
        print(f"{SKIP} WRITER=none — 규칙 기반 문구만 사용합니다")
        return True

    if backend == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(f"{SKIP} WRITER=claude 인데 ANTHROPIC_API_KEY 미설정 — 규칙 기반으로 대체됩니다")
            return True
        import anthropic

        try:
            client = anthropic.Anthropic()
            models = list(client.models.list())
        except Exception as exc:
            print(f"{FAIL} Anthropic: {type(exc).__name__}: {str(exc)[:110]}")
            return False
        print(f"{OK} 문구 작성: Anthropic 모델 {len(models)}개 조회 성공 "
              f"({os.environ.get('ANTHROPIC_MODEL', 'claude-opus-5')})")
        return True

    if not os.environ.get("GEMINI_API_KEY"):
        print(f"{SKIP} WRITER=gemini 인데 GEMINI_API_KEY 미설정 — 규칙 기반으로 대체됩니다")
        return True
    from google import genai

    try:
        # Client 를 변수에 붙들어 둬야 한다. 임시 객체로 쓰면 지연 페이저를 순회하기 전에
        # GC 되면서 "Cannot send a request, as the client has been closed" 가 난다.
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        models = list(client.models.list())
    except Exception as exc:
        print(f"{FAIL} Gemini: {type(exc).__name__}: {str(exc)[:110]}")
        return False
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    print(f"{OK} 문구 작성: Gemini 모델 {len(models)}개 조회 성공 ({model}, 무료 티어)")
    return True


def check_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"{FAIL} playwright 미설치 — pip install -r requirements.txt")
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
    except Exception as exc:
        print(f"{FAIL} Chromium 실행 실패 — python -m playwright install chromium 이 필요합니다 ({exc})")
        return False
    print(f"{OK} Chromium: 카드 렌더링 가능")
    return True


if __name__ == "__main__":
    print("자격증명 점검 (값은 출력하지 않습니다)\n")
    results = [check_slack(), check_kma_pages(), check_writer(), check_chromium()]
    print()
    if all(results):
        print("전부 준비됨 → python -m src.post --dry-run")
        sys.exit(0)
    print("위 ❌ 항목을 해결한 뒤 다시 실행하세요.")
    sys.exit(1)
