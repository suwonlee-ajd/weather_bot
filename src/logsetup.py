"""로그 초기화 — loguru 를 단일 출구로 두고 표준 logging 을 그쪽으로 흡수한다.

슬랙 SDK·requests 는 표준 logging 으로 찍으므로, 다리를 놓지 않으면 같은 실행의
로그가 두 갈래 포맷으로 갈린다. 여기서 다리를 놓고 소음이 큰 로거는 눌러 둔다.

파일은 연·월 폴더 아래 앱 이름과 날짜로 쌓인다.

    logs/2026/2026.09/weather-mention.2026-09-12.log
         └연┘ └─연.월─┘ └──앱 이름──┘ └──날짜──┘

자정마다 새 파일로 넘어가므로 «언제의 로그인가» 가 파일명만으로 풀린다.
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

# 자정 회전 + 90일 보관. 개인 맥에서도 돌 수 있으므로 무한정 쌓이지 않게 상한을 둔다.
_ROTATION: Final[str] = "00:00"
# 보존 일수는 bin/cleanup.py 도 쓴다. 문자열을 따로 적어 두면 한쪽만 고쳐져
# 조용히 어긋나므로, 숫자를 단일 출처로 두고 loguru 문자열을 여기서 만든다.
RETENTION_DAYS: Final[int] = 90
_RETENTION: Final[str] = f"{RETENTION_DAYS} days"
_COMPRESSION: Final[str] = "gz"  # 지난 날짜 파일은 압축해 둔다

_CONSOLE_FORMAT: Final[str] = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
    "<level>{level: <7}</level> "
    "<cyan>{name}</cyan>: <level>{message}</level>"
)
# 파일은 색 코드가 섞이면 grep 이 불편하다. 대신 어느 줄에서 났는지를 붙인다.
_FILE_FORMAT: Final[str] = (
    "{time:YYYY-MM-DD HH:mm:ss} {level: <7} {name}:{function}:{line} - {message}"
)

# 서드파티 하한 — 우리 로그를 덮어 버리는 소음을 누른다.
# slack_bolt 는 연결마다 여러 줄, urllib3 는 요청마다 한 줄씩 찍는다.
_THIRD_PARTY_LEVELS: Final[dict[str, str]] = {
    "slack_bolt": "WARNING",
    "slack_sdk": "WARNING",
    "urllib3": "WARNING",
    "requests": "WARNING",
    "asyncio": "INFO",
    "anthropic": "WARNING",
}


def _apply_logger_name(name: str, record: dict[str, object]) -> None:
    """loguru 레코드의 모듈명을 원래 표준 logging 로거 이름으로 교체한다.

    안 바꾸면 전부 이 브리지 모듈 이름으로 찍혀 «어느 라이브러리의 로그인가» 가 사라진다.
    """
    record["name"] = name


class _InterceptHandler(logging.Handler):
    """표준 logging 레코드를 loguru 로 넘기는 다리.

    포맷·전달 실패는 삼켜 `handleError` 로 떨군다 — 로깅 실패가 본 작업을 죽이면 안 된다.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # logging 내부 프레임을 건너뛰어야 호출처 파일·줄번호가 제대로 찍힌다
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
    """표준 logging 루트에 브리지를 설치하고 서드파티 레벨을 고정한다.

    기존 브리지를 먼저 떼어 재호출 시 같은 줄이 두 번 찍히는 것을 막는다.
    """
    root = logging.getLogger()
    # 기존 핸들러를 모두 뗀다 — 재호출 시 겹치는 브리지도, basicConfig 가 남긴
    # 기본 핸들러도 함께 걷힌다. 로그가 두 갈래 포맷으로 갈리는 것을 막는다.
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(_InterceptHandler())
    root.setLevel(logger.level(level.upper()).no)

    for name, cap in _THIRD_PARTY_LEVELS.items():
        logging.getLogger(name).setLevel(cap)


def log_dir() -> Path:
    """LOG_DIR 로 옮길 수 있다. 기본은 저장소 옆 logs/."""
    env = os.environ.get("LOG_DIR")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent.parent / "logs"


def dated_sink_path(base: Path, app_name: str, suffix: str = ".log") -> str:
    """`logs/{연}/{연.월}/{앱}.{날짜}.log` 꼴 sink 패턴.

    한 디렉토리에 날짜 파일이 무한정 쌓이면 목록 조회부터 느려진다 — 연·월로 갈라 둔다.
    """
    return str(base / "{time:YYYY}" / "{time:YYYY.MM}" / f"{app_name}.{{time:YYYY-MM-DD}}{suffix}")


def setup(app_name: str, *, level: str | None = None) -> None:
    """콘솔 + 날짜별 파일 두 갈래로 로그를 연다. 두 번 불러도 중복되지 않는다.

    오류만 모은 파일을 하나 더 둔다 — 정상 트래픽에 묻히면 찾을 수 없기 때문이다.
    수준은 LOG_LEVEL 로 올릴 수 있다(파서가 의심스러울 때 DEBUG).
    """
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    logger.remove()  # 기본 sink 를 먼저 제거해 중복 출력을 막는다
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
            # diagnose=False — 예외 트레이스에 지역 변수 값이 실려 토큰이 새는 것을 막는다
            diagnose=False,
            enqueue=True,  # 멘션 봇은 타이머 스레드와 함께 쓴다
        )
        # 둘 중 하나만 열리면 상태가 어긋난다 — 오류 파일이 없는데 «없으니 경고도
        # 없었다» 고 읽으면 디버깅이 헛돈다. 무엇이 열렸는지 정확히 말한다.
        logger.add(dated_sink_path(base, app_name), level=level, **common)
        opened.append("전체")
        logger.add(dated_sink_path(base, f"{app_name}.error"), level="WARNING", **common)
        opened.append("오류")
    except OSError as exc:
        # 파일에 못 써도 봇은 돌아가야 한다 — 콘솔만으로 계속한다
        if opened:
            logger.warning(
                "{} 로그 파일만 열렸습니다 (나머지는 실패). WARNING 이상은 전체 로그에서 찾으세요: {}",
                "·".join(opened), exc,
            )
        else:
            logger.warning("로그 파일을 열지 못해 콘솔로만 남깁니다: {}", exc)

    _install_stdlib_bridge(level)
