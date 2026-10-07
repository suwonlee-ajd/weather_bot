"""기상청이 단풍을 관측하는 21개 명산.

지도 그리기, 멘션에서 산 이름 알아듣기, 산 날씨(동네예보)가 모두 이 목록 하나를 씀.
목록에 없는 산은 모른다고 답함 — 가까운 산으로 짐작하지 않음.

좌표는 정상임(위키데이터, 2026-10 확인). 지도에 점을 찍는 데만 씀.

`zone` 은 산 날씨를 물을 때 보여줄 동네예보의 행정동코드. 기상청 단풍 관측 지점이
있는 탐방 거점(국립공원 입구·사찰 아래 마을)을 골랐음. 산 위가 아니라 산 아래 마을의
예보라는 점을 답에서 밝힘.

행정동은 이름으로 찾지 않고 코드를 박아 둠. 이름 검색은 '남원 주천면' 이
대구 남구로 걸리는 식으로 엉뚱한 곳을 집을 수 있는데, 산 날씨가 다른 도시의
값으로 나가면 알아채기 어려움. 코드가 낡으면 동네예보 조회가 실패하고
"가져오지 못했습니다" 로 답하므로 조용히 틀리지는 않음.
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
    zone: str                       # 동네예보 행정동코드 (탐방 거점)
    zone_name: str                  # 그 행정동을 보여줄 이름
    aliases: tuple[str, ...] = ()
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

# 광역 구역(kma_scrape.REGIONS 의 key)마다 그 안에 걸친 산. 지역 날씨에 단풍 한 줄을 붙일 때 씀.
# 정상부가 여러 도에 걸친 산(지리산·소백산 …)은 걸친 구역마다 둠. 전국은 21곳 전부라 적지 않음.
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

# 낱말 끝에 붙은 조사를 뗌 — '화악산은' 에서 '화악산' 을 얻음. 겹쳐 붙은 것('에서는')과
# '으로'·'까지' 도 뗌 — 남겨 두면 '설악면으로' 가 행정구역으로 걸러지지 않고 설악산이 됨.
# 이름은 깎이지 않음 — 산 이름·별칭은 이 글자들로 끝나지 않음.
_PARTICLE = re.compile(r"(?:은|는|이|가|을|를|도|의|에서|에|쪽|근처|으로|로|까지|부터|만)+$")
# 산 이름 바로 뒤에 붙어 낱말을 끝내면 행정구역임 — '설악면' 은 가평, '속리산면' 은 보은.
# '설악산이면'·'지리산가려면' 의 '면' 은 어미라 산 이름 바로 뒤가 아님.
_PLACE_SUFFIX = ("동", "면", "읍", "리")
# '산' 앞에 붙어도 산 이름이 아닌 말 — "단풍 어느산이 좋아?" 에 "'어느산' 은 모릅니다" 라고 하면 엉뚱함
_NOT_NAME = re.compile(
    r"(어느|무슨|어떤|아무|다른|우리|동네|근교|근처|주변|인근|가까운|좋은|예쁜|이쁜|높은|낮은|"
    r"유명한|큰|작은|뒷|앞)산"
)
# 찾을 이름(이름·별칭, 띄어쓰기 없이)과 그 산. 목록 순서대로라 같은 자리면 앞선 산이 이김.
_KEYED: tuple[tuple[str, Mountain], ...] = tuple(
    (key.replace(" ", ""), m) for m in MOUNTAINS for key in (m.name, *m.aliases))
_KEYS = tuple(key for key, _ in _KEYED)
# '설악'·'한라' 처럼 '산' 만 뗀 줄임말은 낱말 하나로 섰을 때만 산으로 봄. 다른 말의 앞머리이기도
# 해서('한라대'·'치악체육관'·'무등경기장'), 그냥 찾으면 도시의 학교·경기장을 물은 질문이 산 날씨로
# 빠짐 — 산 이름은 단풍 말 없이 물어도 산 날씨로 감.
_SHORT = frozenset(a for m in MOUNTAINS for a in m.aliases if m.name.startswith(a))


def find_mountain(text: str) -> Mountain | None:
    """문장에서 21개 산 가운데 하나를 집어냄. 둘 이상이면 먼저 나온 것.

    별칭은 그 산에만 있는 것만 둠. '천왕봉'·'비로봉' 은 여러 산에 있어 뺐음.
    '설악면' 처럼 행정구역 이름에 든 산 이름은 건너뜀 — 산 날씨가 엉뚱한 동네로 나감.
    """
    words = (_PARTICLE.sub("", w) for w in re.split(r"[\s,.?!~]+", text))
    kept = [w for w in words if not (w.endswith(_PLACE_SUFFIX) and w[:-1].endswith(_KEYS))]
    flat = "".join(kept)
    starts: dict[str, int] = {}            # 낱말이 처음 나온 자리 — 줄임말은 낱말로만 찾음
    for w, at in zip(kept, itertools.accumulate((len(w) for w in kept), initial=0)):
        starts.setdefault(w, at)
    best: tuple[int, Mountain] | None = None
    for key, m in _KEYED:
        pos = starts.get(key, -1) if key in _SHORT else flat.find(key)
        if pos >= 0 and (best is None or pos < best[0]):
            best = (pos, m)
    return best[1] if best else None


def in_region(key: str) -> tuple[Mountain, ...]:
    """광역 구역 안의 산. 목록 순서(북에서 남)를 지킴."""
    names = REGION_MOUNTAINS.get(key, ())
    return tuple(m for m in MOUNTAINS if m.name in names)


def in_zone(code: str) -> tuple[Mountain, ...]:
    """동네예보 코드(시도 또는 시군구) 안에 탐방 거점이 있는 산. '서울' 이면 북한산.

    시도 코드면 앞 2자리로, 광주처럼 시군구 코드면 앞 5자리로 견줌 —
    행정동코드는 시도 2 · 시군구 3 · 읍면동 3 · 리 2 자리.
    """
    n = 2 if not code[2:].strip("0") else 5
    return tuple(m for m in MOUNTAINS if m.zone[:n] == code[:n])


def unknown_mountain(text: str) -> str | None:
    """목록에 없는 'X산' 을 물었으면 그 이름. 산 이름이 없거나 아는 산이면 None.

    세 글자 이상만 산으로 봄. 두 글자 'X산' 은 대개 도시(부산·울산·익산…)나 말
    (등산·하산). 남산 같은 두 글자 산은 놓치지만, 그때도 21곳 전체 현황으로 답함.
    """
    if find_mountain(text):
        return None
    for token in re.split(r"[\s,.?!~]+", text):
        word = _PARTICLE.sub("", token)
        if (3 <= len(word) <= 4 and word.endswith("산") and re.fullmatch(r"[가-힣]+", word)
                and not _NOT_NAME.fullmatch(word)):
            return word
    return None
