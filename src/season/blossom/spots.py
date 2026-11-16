"""벚꽃 지도의 웨더아이 19개 도시 — 좌표는 기상관서(ASOS), 웨더아이 예상이 기상관서 표준목 기준임."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Spot:
    name: str                       # 웨더아이 표의 도시 이름 그대로
    lat: float
    lon: float
    label: str = "r"                # 지도 라벨이 점의 어느 쪽에 붙는지 r/l/t/b


# 라벨은 «도시 날짜» 라 이름만 적는 첫눈 지도보다 넓음 — 옆 라벨과 울릉도 상자를 피해 방향을 정함
CITIES: tuple[Spot, ...] = (
    Spot("춘천", 37.90, 127.74, "t"),
    Spot("강릉", 37.75, 128.89, "t"),
    Spot("서울", 37.57, 126.97),
    Spot("인천", 37.48, 126.62, "l"),
    Spot("수원", 37.27, 126.99),
    Spot("서산", 36.78, 126.49, "l"),
    Spot("청주", 36.64, 127.44, "t"),
    Spot("안동", 36.57, 128.71),
    Spot("대전", 36.37, 127.37),
    Spot("포항", 36.03, 129.38),
    Spot("대구", 35.88, 128.65, "l"),
    Spot("전주", 35.82, 127.16, "l"),
    Spot("울산", 35.56, 129.32),
    Spot("창원", 35.17, 128.57, "l"),
    Spot("부산", 35.10, 129.03),
    Spot("광주", 35.17, 126.89, "l"),
    Spot("목포", 34.82, 126.38, "l"),
    Spot("여수", 34.74, 127.74, "b"),
    Spot("서귀포", 33.25, 126.57),
)

CITY_BY_NAME = {s.name: s for s in CITIES}
