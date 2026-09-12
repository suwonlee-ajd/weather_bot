"""아주 작은 TTL 캐시.

기상청 예보는 하루 네 번(통보문 05/11/17/23시, 중기예보 06/18시)만 갱신된다.
멘션마다 페이지를 긁을 이유가 없다. 응답이 빨라지고, 남의 서버에 대한 예의이기도 하다.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_LOCK = threading.Lock()
_STORE: dict[Any, tuple[float, Any]] = {}


def get_or_set(key: Any, ttl_sec: int, producer: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _LOCK:
        hit = _STORE.get(key)
        if hit and now - hit[0] < ttl_sec:
            return hit[1]

    # 값을 만드는 동안에는 락을 놓는다. 같은 키가 동시에 두 번 만들어질 수는 있지만,
    # 네트워크 호출을 락 안에서 붙들고 있는 것보다 낫다.
    value = producer()
    with _LOCK:
        _STORE[key] = (now, value)
    return value


def clear() -> None:
    with _LOCK:
        _STORE.clear()
