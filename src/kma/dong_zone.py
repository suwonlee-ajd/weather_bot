"""행정동 이름 → 동네예보 행정동코드(10자리) 검색.

동 목록은 날씨누리 지역 API 에 그때그때 물음 — 행정동이 계속 바뀌어 리포 스냅샷은 조용히 낡음.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from src.common.cache import get_or_set
from src.common.config import UA

log = logging.getLogger(__name__)


ZONE_URL = "https://www.weather.go.kr/w/rest/zone/dong.do"

ZONE_TTL_SEC = 24 * 3600

# "서울 강남" 처럼 앞에 붙여 동명이인을 가려내는 시/도 약칭
WIDE_ALIASES = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
    "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
    "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
    "제주": "제주특별자치도",
}


@dataclass(frozen=True)
class Dong:
    code: str
    wide: str
    city: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.wide} {self.city} {self.name}"

    @property
    def short_name(self) -> str:
        return f"{self.city} {self.name}"


def _zone(kind: str, wide_code: str = "", city_code: str = "") -> list[dict]:
    params = {
        "type": kind, "wideCode": wide_code, "cityCode": city_code,
        "keyword": "", "keywordStart": "", "keywordEnd": "",
    }
    resp = requests.get(ZONE_URL, params=params,
                        headers={"User-Agent": UA}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _normalize(text: str) -> str:
    return (text or "").strip().replace(" ", "")


def _dongs_in(wide: dict, city: dict) -> list[Dong]:
    return [
        Dong(d["code"], wide["name"], city["name"], d["name"])
        for d in _zone("DONG", wide["code"], city["code"])
    ]


# «도시 = 시도» 인 곳은 시도 값으로 답함 — 광역 구역(부산·울산·경남) 기온엔 경남내륙이 섞임
_WIDE_ALIASES = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
    "인천": "인천광역시", "대전": "대전광역시", "울산": "울산광역시",
    "세종": "세종특별자치시", "제주": "제주특별자치도",
}

# 광주는 값이 같은 5개 구 중 하나로 대신함 — '전남광주통합특별시' 는 27개 시군구라 너무 넓음
_CITY_ALIASES = {
    "광주": ("전남광주통합특별시", "북구", "광주광역시"),
}


def find_wide(query: str) -> tuple[str, str] | None:
    """'부산' 처럼 도시 하나를 가리키는 말이면 (동네예보 코드, 보여줄 이름)."""
    text = _normalize(query).lower()
    if not text:
        return None
    for alias, full in _WIDE_ALIASES.items():
        if text in (alias, full, full.replace("특별시", "").replace("광역시", "")):
            for w in _zone("WIDE"):
                if w["name"] == full:
                    return w["code"], w["name"]
    for alias, (wide_name, city_name, label) in _CITY_ALIASES.items():
        if text in (alias, label, f"{alias}광역시"):
            wide = next((w for w in _zone("WIDE") if w["name"] == wide_name), None)
            if not wide:
                return None
            city = next((c for c in _zone("CITY", wide["code"])
                         if c["name"] == city_name), None)
            if city:
                return city["code"], label
    return None


def _split_wide(text: str) -> tuple[str | None, str]:
    """앞에 붙은 시/도 약칭 → (시/도 정식 이름, 나머지). 없으면 (None, text)."""
    for alias, full in WIDE_ALIASES.items():
        if text.startswith(alias) and len(text) > len(alias):
            return full, text[len(alias):]
    return None, text


def _heads(city_name: str) -> set[str]:
    """'성남시분당구' 같은 합친 이름도 앞 토막('성남')으로 걸리게 함."""
    name = _normalize(city_name)
    return {name} | {name.split(cut)[0] for cut in ("시", "군", "구") if cut in name}


def _candidate_cities(text: str) -> list[tuple[dict, dict]]:
    wides = get_or_set("zone:wide", ZONE_TTL_SEC, lambda: _zone("WIDE"))
    scoped, rest = _split_wide(text)

    pairs: list[tuple[dict, dict]] = []
    for wide in wides:
        if scoped and wide["name"] != scoped:
            continue
        cities = get_or_set(
            f"zone:city:{wide['code']}", ZONE_TTL_SEC,
            lambda w=wide: _zone("CITY", w["code"]),
        )
        for city in cities:
            if any(h and (rest.startswith(h) or h.startswith(rest)) for h in _heads(city["name"]) if h):
                pairs.append((wide, city))
    return pairs


def _all_dongs() -> list[Dong]:
    """지역 API 가 keyword 검색을 못 해 전국을 훑음 — 요청 약 250번이라 하루 캐시함."""
    def build() -> list[Dong]:
        out: list[Dong] = []
        for wide in _zone("WIDE"):
            for city in _zone("CITY", wide["code"]):
                out += _dongs_in(wide, city)
        log.info("전국 행정동 %d건 수집", len(out))
        return out

    return get_or_set("zone:all", ZONE_TTL_SEC, build)


def _pool(text: str) -> tuple[list[tuple[dict, dict]], list[Dong]]:
    """(걸린 시군구들, 후보 동). 시군구가 안 걸리면 전국 동."""
    pairs = _candidate_cities(text)
    pool: list[Dong] = []
    for wide, city in pairs[:6]:
        pool += get_or_set(
            f"zone:dong:{city['code']}", ZONE_TTL_SEC,
            lambda w=wide, c=city: _dongs_in(w, c),
        )
    if not pool:
        pool = _all_dongs()          # 동 이름만 준 경우 (역삼, 봉담 …)
    return pairs, pool


def _strip_place(text: str, pairs: list[tuple[dict, dict]]) -> str:
    """시/도에 시군구 이름까지 떼어냄 — "성남 판교" 의 '판교' 로 동을 고르게."""
    _, stripped = _split_wide(text)
    for _, city in pairs:
        for head in sorted((h for h in _heads(city["name"]) if h), key=len, reverse=True):
            if stripped.startswith(head) and len(stripped) > len(head):
                return stripped[len(head):]
    return stripped


def _score(stripped: str, d: Dong, narrowed: bool) -> int | None:
    """작을수록 가까움. None 이면 후보에서 뺌."""
    name, city = _normalize(d.name), _normalize(d.city)
    if stripped == name:
        return 0
    if name.startswith(stripped):
        return 1
    if stripped in name:
        return 2
    if city.startswith(stripped) or stripped.startswith(city.rstrip("시군구")):
        # 구 이름만 준 경우('강남')
        return 3 if stripped not in name else 2
    if narrowed:
        return 4        # 시군구로 좁혀진 결과라 후보로 남김
    return None         # 전국을 훑는 중이면 버림


def search_dong(query: str, limit: int = 5) -> list[Dong]:
    """행정동 후보를 점수순으로. 구 이름만('강남')도, 시/도·시군구를 붙인 말('강릉 강남')도 받음."""
    text = _normalize(query)
    if not text:
        return []

    try:
        pairs, pool = _pool(text)
    except (requests.RequestException, ValueError) as exc:
        log.warning("행정동 조회 실패: %s", exc)
        return []

    stripped = _strip_place(text, pairs)
    scored = [(score, d) for d in pool if (score := _score(stripped, d, bool(pairs))) is not None]
    scored.sort(key=lambda pair: (pair[0], pair[1].full_name))
    hits = [d for _, d in scored[:limit]]

    # 접미사를 떼고 다시 찾음 — '역삼동' 의 실제 행정동은 '역삼1동'·'역삼2동'
    if not hits and len(text) > 2 and text[-1] in "동읍면":
        return search_dong(text[:-1], limit)
    return hits


def find_dong(query: str) -> tuple[str, str] | None:
    """가장 가까운 동 하나. 행정동코드 10자리를 직접 줘도 받음."""
    text = _normalize(query)
    if text.isdigit() and len(text) == 10:
        return text, text
    hits = search_dong(query, limit=1)
    return (hits[0].code, hits[0].full_name) if hits else None


