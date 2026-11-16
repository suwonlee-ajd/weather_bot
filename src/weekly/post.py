"""주간 날씨 브리핑을 슬랙 채널에 게시함 — 헬스체크 → 영역 동시 실행·종합(pipeline) → 전송.

    python -m src.weekly.post              # 실제 게시
    python -m src.weekly.post --dry-run    # 슬랙 전송 없이 data/ 에 저장하고 본문만 출력
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import pathlib
import re
import sys
import time

from src.common.config import KST, Config
from src.common.logsetup import setup
from src.common.retention import sweep
from src.weekly import health, pipeline
from src.weekly.pipeline import Post

log = logging.getLogger("weekly-weather")

MAX_WAIT = dt.timedelta(minutes=60)


def wait_until(post_at: str, now: dt.datetime) -> None:
    """지정 시각(KST)까지 기다림 — 크론 지연을 흡수함."""
    if not post_at:
        return
    hour, minute = (int(x) for x in post_at.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = target - now
    if delta <= dt.timedelta(0):
        log.info("게시 예정 시각(%s KST)이 지나 즉시 게시합니다.", post_at)
        return
    if delta > MAX_WAIT:
        log.warning("게시까지 %s 남아 대기를 건너뜁니다.", delta)
        return
    log.info("%s KST까지 %.0f초 대기합니다.", post_at, delta.total_seconds())
    time.sleep(delta.total_seconds())


# 콘솔에 찍을 때만 바꿈 — 원문의 □/○ 는 서술 파싱(NARRATIVE_RE)이 씀
def _md_bullets(text: str) -> str:
    text = re.sub(r"^□\s*", "- ", text, flags=re.M)
    return re.sub(r"^○\s*", "  - ", text, flags=re.M)


def main(argv: list[str] | None = None) -> int:
    parser, args = _parse_args(argv)
    setup("weekly-weather")
    cfg = Config()
    dry_run = args.dry_run or cfg.dry_run
    if args.data_dir and not dry_run:
        # 조용히 무시하면 지정한 자리에서 파일을 찾다 헤맴
        parser.error("--data-dir 은 --dry-run 과 함께 써야 합니다 (실제 게시는 파일을 남기지 않습니다)")

    ok = health.check(cfg)
    if not ok.slack:
        if not dry_run:
            log.error("슬랙 점검에 실패해 게시하지 않습니다 — python -m tests.check_credentials 로 확인하세요")
            return 1
        log.warning("슬랙 점검에 실패했지만 dry-run 이라 계속합니다")

    post = pipeline.compose(cfg, dt.datetime.now(tz=KST), args.week_offset, can_render=ok.chromium)
    if post is None:
        return 1
    if dry_run:
        _save_dry_run(post, pathlib.Path(args.data_dir or cfg.data_dir) / cfg.img_dir, cfg.slack_channel_id)
        return 0
    if not args.no_wait:
        wait_until(cfg.post_at, dt.datetime.now(tz=KST))
    return _send(post, cfg)


def _parse_args(argv: list[str] | None) -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(description="주간 날씨 슬랙 봇")
    parser.add_argument("--dry-run", action="store_true", help="슬랙에 보내지 않고 출력/저장만")
    parser.add_argument("--no-wait", action="store_true", help="POST_AT 대기 생략")
    parser.add_argument("--data-dir", default=None,
                        help="dry-run 산출물 위치 (이미지는 그 아래 IMG_DIR, 기본 img/ 에 쌓인다). "
                             "실제 게시는 슬랙에만 올리므로 --dry-run 과 함께 써야 한다")
    parser.add_argument(
        "--week-offset", type=int, default=0,
        help="0=이번 주(기본), 1=다음 주. 주 중간에 결과를 미리 보고 싶을 때 쓴다",
    )
    return parser, parser.parse_args(argv)


def _save_dry_run(post: Post, img_dir: pathlib.Path, channel: str) -> None:
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for att in post.attachments:
        sweep(img_dir, att.keep_days, pattern=att.pattern)
        path = img_dir / att.filename
        path.write_bytes(att.png)
        saved.append(path)
    print("=" * 72)
    print(_md_bullets(post.week.as_digest()))
    print("=" * 72)
    print(post.text)
    print("=" * 72)
    print(f"[dry-run] 채널 {channel} · 첨부 {len(post.attachments)}건")
    for path in saved:
        print(f"           {path}")


def _send(post: Post, cfg: Config) -> int:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    client = WebClient(token=cfg.slack_bot_token)
    try:
        if post.attachments:
            result = client.files_upload_v2(
                channel=cfg.slack_channel_id, initial_comment=post.text,
                file_uploads=[att.upload() for att in post.attachments],
            )
        else:
            # 카드·일기도·지도가 모두 빠진 날 — files_upload_v2 는 빈 첨부를 받지 않아 글만 올림
            result = client.chat_postMessage(channel=cfg.slack_channel_id, text=post.text)
    except SlackApiError as exc:
        err = exc.response.get("error")
        if err in ("not_in_channel", "channel_not_found"):
            log.error(
                "봇이 채널(%s)에 없습니다. 해당 채널에서 `/invite @날씨 알리미` 를 실행하세요. "
                "(비공개 채널은 초대 전까지 채널 자체가 보이지 않아 channel_not_found 로 나옵니다)",
                cfg.slack_channel_id,
            )
        elif err in ("missing_scope", "invalid_auth"):
            log.error("토큰 스코프를 확인하세요 (chat:write, files:write). 응답: %s", exc.response.data)
        else:
            log.error("슬랙 전송 실패: %s", exc.response.data)
        return 1
    log.info("게시 완료: %s", (result.get("files") or [{}])[0].get("permalink", "") or result.get("ts", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
