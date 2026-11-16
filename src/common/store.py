"""디스크 캐시 — 한 번 나오면 바뀌지 않는 자료(웨더아이 연간 예상표)를 DATA_DIR/cache 에 JSON 으로 남김."""
from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


def cache_dir() -> Path:
    """DATA_DIR(기본 저장소의 data/) 아래 cache/.

    Config 를 거치지 않음 — 자료 패키지는 설정을 받지 않고, Config 는 슬랙 토큰을 요구함. 이름·기본값은 config.py 와 같게.
    """
    root = Path(os.environ.get("DATA_DIR") or "data").expanduser()
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root     # src/common/store.py → 저장소
    return root / "cache"


def kept[T](name: str, produce: Callable[[], T | None], *, dump: Callable[[T], dict],
            load: Callable[[dict], T]) -> T | None:
    """cache/{name}.json 이 있으면 읽고, 없으면 produce 로 만들어 남김.

    None(아직 없음)과 예외는 남기지 않음 — 다음 실행이 다시 받음.
    """
    path = cache_dir() / f"{name}.json"
    try:
        value = load(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.warning("디스크 캐시를 읽지 못해 다시 받습니다 — %s: %s", path, exc)
    else:
        log.info("디스크 캐시 사용 — %s", path)
        return value
    value = produce()
    if value is not None:
        _write(path, dump(value))
    return value


def _write(path: Path, data: dict) -> None:
    # 임시 파일에 쓰고 바꿔치기 — 멘션 봇과 주간 게시가 함께 돌아도 반쯤 쓴 파일을 읽지 않게
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("디스크 캐시를 남기지 못했습니다 — %s: %s", path, exc)
        return
    log.info("디스크 캐시 저장 — %s", path)
