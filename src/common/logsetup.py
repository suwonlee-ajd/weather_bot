"""로그 초기화 — loguru 를 단일 출구로 두고 표준 logging(슬랙 SDK·requests)을 흡수함.

파일은 logs/2026/2026.09/weather-mention.2026-09-12.log 꼴로 자정마다 새로 생김.
"""
from __future__ import annotations

import inspect
import logging
import os
import sys
from functools import partial
from pathlib import Path
from typing import Final

from loguru import logger

_ROTATION: Final[str] = "00:00"
# 보존 일수의 단일 출처 — bin/cleanup.py 도 이 숫자를 씀
RETENTION_DAYS: Final[int] = 90
_RETENTION: Final[str] = f"{RETENTION_DAYS} days"
_COMPRESSION: Final[str] = "gz"

_CONSOLE_FORMAT: Final[str] = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
    "<level>{level: <7}</level> "
    "<cyan>{name}</cyan>: <level>{message}</level>"
)
_FILE_FORMAT: Final[str] = (
    "{time:YYYY-MM-DD HH:mm:ss} {level: <7} {name}:{function}:{line} - {message}"
)

# 서드파티 소음 누름 — slack_bolt 는 연결마다 여러 줄, urllib3 는 요청마다 한 줄씩 찍음
_THIRD_PARTY_LEVELS: Final[dict[str, str]] = {
    "slack_bolt": "WARNING",
    "slack_sdk": "WARNING",
    "urllib3": "WARNING",
    "requests": "WARNING",
    "asyncio": "INFO",
    "anthropic": "WARNING",
}


def _apply_logger_name(name: str, record: dict[str, object]) -> None:
    record["name"] = name


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # logging 내부 프레임을 건너뛰어야 호출처 파일·줄번호가 찍힘
        frame, depth = inspect.currentframe(), 0
        while frame is not None and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        try:
            message = record.getMessage()
        except Exception:
            message = f"<로그 포맷 실패> {record.msg!r} % {record.args!r}"

        try:
            logger.patch(partial(_apply_logger_name, record.name)).opt(
                depth=depth, exception=record.exc_info
            ).log(level, message)
        except Exception:
            self.handleError(record)


def _install_stdlib_bridge(level: str) -> None:
    root = logging.getLogger()
    # 기존 핸들러를 모두 뗌 — 재호출로 겹친 브리지와 basicConfig 기본 핸들러까지
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(_InterceptHandler())
    root.setLevel(logger.level(level.upper()).no)

    for name, cap in _THIRD_PARTY_LEVELS.items():
        logging.getLogger(name).setLevel(cap)


def log_dir() -> Path:
    """기본은 저장소의 logs/ — LOG_DIR 로 옮김."""
    env = os.environ.get("LOG_DIR")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "logs"   # src/common/logsetup.py → 저장소


def dated_sink_path(base: Path, app_name: str, suffix: str = ".log") -> str:
    return str(base / "{time:YYYY}" / "{time:YYYY.MM}" / f"{app_name}.{{time:YYYY-MM-DD}}{suffix}")


def setup(app_name: str, *, level: str | None = None) -> None:
    """콘솔 + 날짜별 파일(전체, WARNING 이상만 모은 오류)로 로그를 엶. 두 번 불러도 겹치지 않음."""
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    logger.remove()
    logger.add(sys.stderr, level=level, format=_CONSOLE_FORMAT, diagnose=False)

    base = log_dir()
    opened: list[str] = []
    try:
        base.mkdir(parents=True, exist_ok=True)
        common = dict(
            format=_FILE_FORMAT,
            rotation=_ROTATION,
            retention=_RETENTION,
            compression=_COMPRESSION,
            encoding="utf-8",
            # 예외 트레이스에 지역 변수 값(토큰)이 실리지 않게
            diagnose=False,
            enqueue=True,  # 멘션 봇은 타이머 스레드와 함께 씀
        )
        logger.add(dated_sink_path(base, app_name), level=level, **common)
        opened.append("전체")
        logger.add(dated_sink_path(base, f"{app_name}.error"), level="WARNING", **common)
        opened.append("오류")
    except OSError as exc:
        if opened:
            logger.warning(
                "{} 로그 파일만 열렸습니다 (나머지는 실패). WARNING 이상은 전체 로그에서 찾으세요: {}",
                "·".join(opened), exc,
            )
        else:
            logger.warning("로그 파일을 열지 못해 콘솔로만 남깁니다: {}", exc)

    _install_stdlib_bridge(level)
