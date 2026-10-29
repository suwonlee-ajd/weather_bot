"""기상청이 첫눈을 관측하는 24곳(계절관측 지점). 2015년부터 교대근무 관서만 눈·서리·얼음을 관측함."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    name: str                          # 계절관측 표기
    stn: str
    lat: float                         # 기상청 ASOS 지점 좌표
    lon: float
    normal: tuple[int, int] | None     # 평년 첫눈 (월, 일). 홍성은 평년이 없음
    regions: tuple[str, ...]           # 광역 구역 키(kma.regions)
    sido: str                          # 동네예보 행정동코드 앞 2자리
    aliases: tuple[str, ...] = ()
    label: str = "r"                   # 지도 라벨이 점의 어느 쪽에 붙는지 r/l/t/b


STATIONS: tuple[Station, ...] = (
    Station("속초", "90", 38.25, 128.56, (12, 10), ("강원", "영동"), "51"),
    Station("백령도", "102", 37.97, 124.63, (11, 18), ("수도권",), "28", ("백령",)),
    Station("북춘천", "93", 37.95, 127.75, (11, 21), ("강원", "영서"), "51", ("춘천",)),
    Station("북강릉", "104", 37.80, 128.86, (12, 7), ("강원", "영동"), "51", ("강릉",)),
    Station("서울", "108", 37.57, 126.97, (11, 20), ("수도권",), "11"),
    Station("인천", "112", 37.48, 126.62, (11, 23), ("수도권",), "28", label="l"),
    Station("울릉도", "115", 37.48, 130.90, (11, 16), ("경북",), "47", ("울릉",)),
    Station("수원", "119", 37.27, 126.99, (11, 21), ("수도권",), "41"),
    Station("홍성", "177", 36.66, 126.69, None, ("충남",), "44", label="l"),
    Station("청주", "131", 36.64, 127.44, (11, 23), ("충북",), "43"),
    Station("안동", "136", 36.57, 128.71, (11, 29), ("경북",), "47"),
    Station("대전", "133", 36.37, 127.37, (11, 20), ("충남",), "30", label="b"),
    Station("포항", "138", 36.03, 129.38, (12, 18), ("경북",), "47"),
    Station("대구", "143", 35.88, 128.65, (12, 5), ("경북",), "27", label="l"),
    Station("전주", "146", 35.82, 127.16, (11, 29), ("전북",), "52"),
    Station("울산", "152", 35.56, 129.32, (12, 24), ("경남",), "31"),
    Station("광주", "156", 35.17, 126.89, (11, 29), ("전남",), "29"),
    Station("창원", "155", 35.17, 128.57, (12, 27), ("경남",), "48", label="l"),
    Station("부산", "159", 35.10, 129.03, (12, 23), ("경남",), "26", label="b"),
    Station("목포", "165", 34.82, 126.38, (11, 29), ("전남",), "46", label="l"),
    Station("여수", "168", 34.74, 127.74, (12, 13), ("전남",), "46", label="b"),
    Station("흑산도", "169", 34.69, 125.45, (12, 1), ("전남",), "46", ("흑산",), "b"),
    Station("제주", "184", 33.51, 126.53, (12, 10), ("제주",), "50", label="t"),
    Station("서귀포", "189", 33.25, 126.57, (12, 20), ("제주",), "50"),
)

BY_NAME = {s.name: s for s in STATIONS}


def stations_in_region(key: str) -> tuple[Station, ...]:
    return tuple(s for s in STATIONS if key in s.regions)


def stations_in_zone(code: str) -> tuple[Station, ...]:
    """동네예보 코드의 시도 안 지점. 세종처럼 관측 지점이 없는 시도는 비어 있음."""
    return tuple(s for s in STATIONS if s.sido == code[:2])


def find_station(text: str) -> Station | None:
    flat = text.replace(" ", "")
    names = sorted(((n, s) for s in STATIONS for n in (s.name, *s.aliases)), key=lambda p: -len(p[0]))
    return next((s for n, s in names if n in flat), None)
