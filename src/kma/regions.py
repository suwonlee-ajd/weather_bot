"""광역 구역(기상청 페이지의 stnId · regId)과 지역명 해석."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    """기상청 페이지의 지역 구분.

    통보문(notice.do)은 지역별 페이지가 따로 있어 stnId 하나로 끝남.
    중기예보(mid-term.do)는 표에서 해당 그룹 행만 골라내야 함 — 두 지역을 한 페이지에
    묶어 보여주는 경우가 있음(예: 부산·울산·경남 + 대구·경북).
    """

    key: str
    label: str
    notice_stn: str
    mid_stn1: str
    mid_stn2: str | None = None
    mid_group: str | None = None  # 기온/날씨 표에서 이 문자열이 든 지역 행만 사용
    aliases: tuple[str, ...] = ()


REGIONS: tuple[Region, ...] = (
    Region("전국", "전국", "108", "108", aliases=("전체", "대한민국", "all")),
    Region("수도권", "서울·인천·경기", "109", "109",
           aliases=("서울", "인천", "경기", "경기도", "서울경기", "수도권", "기호")),
    # 기상청 중기예보는 강원을 영서/영동으로 나눠 줌. 전통 지명이 그대로 표의 그룹명.
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


# 여러 광역 구역을 아우르는 말은 대표 구역으로 보냄 — 기상청에 대응하는 단일 페이지가 없음.
# (응답에는 어떤 구역으로 해석했는지 함께 적음 — 예보 자체가 그 구역 기준.)
WIDE_AREAS: dict[str, tuple[str, str]] = {
    # 별칭 → (대표 REGIONS key, 사용자에게 보여줄 설명)
    "중부": ("수도권", "중부지방은 서울·인천·경기 기준으로 보여드립니다"),
    "중부지방": ("수도권", "중부지방은 서울·인천·경기 기준으로 보여드립니다"),
    "남부": ("경남", "남부지방은 부산·울산·경남 기준으로 보여드립니다"),
    "남부지방": ("경남", "남부지방은 부산·울산·경남 기준으로 보여드립니다"),
    "영남": ("경남", "영남은 부산·울산·경남 기준으로 보여드립니다 (경북은 '경북')"),
    "호남": ("전남", "호남은 광주·전남 기준으로 보여드립니다 (전북은 '전북')"),
    "충청": ("충남", "충청은 대전·세종·충남 기준으로 보여드립니다 (충북은 '충북')"),
    "충청도": ("충남", "충청은 대전·세종·충남 기준으로 보여드립니다 (충북은 '충북')"),
    "영동": ("영동", ""),   # 영동/영서는 실제 구역이 있으므로 설명이 필요 없음
    "영서": ("영서", ""),
}


NATIONWIDE = REGIONS[0]


# 안내문에 쓰는 구역 목록. REGIONS 에서 만들어 구역을 추가해도 따로 고칠 일이 없음.
REGION_HELP = " · ".join(r.key for r in REGIONS)


def extract_region(text: str) -> tuple[Region | None, str]:
    """문장에서 지역을 집어냄. 조언 문장처럼 군더더기가 섞여 있어도 동작함.

    아는 지역 이름이 문장 안에 있는지 긴 이름부터 훑음 — '경기'보다 '경기도' 가 먼저 걸림.
    지우는 방식(정규식으로 조언어 제거)은 '무등산' 의 '등산' 까지 지워 버려 쓰지 않음.
    """
    flat = (text or "").replace(" ", "")
    if not flat:
        return NATIONWIDE, ""

    candidates: list[tuple[str, Region | None, str]] = []
    for name, (key, note) in WIDE_AREAS.items():
        region = next((r for r in REGIONS if r.key == key), None)
        candidates.append((name, region, note))
    for region in REGIONS:
        for name in (region.key, region.label.replace("·", ""), *region.aliases):
            candidates.append((name, region, ""))

    for name, region, note in sorted(candidates, key=lambda c: -len(c[0])):
        if name and name.replace(" ", "") in flat:
            return region, note
    return None, ""


def find_region(query: str | None) -> Region | None:
    """'부산', '영남', '중부' 같은 말에서 지역을 찾음. 못 찾으면 None."""
    region, _ = resolve_region(query)
    return region


def resolve_region(query: str | None) -> tuple[Region | None, str]:
    """지역과 함께 '어떻게 해석했는지' 안내문을 돌려줌.

    '중부'·'남부'·'영남'처럼 기상청에 대응하는 단일 페이지가 없는 말은 대표 구역으로
    보내되, 무엇으로 바꿔 읽었는지 안내문에 담음. 조용히 바꿔치기하면 사용자가
    자기가 물은 것과 다른 답을 받은 줄 모름.
    """
    if not query:
        return NATIONWIDE, ""
    text = query.strip().lower().replace(" ", "")
    if not text:
        return NATIONWIDE, ""

    def by_key(key: str) -> Region | None:
        return next((r for r in REGIONS if r.key == key), None)

    # 광역 표현을 먼저 봄 ('영동'처럼 실제 구역과 겹치는 말이 있어 순서가 중요함)
    for name, (key, note) in WIDE_AREAS.items():
        if text == name:
            return by_key(key), note

    for region in REGIONS:
        canon = {region.key, region.label}
        for name in (region.key, region.label, *region.aliases):
            if text == name.lower().replace(" ", "").replace("·", ""):
                # 도시 하나를 구역 전체로 답할 때는 그 사실을 밝힘('부산' → 부산·울산·경남).
                # 헤더에 구역 이름이 떠도 물은 대로 답했다고 읽기 쉽고, 기온 범위가
                # 남의 동네까지 아우른 값인 줄 모르면 «예보가 틀렸다» 로 읽힘.
                if name not in canon:
                    return region, (f"'{query.strip()}' 은 기상청 구역 "
                                    f"'{region.label}' 에 묶여 있어 그 기준으로 "
                                    "보여드립니다")
                return region, ""

    for name, (key, note) in WIDE_AREAS.items():
        if name in text:
            return by_key(key), note

    for region in REGIONS:
        for name in (region.key, *region.aliases):
            if name.lower() in text:
                return region, ""
    return None, ""
