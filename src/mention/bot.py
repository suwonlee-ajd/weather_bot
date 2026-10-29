"""`@날씨 알리미 부산` 처럼 멘션으로 날씨를 묻는 봇. Socket Mode 라 인바운드 포트·TLS·Signing Secret 이 필요 없음.

    SLACK_BOT_TOKEN=xoxb-...   (chat:write, files:write, app_mentions:read, emoji:read)
    SLACK_APP_TOKEN=xapp-...   (connections:write)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass

from slack_sdk.errors import SlackApiError

from src.common.config import KST
from src.common.logsetup import setup
from src.mention.answer import Reply, answer
from src.mention.region_reply import CACHE_TTL_SEC
from src.mention.texts import _SELF

log = logging.getLogger("weather-mention")

LOADING_EMOJI = os.environ.get("LOADING_EMOJI", "")
LOADING_FALLBACK = ":hourglass_flowing_sand:"
LOADING_PREFERRED = (":loading:", ":loading2:", ":bearloading:")


# 이보다 빨리 끝나면 로딩 메시지 없음 (캐시 적중은 0.3초)
SLOW_REPLY_SEC = 2.0


def resolve_loading_emoji(client) -> str:
    """워크스페이스에 있는 로딩 이모지, 없으면 표준 이모지 — 없는 코드는 `:loading:` 글자로 보임."""
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


def session_only(record: logging.LogRecord) -> bool:
    """Bolt 연결 잡담 중 세션 수립(첫 연결 · 재연결 성공)과 WARNING 이상만 통과."""
    return record.levelno >= logging.WARNING or record.getMessage().startswith(
        "A new session has been established"
    )


@dataclass(frozen=True)
class Thread:
    """답할 자리. ctx 는 로그용(사용자·채널·스레드)."""
    channel: str
    ts: str
    ctx: str


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
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app = App(token=bot_token)
    # Bolt 가 App 로거를 루트 수준으로 되돌려 놓음 — 수준 대신 필터로 잡담을 누르고 재연결 기록은 남김
    app.logger.addFilter(session_only)
    loading = resolve_loading_emoji(app.client)
    log.info("로딩 표시: %s", loading)
    try:
        # 안내문 예시용 — <@U…> 는 슬랙이 표시 이름으로 바꿔 보여줌
        _SELF["mention"] = f"<@{app.client.auth_test()['user_id']}>"
    except Exception:
        log.info("봇 user_id 를 얻지 못해 기본 표기를 씁니다")

    @app.event("app_mention")
    def on_mention(event, say, client):
        handle_mention(event, say, client, loading)

    @app.event("message")
    def ignore_messages():
        """app_mention 과 함께 오는 message 이벤트를 흘려보냄."""

    log.info("Socket Mode 연결 시작 (캐시 TTL %d초)", CACHE_TTL_SEC)
    SocketModeHandler(app, app_token).start()
    return 0


def handle_mention(event: dict, say, client, loading: str) -> None:
    text = event.get("text", "")
    channel, ts = event["channel"], event.get("thread_ts") or event.get("ts")
    where = Thread(channel, ts, f"user={event.get('user')} ch={channel} ts={ts}")
    log.info("멘션 수신 %s query=%r", where.ctx, text[:200])
    res, loading_ts = _answer_slowly(text, client, where, loading)
    if res.image and _upload_map(client, where, res, loading_ts):
        return
    _reply_text(say, client, where, res.text, loading_ts)


def _answer_slowly(text: str, client, where: Thread, loading: str) -> tuple[Reply, str | None]:
    """SLOW_REPLY_SEC 를 넘기면 로딩 메시지를 띄움(동 첫 조회는 20초 가까이 걸림). → (답, 로딩 ts)"""
    started = time.monotonic()
    holder: dict[str, str | None] = {"ts": None}

    def show_loading():
        try:
            holder["ts"] = client.chat_postMessage(
                channel=where.channel, thread_ts=where.ts, text=f"{loading} 기상청 자료를 받아오는 중이에요…",
            )["ts"]
        except Exception:
            log.debug("로딩 메시지 실패", exc_info=True)

    timer = threading.Timer(SLOW_REPLY_SEC, show_loading)
    timer.start()
    try:
        res = answer(text)
        log.info("응답 완료 %s %.1fs %d자%s", where.ctx, time.monotonic() - started, len(res.text),
                 f" + 지도 {len(res.image):,}B" if res.image else "")
    except Exception:
        log.exception("응답 생성 실패 %s query=%r", where.ctx, text[:200])
        res = Reply("예보를 정리하는 중에 문제가 생겼습니다. 잠시 뒤 다시 불러 주세요.")
    finally:
        # 로딩 메시지를 올리는 중이면 기다림 — 아니면 교체되지 않고 남음
        timer.cancel()
        timer.join()
    return res, holder["ts"]


def _upload_map(client, where: Thread, res: Reply, loading_ts: str | None) -> bool:
    """글을 지도에 붙여 올리고 로딩 메시지는 지움 — 파일은 기존 메시지에 붙일 수 없음."""
    try:
        client.files_upload_v2(
            channel=where.channel, thread_ts=where.ts, initial_comment=res.text, file=res.image,
            filename=f"{res.slug}-{dt.datetime.now(tz=KST):%Y%m%d}.png", title=res.title,
        )
    except Exception as exc:
        error = exc.response.get("error") if isinstance(exc, SlackApiError) else repr(exc)
        log.warning("지도 업로드 실패 — 글로만 답합니다 %s error=%s", where.ctx, error)
        return False
    if loading_ts:
        try:
            client.chat_delete(channel=where.channel, ts=loading_ts)
        except Exception:
            log.debug("로딩 메시지 삭제 실패", exc_info=True)
    return True


def _reply_text(say, client, where: Thread, reply: str, loading_ts: str | None) -> None:
    if loading_ts:
        try:
            client.chat_update(channel=where.channel, ts=loading_ts, text=reply)
            return
        except Exception:
            log.debug("로딩 메시지 교체 실패 — 새 메시지로 보냅니다", exc_info=True)
    try:
        say(text=reply, thread_ts=where.ts)
    except SlackApiError as exc:
        # not_in_channel · missing_scope 면 슬랙 앱 설정 문제
        log.error("슬랙 전송 실패 %s error=%s", where.ctx, exc.response.get("error"))


if __name__ == "__main__":
    sys.exit(main())
