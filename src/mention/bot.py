"""`@날씨 알리미 부산` 처럼 멘션으로 지역 날씨를 물어보는 봇. (Socket Mode)

Socket Mode 를 씀 — 나가는 WebSocket 연결 하나뿐이라 인바운드 포트·리버스 프록시·TLS 인증서·
Signing Secret 이 필요 없고, 서버에 이미 떠 있는 다른 서비스의 ingress 를 건드리지 않음.

    SLACK_BOT_TOKEN=xoxb-...   (chat:write, files:write, app_mentions:read, emoji:read)
    SLACK_APP_TOKEN=xapp-...   (connections:write)

    python -m src.mention.bot
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

# 워크스페이스 커스텀 이모지를 쓰되, 없는 워크스페이스에서는 표준 이모지로 물러섬.
LOADING_EMOJI = os.environ.get("LOADING_EMOJI", "")
LOADING_FALLBACK = ":hourglass_flowing_sand:"
LOADING_PREFERRED = (":loading:", ":loading2:", ":bearloading:")


# 이 시간 안에 끝나면 로딩 메시지를 띄우지 않음 (캐시 적중은 0.3초면 끝남)
SLOW_REPLY_SEC = 2.0


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


@dataclass(frozen=True)
class Thread:
    """답할 자리. ctx 는 로그용 — 질문을 재현할 수 있게 사용자·채널·스레드를 함께 남김."""
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

    app = App(token=bot_token)   # Socket Mode 라 서명 검증이 필요 없음
    # Bolt 가 App 로거를 루트 수준(INFO)으로 되돌림 — 연결 잡담을 다시 누름. 멘션 처리는 log 로 남김
    app.logger.setLevel(logging.WARNING)
    loading = resolve_loading_emoji(app.client)
    log.info("로딩 표시: %s", loading)
    try:
        # 안내문 예시가 실제 봇을 가리키게 — <@U…> 는 슬랙이 표시 이름으로 바꿔 보여줌
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
    """멘션 하나에 답함. 지도가 있으면 글과 함께 올리고, 못 올리면 글로만."""
    text = event.get("text", "")
    channel, ts = event["channel"], event.get("thread_ts") or event.get("ts")
    where = Thread(channel, ts, f"user={event.get('user')} ch={channel} ts={ts}")
    log.info("멘션 수신 %s query=%r", where.ctx, text[:200])
    res, loading_ts = _answer_slowly(text, client, where, loading)
    if res.image and _upload_map(client, where, res, loading_ts):
        return
    _reply_text(say, client, where, res.text, loading_ts)


def _answer_slowly(text: str, client, where: Thread, loading: str) -> tuple[Reply, str | None]:
    """답을 만듦. SLOW_REPLY_SEC 안에 못 끝내면 로딩 메시지를 띄우고 그 ts 를 돌려줌.

    동 단위 첫 조회는 전국 목록을 받느라 20초 가까이 걸림 — 반응이 없으면 죽은 줄 앎.
    """
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
        # 로딩 메시지를 올리는 중이면 끝날 때까지 기다림 — 아니면 지워지지도 바뀌지도 않고 남음
        timer.cancel()
        timer.join()
    return res, holder["ts"]


def _upload_map(client, where: Thread, res: Reply, loading_ts: str | None) -> bool:
    """글을 지도에 붙여 한 번에 올리고 로딩 메시지는 지움(파일은 기존 메시지에 붙일 수 없음). 실패하면 False."""
    try:
        client.files_upload_v2(
            channel=where.channel, thread_ts=where.ts, initial_comment=res.text, file=res.image,
            filename=f"foliage-{dt.datetime.now(tz=KST):%Y%m%d}.png", title="단풍 지도",
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
    """로딩 메시지를 띄웠으면 그 자리를 결과로 바꾸고, 아니면 새로 답함."""
    if loading_ts:
        try:
            client.chat_update(channel=where.channel, ts=loading_ts, text=reply)
            return
        except Exception:
            log.debug("로딩 메시지 교체 실패 — 새 메시지로 보냅니다", exc_info=True)
    try:
        say(text=reply, thread_ts=where.ts)
    except SlackApiError as exc:
        # 원인 코드를 남김 — not_in_channel · missing_scope 는 슬랙 설정 문제라 코드만 보면 고칠 곳을 앎
        log.error("슬랙 전송 실패 %s error=%s", where.ctx, exc.response.get("error"))


if __name__ == "__main__":
    sys.exit(main())
