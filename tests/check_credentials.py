"""자격증명 4종이 실제로 동작하는지 확인함 (값은 출력하지 않음).

    set -a && . ./.env && set +a
    python -m tests.check_credentials
"""
from __future__ import annotations

import os
import sys

OK, FAIL, SKIP = "  ✅", "  ❌", "  ⏭️"


def check_slack() -> bool:
    from src.weekly.health import check_slack as probe

    ok, text = probe(os.environ.get("SLACK_BOT_TOKEN", ""), os.environ.get("SLACK_CHANNEL_ID", ""))
    print(f"{OK if ok else FAIL} {text}")
    if ok:
        print("     채널 초대 여부는 실제 게시에서 드러납니다(초대 전이면 channel_not_found)")
    return ok


def check_kma_pages() -> bool:
    """기상청 공개 페이지가 여전히 파싱되는지 (키 불필요)."""
    import datetime as dt

    from src.common.config import KST
    from src.kma.mid_term import fetch_mid_term
    from src.kma.notice import fetch_notice

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
    """문구 작성 백엔드가 응답하는지 (실패해도 규칙 기반은 남음)."""
    backend = os.environ.get("WRITER", "none").lower()
    if backend not in ("claude", "gemini"):
        print(f"{SKIP} WRITER={backend} — 규칙 기반 문구만 사용합니다")
        return True

    if backend == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(f"{SKIP} WRITER=claude 인데 ANTHROPIC_API_KEY 미설정 — 규칙 기반으로 대체됩니다")
            return True
        try:
            import anthropic
        except ImportError:
            print(f"{FAIL} WRITER=claude 인데 anthropic 미설치 — uv sync --extra claude")
            return False

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
    try:
        from google import genai
    except ImportError:
        print(f"{FAIL} WRITER=gemini 인데 google-genai 미설치 — uv sync --extra gemini")
        return False

    try:
        # Client 를 변수에 잡아 둠 — 임시 객체면 페이저 순회 전에 GC 돼 "client closed" 오류
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        models = list(client.models.list())
    except Exception as exc:
        print(f"{FAIL} Gemini: {type(exc).__name__}: {str(exc)[:110]}")
        return False
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    print(f"{OK} 문구 작성: Gemini 모델 {len(models)}개 조회 성공 ({model}, 무료 티어)")
    return True


def check_chromium() -> bool:
    from src.weekly.health import check_chromium as probe

    ok, text = probe()
    print(f"{OK if ok else FAIL} {text}")
    return ok


if __name__ == "__main__":
    print("자격증명 점검 (값은 출력하지 않습니다)\n")
    results = [check_slack(), check_kma_pages(), check_writer(), check_chromium()]
    print()
    if all(results):
        print("전부 준비됨 → python -m src.weekly.post --dry-run")
        sys.exit(0)
    print("위 ❌ 항목을 해결한 뒤 다시 실행하세요.")
    sys.exit(1)
