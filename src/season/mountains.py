"""기상청이 단풍을 관측하는 21개 명산. 좌표는 정상(위키데이터).

zone 은 이름 검색 대신 코드로 박아 둠 — 이름 검색은 엉뚱한 곳('남원 주천면' → 대구 남구)을 집지만,
낡은 코드는 조회 실패로 드러남.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Mountain:
    name: str                       # 기상청 표기
    lat: float
    lon: float
    zone: str                       # 탐방 거점(산 아래 마을)의 동네예보 행정동코드
    zone_name: str
    aliases: tuple[str, ...] = ()   # 그 산에만 있는 것만 — '천왕봉'·'비로봉' 은 여러 산에 있음
    label: str = "r"                # 지도 라벨이 점의 어느 쪽에 붙는지 r/l/t/b


MOUNTAINS: tuple[Mountain, ...] = (
    Mountain("설악산", 38.1194, 128.4656, "5121060000", "속초시 대포동", ("설악", "대청봉")),
    Mountain("오대산", 37.7981, 128.5431, "5176036000", "평창군 진부면"),
    Mountain("북한산", 37.6608, 126.9933, "1130564500", "서울 강북구 우이동", ("백운대",)),
    Mountain("치악산", 37.3650, 128.0553, "5113031000", "원주시 소초면", ("치악",)),
    Mountain("소백산", 36.9600, 128.4847, "4721025000", "영주시 풍기읍"),
    Mountain("월악산", 36.8833, 128.0833, "4315035000", "제천시 한수면", label="l"),
    Mountain("속리산", 36.5433, 127.8706, "4372031500", "보은군 속리산면", ("법주사",)),
    Mountain("주왕산", 36.3892, 129.1626, "4775031500", "청송군 주왕산면", label="t"),
    Mountain("계룡산", 36.3433, 127.2061, "4415034000", "공주시 반포면", ("동학사",), label="l"),
    Mountain("금오산", 36.0925, 128.3000, "4719056500", "구미시 선주원남동", label="l"),
    Mountain("팔공산", 36.0169, 128.6953, "2714076000", "대구 동구 공산동"),
    Mountain("덕유산", 35.8606, 127.7464, "5273032000", "무주군 설천면", ("향적봉",), label="l"),
    Mountain("가야산", 35.8221, 128.1179, "4889033000", "합천군 가야면", ("해인사",), label="b"),
    Mountain("가지산", 35.6206, 129.0031, "3171038000", "울주군 상북면"),
    Mountain("내장산", 35.4833, 126.8833, "5218053500", "정읍시 내장상동", ("내장사",), label="l"),
    Mountain("지리산", 35.3369, 127.7306, "5219031000", "남원시 주천면", ("노고단",)),
    Mountain("무등산", 35.1342, 126.9889, "1230068500", "광주 북구 석곡동", ("무등",), label="l"),
    Mountain("조계산", 35.0025, 127.3136, "1215025000", "순천시 승주읍", ("선암사", "송광사")),
    Mountain("월출산", 34.7678, 126.7044, "1280036000", "영암군 군서면", label="l"),
    Mountain("두륜산", 34.4728, 126.6378, "1279031000", "해남군 삼산면", ("대흥사",), label="l"),
    Mountain("한라산", 33.3617, 126.5292, "5011066000", "제주시 노형동", ("한라", "백록담")),
)

BY_NAME = {m.name: m for m in MOUNTAINS}

# 광역 구역(kma_scrape.REGIONS 키)별 산. 여러 도에 걸친 산은 구역마다 둠. 전국은 21곳 전부라 뺌.
REGION_MOUNTAINS: dict[str, tuple[str, ...]] = {
    "수도권": ("북한산",),
    "강원": ("설악산", "오대산", "치악산"),
    "영서": ("설악산", "오대산", "치악산"),       # 설악산은 인제, 오대산은 평창·홍천
    "영동": ("설악산", "오대산"),                 # 설악산은 속초·양양, 오대산은 강릉
    "충남": ("계룡산",),
    "충북": ("소백산", "월악산", "속리산"),
    "전북": ("덕유산", "내장산", "지리산"),
    "전남": ("지리산", "무등산", "조계산", "월출산", "두륜산"),
    "경남": ("덕유산", "가야산", "가지산", "지리산"),
    "경북": ("소백산", "속리산", "주왕산", "금오산", "팔공산", "가야산", "가지산"),
    "제주": ("한라산",),
}

# 낱말 끝 조사(겹친 것 포함). '으로' 등이 남으면 '설악면으로' 가 행정구역으로 안 걸러짐.
# 산 이름·별칭은 이 글자들로 끝나지 않아야 함.
_PARTICLE = re.compile(r"(?:은|는|이|가|을|를|도|의|에서|에|쪽|근처|으로|로|까지|부터|만)+$")
# 산 이름 바로 뒤에서 낱말이 끝나면 행정구역 — '설악면'(가평), '속리산면'(보은)
_PLACE_SUFFIX = ("동", "면", "읍", "리")
# '산' 앞에 붙어도 산 이름이 아닌 말 ("어느산이 좋아?")
_NOT_NAME = re.compile(
    r"(어느|무슨|어떤|아무|다른|우리|동네|근교|근처|주변|인근|가까운|좋은|예쁜|이쁜|높은|낮은|"
    r"유명한|큰|작은|뒷|앞)산"
)
# 같은 자리면 목록 앞의 산이 이김
_KEYED: tuple[tuple[str, Mountain], ...] = tuple(
    (key.replace(" ", ""), m) for m in MOUNTAINS for key in (m.name, *m.aliases))
_KEYS = tuple(key for key, _ in _KEYED)
# '산' 만 뗀 줄임말('설악'·'한라')은 낱말 하나일 때만 — '한라대'·'무등경기장' 의 앞머리이기도 함
_SHORT = frozenset(a for m in MOUNTAINS for a in m.aliases if m.name.startswith(a))


def find_mountain(text: str) -> Mountain | None:
    """문장에서 먼저 나온 산. 행정구역 이름에 든 산 이름('설악면')은 건너뜀."""
    words = (_PARTICLE.sub("", w) for w in re.split(r"[\s,.?!~]+", text))
    kept = [w for w in words if not (w.endswith(_PLACE_SUFFIX) and w[:-1].endswith(_KEYS))]
    flat = "".join(kept)
    starts: dict[str, int] = {}            # 줄임말은 낱말로만 찾음
    for w, at in zip(kept, itertools.accumulate((len(w) for w in kept), initial=0)):
        starts.setdefault(w, at)
    best: tuple[int, Mountain] | None = None
    for key, m in _KEYED:
        pos = starts.get(key, -1) if key in _SHORT else flat.find(key)
        if pos >= 0 and (best is None or pos < best[0]):
            best = (pos, m)
    return best[1] if best else None


def in_region(key: str) -> tuple[Mountain, ...]:
    """광역 구역 안의 산, 목록 순서(북→남)대로."""
    names = REGION_MOUNTAINS.get(key, ())
    return tuple(m for m in MOUNTAINS if m.name in names)


def in_zone(code: str) -> tuple[Mountain, ...]:
    """동네예보 코드(시도·시군구) 안에 탐방 거점이 있는 산. 행정동코드는 시도 2·시군구 3·읍면동 3·리 2 자리."""
    n = 2 if not code[2:].strip("0") else 5
    return tuple(m for m in MOUNTAINS if m.zone[:n] == code[:n])


def unknown_mountain(text: str) -> str | None:
    """목록에 없는 'X산' 이름. 두 글자는 대개 도시·말(부산·등산)이라 세 글자 이상만 봄."""
    if find_mountain(text):
        return None
    for token in re.split(r"[\s,.?!~]+", text):
        word = _PARTICLE.sub("", token)
        if (3 <= len(word) <= 4 and word.endswith("산") and re.fullmatch(r"[가-힣]+", word)
                and not _NOT_NAME.fullmatch(word)):
            return word
    return None
