"""보존 기간이 지난 산출물을 지움.

기준은 파일명의 날짜가 아니라 수정 시각임 — 같은 날짜로 덮어썼으면 마지막 실행이 기준.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# dry-run 산출물은 그때 보고 끝나므로 길게 둘 이유가 없음
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
    """`keep_days` 보다 오래된 파일을 지우고 `(경로, 지우기 전 바이트)` 목록을 돌려줌.

    keep_days 가 0 이하면 보존 기간 없음 — 아무것도 지우지 않음(«0 = 전부 삭제» 가 아님).
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
            # 본 작업은 계속 — 다음 실행에서 다시 시도함
            log.warning("정리 실패 %s: %s", path, exc)
            continue
        removed.append((path, stat.st_size))

    if removed:
        verb = "정리 대상" if dry_run else "정리"
        log.info("%s 에서 %d일 지난 파일 %d개 %s", root, keep_days, len(removed), verb)
    return removed


def prune_empty_dirs(root: Path | str) -> list[Path]:
    """빈 디렉터리를 아래에서부터 걷어냄. root 자신은 남김."""
    root = Path(root)
    if not root.is_dir():
        return []
    removed: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir():
            continue
        try:
            path.rmdir()  # 비어 있지 않으면 OSError
        except OSError:
            continue
        removed.append(path)
    return removed
