"""TTL 캐시 — 기상청 예보는 하루 몇 번(통보문 05/11/17/23시, 중기 06/18시)만 갱신되므로 멘션마다 다시 긁지 않음."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_LOCK = threading.Lock()
_STORE: dict[Any, tuple[float, Any]] = {}     # key → (만료 시각, 값)


class _Failure:
    def __init__(self, exc: BaseException):
        self.exc = exc


def get_or_set(
    key: Any,
    ttl_sec: int,
    producer: Callable[[], Any],
    *,
    errors: tuple[type[BaseException], ...] = (),
    error_ttl: int = 0,
) -> Any:
    """`errors` 예외는 `error_ttl` 초 동안 기억해 다시 던짐 — 실패할 때마다 같은 페이지를 다시 받지 않게."""
    now = time.monotonic()
    with _LOCK:
        hit = _STORE.get(key)
    if hit and now < hit[0]:
        if isinstance(hit[1], _Failure):
            exc = hit[1].exc
            raise type(exc)(*exc.args)
        return hit[1]

    # 락 밖에서 만듦 — 같은 키가 두 번 만들어질 수는 있어도 네트워크 호출 동안 락을 쥐지 않음
    try:
        value = producer()
    except errors as exc:
        if error_ttl > 0:
            _store(key, now + error_ttl, _Failure(exc), now)
        raise
    _store(key, now + ttl_sec, value, now)
    return value


def _store(key: Any, expires: float, value: Any, now: float) -> None:
    with _LOCK:
        # 날짜가 든 키(단풍 등)는 날마다 새로 생겨, 지난 항목을 걷지 않으면 계속 쌓임
        for old in [k for k, (until, _) in _STORE.items() if until <= now]:
            del _STORE[old]
        _STORE[key] = (expires, value)


def clear() -> None:
    with _LOCK:
        _STORE.clear()
