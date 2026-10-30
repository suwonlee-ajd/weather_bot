"""멘션 답의 꼴 — 글과, 있으면 지도 한 장. 철 소식 답(단풍·첫눈)이 지도를 붙일 때 함께 씀."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.common.cache import get_or_set
from src.mention.forecast import CACHE_TTL_SEC
from src.season.basemap import MapInfo

log = logging.getLogger("weather-mention")


@dataclass
class Reply:
    text: str
    image: bytes | None = None
    slug: str = "map"              # 올릴 파일 이름 앞부분 (foliage-20261102.png)
    title: str = "지도"


def with_map(text: str, info: MapInfo, key: tuple, render: Callable[[], bytes]) -> Reply:
    """그림을 못 그려도 글은 나감."""
    try:
        # 재료가 같으면 그림 재사용(Chromium 렌더링이 느림). 키에 재료를 다 넣어 글과 어긋나지 않게 함
        return Reply(text, get_or_set(key, CACHE_TTL_SEC, render), info.slug, info.title)
    except Exception:
        log.warning("%s 렌더링 실패 — 글로만 답합니다", info.title, exc_info=True)
        return Reply(text)
