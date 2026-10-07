"""주간 날씨 브리핑을 슬랙 채널에 게시함.

본문(날씨 두 문단 → 철 소식 → 출처 줄)에 카드·지상일기도·철 소식 그림을 붙임.

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
from dataclasses import dataclass, field

from src.common.config import KST, Config
from src.common.logsetup import setup
from src.common.retention import sweep
from src.kma.chart import fetch_latest_chart
from src.weekly import themes
from src.weekly.card import render_png
from src.weekly.forecast import ForecastError, WeekForecast, build_week
from src.weekly.paragraph import Message
from src.weekly.writer import write

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


@dataclass
class Post:
    """슬랙에 올릴 한 건. keep 은 uploads 와 같은 순서의 (보존일, 파일명 패턴)."""
    week: WeekForecast
    text: str
    uploads: list[dict] = field(default_factory=list)
    keep: list[tuple[int, str]] = field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    parser, args = _parse_args(argv)
    setup("weekly-weather")
    cfg = Config()
    dry_run = args.dry_run or cfg.dry_run
    if args.data_dir and not dry_run:
        # 조용히 무시하면 지정한 자리에서 파일을 찾다 헤맴
        parser.error("--data-dir 은 --dry-run 과 함께 써야 합니다 (실제 게시는 파일을 남기지 않습니다)")

    post = _compose(cfg, dt.datetime.now(tz=KST), args.week_offset)
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


def _compose(cfg: Config, now: dt.datetime, week_offset: int) -> Post | None:
    try:
        week = build_week(cfg, now, week_offset=week_offset)
    except ForecastError as exc:
        log.error("%s", exc)
        log.error("지어낸 날씨를 올리지 않기 위해 게시를 건너뜁니다.")
        return None
    for warning in week.warnings:
        log.warning("예보 검증: %s", warning)
    for n in week.narratives:
        stamp = f"{n.issued_at:%m/%d %H시}" if n.issued_at else "발표시각 미상"
        log.info("자료: %s (%s)", n.title, stamp)

    written = write(week, cfg)
    week.lead, week.sections, week.alerts = written.lead, written.sections, written.alerts
    log.info("특이사항 %d건", len(week.alerts))

    card_png = render_png(week, scale=cfg.card_scale)
    chart = fetch_latest_chart(cfg.chart_product, back=5)
    log.info("카드 %s bytes / 일기도 %s (%s bytes)", f"{len(card_png):,}", chart.url, f"{len(chart.png):,}")

    message = Message(written.body, credits=[f"{chart.label} · 기상청"])
    for block in themes.blocks_for(week.week_start, now.date(), cfg.card_scale):
        message.add(block)

    post = Post(week, message.to_slack())
    post.uploads += [
        {"filename": f"weekly-weather-{week.week_start:%Y%m%d}.png", "file": card_png,
         "title": f"이번 주 날씨 전망 ({week.area})", "alt_txt": "이번 주 기온·강수 전망 요약 카드"},
        {"filename": chart.filename, "file": chart.png, "title": chart.label, "alt_txt": f"기상청 {chart.label}"},
    ]
    post.keep += [(cfg.card_keep_days, "weekly-weather-*.png"), (cfg.chart_keep_days, f"{cfg.chart_product}_*.png")]
    for att in message.attachments:
        post.uploads.append({"filename": f"{att.slug}-{week.week_start:%Y%m%d}.png", "file": att.png,
                             "title": att.title, "alt_txt": att.alt})
        post.keep.append((cfg.card_keep_days, f"{att.slug}-*.png"))   # 카드처럼 다시 만들 수 있음
    return post


def _save_dry_run(post: Post, img_dir: pathlib.Path, channel: str) -> None:
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for item, (keep_days, pattern) in zip(post.uploads, post.keep, strict=True):
        sweep(img_dir, keep_days, pattern=pattern)
        path = img_dir / item["filename"]
        path.write_bytes(item["file"])
        saved.append(path)
    print("=" * 72)
    print(_md_bullets(post.week.as_digest()))
    print("=" * 72)
    print(post.text)
    print("=" * 72)
    print(f"[dry-run] 채널 {channel} · 첨부 {len(post.uploads)}건")
    for path in saved:
        print(f"           {path}")


def _send(post: Post, cfg: Config) -> int:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    try:
        result = WebClient(token=cfg.slack_bot_token).files_upload_v2(
            channel=cfg.slack_channel_id, initial_comment=post.text, file_uploads=post.uploads,
        )
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
    log.info("게시 완료: %s", (result.get("files") or [{}])[0].get("permalink", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
