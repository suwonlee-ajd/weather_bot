"""산출물 보존 기간 — 오래된 파일을 지운다.

`logs/` 는 loguru 가 알아서 회전·압축·폐기한다(src/logsetup.py). 여기가 맡는 것은
그 바깥, 관리 주체가 없어 무한정 쌓이는 `data/img/` 이다. dry-run 을 돌릴 때마다
카드·일기도 PNG 가 1MB 가까이 남는다.

지우는 기준은 수정 시각이다. 파일명의 날짜가 아니라 — 같은 날짜로 여러 번
덮어써도 마지막 실행 시점이 기준이 되어야 «최근에 본 것» 이 살아남는다.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# 기본 보존 기간. dry-run 산출물은 그때 눈으로 보고 끝나므로 길 이유가 없다.
DEFAULT_KEEP_DAYS = 14


def sweep(
    directory: Path | str,
    keep_days: int = DEFAULT_KEEP_DAYS,
    *,
    pattern: str = "*",
    recursive: bool = False,
    dry_run: bool = False,
    now: dt.datetime | None = None,
) -> list[tuple[Path, int]]:
    """`keep_days` 보다 오래된 파일을 지우고 `(경로, 바이트)` 목록을 돌려준다.

    크기를 함께 돌려주는 이유는 호출하는 쪽이 «얼마나 비웠는가» 를 알려면
    지우기 전에 재야 하기 때문이다. 지운 뒤에 stat 하면 0 이 된다.

    keep_days 가 0 이하면 보존 기간 없음으로 보고 아무것도 지우지 않는다 —
    «0 = 전부 삭제» 로 읽히면 사고가 난다.

    `recursive` 는 하위 디렉터리까지 훑는다. logs/ 처럼 연·월로 중첩된 자리에 쓴다.
    `dry_run` 은 지우지 않고 대상만 돌려준다.
    """
    if keep_days <= 0:
        return []

    root = Path(directory)
    if not root.is_dir():
        return []

    now = now or dt.datetime.now()
    cutoff = (now - dt.timedelta(days=keep_days)).timestamp()

    found = root.rglob(pattern) if recursive else root.glob(pattern)
    removed: list[tuple[Path, int]] = []
    for path in sorted(found):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            if stat.st_mtime >= cutoff:
                continue
            if not dry_run:
                path.unlink()
        except OSError as exc:
            # 지우기 실패로 본 작업을 죽이지 않는다 — 다음 실행에서 다시 시도한다
            log.warning("정리 실패 %s: %s", path, exc)
            continue
        removed.append((path, stat.st_size))

    if removed:
        verb = "정리 대상" if dry_run else "정리"
        log.info("%s 에서 %d일 지난 파일 %d개 %s", root, keep_days, len(removed), verb)
    return removed


def prune_empty_dirs(root: Path | str) -> list[Path]:
    """빈 디렉터리를 아래에서부터 걷어낸다. root 자신은 남긴다.

    logs/2026/2026.08 처럼 파일을 다 지우고 남은 껍데기가 쌓이는 것을 막는다.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    removed: list[Path] = []
    # 깊은 곳부터 — 자식을 지워야 부모가 비기 때문이다
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir():
            continue
        try:
            path.rmdir()  # 비어 있지 않으면 OSError 로 그냥 넘어간다
        except OSError:
            continue
        removed.append(path)
    return removed
