"""아주 작은 TTL 캐시.

기상청 예보는 하루 네 번(통보문 05/11/17/23시, 중기예보 06/18시)만 갱신된다.
멘션마다 페이지를 긁을 이유가 없다. 응답이 빨라지고, 남의 서버에 대한 예의이기도 하다.

항목마다 만료 시각을 들고 있다가, 새 값을 넣을 때 지난 항목을 걷어낸다. 단풍처럼
날짜가 든 키는 날마다 새로 생기므로, 걷어내지 않으면 멘션 봇이 떠 있는 동안 계속 쌓인다.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_LOCK = threading.Lock()
_STORE: dict[Any, tuple[float, Any]] = {}     # key → (만료 시각, 값)


class _Failure:
    """실패를 기억해 둔 자리. 다시 꺼내면 같은 예외를 새로 만들어 던진다."""
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
    """캐시에 있으면 그 값, 없으면 만들어 넣고 돌려준다.

    `errors` 에 든 예외는 `error_ttl` 초 동안 기억했다가 다시 던진다. 실패할 때마다
    같은 페이지를 다시 받으러 가지 않게 한다 — 예외는 값이 아니라 그냥 두면 캐시에 남지 않는다.
    """
    now = time.monotonic()
    with _LOCK:
        hit = _STORE.get(key)
    if hit and now < hit[0]:
        if isinstance(hit[1], _Failure):
            exc = hit[1].exc
            raise type(exc)(*exc.args)
        return hit[1]

    # 값을 만드는 동안에는 락을 놓는다. 같은 키가 동시에 두 번 만들어질 수는 있지만,
    # 네트워크 호출을 락 안에서 붙들고 있는 것보다 낫다.
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
        for old in [k for k, (until, _) in _STORE.items() if until <= now]:
            del _STORE[old]
        _STORE[key] = (expires, value)


def clear() -> None:
    with _LOCK:
        _STORE.clear()
