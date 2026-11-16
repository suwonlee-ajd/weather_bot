"""광역 구역(기상청 페이지의 stnId · regId)과 지역명 해석."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    key: str
    label: str
    notice_stn: str
    mid_stn1: str
    mid_stn2: str | None = None
    mid_group: str | None = None  # 중기예보는 두 지역을 한 페이지에 묶기도 해 이 문자열이 든 행만 씀
    aliases: tuple[str, ...] = ()


REGIONS: tuple[Region, ...] = (
    Region("전국", "전국", "108", "108", aliases=("전체", "대한민국", "all")),
    Region("수도권", "서울·인천·경기", "109", "109",
           aliases=("서울", "인천", "경기", "경기도", "서울경기", "수도권", "기호")),
    # 중기예보는 강원을 영서/영동으로 나눠 줌 (표의 그룹명 그대로)
    Region("강원", "강원", "105", "105",
           aliases=("강원도", "관동", "춘천", "원주")),
    Region("영서", "강원 영서", "105", "105", mid_group="강원도 영서",
           aliases=("강원영서", "영서지방")),
    Region("영동", "강원 영동", "105", "105", mid_group="강원도 영동",
           aliases=("강원영동", "영동지방", "강릉", "속초", "동해안")),
    Region("충남", "대전·세종·충남", "133", "133", "131", "대전",
           aliases=("대전", "세종", "충청남도", "천안")),
    Region("충북", "충북", "131", "133", "131", "충청북도",
           aliases=("충청북도", "청주")),
    Region("전남", "광주·전남", "156", "156", "146", "광주",
           aliases=("광주", "전라남도", "여수", "목포", "순천")),
    Region("전북", "전북", "146", "156", "146", "전북",
           aliases=("전라북도", "전주", "군산")),
    Region("경남", "부산·울산·경남", "159", "159", "143", "부산",
           aliases=("부산", "울산", "경상남도", "창원", "진주", "김해")),
    Region("경북", "대구·경북", "143", "159", "143", "대구",
           aliases=("대구", "경상북도", "포항", "안동", "구미")),
    Region("제주", "제주", "184", "184", aliases=("제주도", "서귀포")),
)


# 기상청에 단일 페이지가 없는 광역 표현 → (대표 REGIONS key, 안내문)
WIDE_AREAS: dict[str, tuple[str, str]] = {
    "중부": ("수도권", "중부지방은 서울·인천·경기 기준으로 보여드립니다"),
    "중부지방": ("수도권", "중부지방은 서울·인천·경기 기준으로 보여드립니다"),
    "남부": ("경남", "남부지방은 부산·울산·경남 기준으로 보여드립니다"),
    "남부지방": ("경남", "남부지방은 부산·울산·경남 기준으로 보여드립니다"),
    "영남": ("경남", "영남은 부산·울산·경남 기준으로 보여드립니다 (경북은 '경북')"),
    "호남": ("전남", "호남은 광주·전남 기준으로 보여드립니다 (전북은 '전북')"),
    "충청": ("충남", "충청은 대전·세종·충남 기준으로 보여드립니다 (충북은 '충북')"),
    "충청도": ("충남", "충청은 대전·세종·충남 기준으로 보여드립니다 (충북은 '충북')"),
    "영동": ("영동", ""),   # 실제 구역이라 안내 없음
    "영서": ("영서", ""),
}


NATIONWIDE = REGIONS[0]


REGION_HELP = " · ".join(r.key for r in REGIONS)


def region_by_key(key: str) -> Region | None:
    """구역 키 그대로 — 사람이 쓴 말을 읽는 find_region 과 달리 바꿔 읽지 않음."""
    return next((r for r in REGIONS if r.key == key), None)


def extract_region(text: str) -> tuple[Region | None, str]:
    """문장 속 아는 지역 이름을 긴 것부터 찾음 — 조언어를 지우는 방식은 '무등산' 의 '등산' 까지 지움."""
    flat = (text or "").replace(" ", "")
    if not flat:
        return NATIONWIDE, ""

    candidates: list[tuple[str, Region | None, str]] = []
    for name, (key, note) in WIDE_AREAS.items():
        candidates.append((name, region_by_key(key), note))
    for region in REGIONS:
        for name in (region.key, region.label.replace("·", ""), *region.aliases):
            candidates.append((name, region, ""))

    for name, region, note in sorted(candidates, key=lambda c: -len(c[0])):
        if name and name.replace(" ", "") in flat:
            return region, note
    return None, ""


def find_region(query: str | None) -> Region | None:
    region, _ = resolve_region(query)
    return region


def resolve_region(query: str | None) -> tuple[Region | None, str]:
    """(지역, 안내문). 대표 구역으로 바꿔 읽었으면 안내문으로 밝힘 — 조용히 바꾸면 다른 답인 줄 모름."""
    if not query:
        return NATIONWIDE, ""
    text = query.strip().lower().replace(" ", "")
    if not text:
        return NATIONWIDE, ""

    # 광역 표현을 먼저 봄 — '영동' 처럼 실제 구역과 겹치는 말이 있음
    for name, (key, note) in WIDE_AREAS.items():
        if text == name:
            return region_by_key(key), note

    for region in REGIONS:
        canon = {region.key, region.label}
        for name in (region.key, region.label, *region.aliases):
            if text == name.lower().replace(" ", "").replace("·", ""):
                # 도시를 구역 전체로 답하면 밝힘 — 남의 동네가 섞인 기온 범위를 «예보가 틀렸다» 로 읽음
                if name not in canon:
                    return region, (f"'{query.strip()}' 은 기상청 구역 "
                                    f"'{region.label}' 에 묶여 있어 그 기준으로 "
                                    "보여드립니다")
                return region, ""

    for name, (key, note) in WIDE_AREAS.items():
        if name in text:
            return region_by_key(key), note

    for region in REGIONS:
        for name in (region.key, *region.aliases):
            if name.lower() in text:
                return region, ""
    return None, ""
