"""벚꽃 지도의 웨더아이 19개 도시 — 좌표는 places(기상관서), 웨더아이 예상이 기상관서 표준목 기준임."""
from __future__ import annotations

from src.season.places import Spot, spot

# 라벨은 «도시 날짜» 라 이름만 적는 첫눈 지도보다 넓음 — 옆 라벨과 울릉도 상자를 피해 방향을 정함
CITIES: tuple[Spot, ...] = (
    spot("춘천", "t"), spot("강릉", "t"), spot("서울"), spot("인천", "l"), spot("수원"), spot("서산", "l"),
    spot("청주", "t"), spot("안동"), spot("대전"), spot("포항"), spot("대구", "l"), spot("전주", "l"),
    spot("울산"), spot("창원", "l"), spot("부산"), spot("광주", "l"), spot("목포", "l"), spot("여수", "b"),
    spot("서귀포"),
)

CITY_BY_NAME = {s.name: s for s in CITIES}
