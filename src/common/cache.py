"""TTL 캐시 — 기상청 예보는 하루 몇 번(통보문 05/11/17/23시, 중기 06/18시)만 갱신되므로 멘션마다 다시 긁지 않음."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_LOCK = threading.Lock()
_STORE: dict[Any, tuple[float, Any]] = {}     # key → (만료 시각, 값)
_FLIGHTS: dict[Any, _Flight] = {}             # key → 지금 만드는 중인 한 번


class _Failure:
    """예외 객체 대신 종류와 인자만 — traceback 이 받은 응답 본문까지 붙들고 있지 않게."""
    def __init__(self, exc: BaseException):
        self.kind, self.args, self.text = type(exc), exc.args, str(exc)

    def reraise(self):
        try:
            exc = self.kind(*self.args)
        except Exception:                     # 인자로 다시 못 만드는 예외 — 글만 살림
            exc = RuntimeError(self.text)
        raise exc


class _Flight:
    """한 번의 만들기 — 기다린 쪽은 성공이든 실패든 같은 결과를 받음."""
    def __init__(self):
        self.done = threading.Event()
        self.value: Any = None
        self.failure: _Failure | None = None


def _fresh(key: Any, now: float) -> tuple[bool, Any]:
    with _LOCK:
        hit = _STORE.get(key)
    if not hit or now >= hit[0]:
        return False, None
    if isinstance(hit[1], _Failure):
        hit[1].reraise()
    return True, hit[1]


def get_or_set(
    key: Any,
    ttl_sec: int,
    producer: Callable[[], Any],
    *,
    errors: tuple[type[BaseException], ...] = (),
    error_ttl: int = 0,
) -> Any:
    """`errors` 예외는 `error_ttl` 초 동안 기억해 다시 던짐 — 실패할 때마다 같은 페이지를 다시 받지 않게.

    같은 키를 동시에 찾으면 하나만 만들고 나머지는 그 결과를 기다림 — 멘션이 몰릴 때 느린 페이지를 답마다
    따로 받지 않게. 만드는 동안 전체 락은 쥐지 않아 다른 키는 그대로 읽힘.
    """
    now = time.monotonic()
    found, value = _fresh(key, now)
    if found:
        return value
    with _LOCK:
        flight = _FLIGHTS.get(key)
        leading = flight is None
        if leading:
            flight = _FLIGHTS[key] = _Flight()
    if not leading:
        flight.done.wait()
        if flight.failure:
            flight.failure.reraise()
        return flight.value

    try:
        flight.value = producer()
        _store(key, now + ttl_sec, flight.value, now)
        return flight.value
    except BaseException as exc:
        flight.failure = _Failure(exc)
        if isinstance(exc, errors) and error_ttl > 0:
            _store(key, now + error_ttl, flight.failure, now)
        raise
    finally:
        with _LOCK:
            del _FLIGHTS[key]
        flight.done.set()


def _store(key: Any, expires: float, value: Any, now: float) -> None:
    with _LOCK:
        # 날짜가 든 키(단풍 등)는 날마다 새로 생겨, 지난 항목을 걷지 않으면 계속 쌓임
        for old in [k for k, (until, _) in _STORE.items() if until <= now]:
            del _STORE[old]
        _STORE[key] = (expires, value)


def clear() -> None:
    with _LOCK:
        _STORE.clear()
