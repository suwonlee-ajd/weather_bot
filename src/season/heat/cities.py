"""더위 지도의 도시 — 기상청 중기예보 기온 표의 41곳(전국 페이지 기준). 좌표는 기상관서·시청 근처.

벚꽃 도시·첫눈 지점과 이름이 같은 곳은 그 좌표를 씀. 라벨 방향은 먼저 해 볼 자리만 — 겹치면 지도가 다른 자리를
찾거나 라벨을 뺌(heat.map).
"""
from __future__ import annotations

from src.season.blossom.spots import CITY_BY_NAME, Spot
from src.season.snow.stations import BY_NAME as STATION_BY_NAME

_EXTRA: dict[str, tuple[float, float]] = {
    "파주": (37.89, 126.77), "이천": (37.26, 127.48), "평택": (36.99, 127.11), "원주": (37.34, 127.95),
    "세종": (36.49, 127.24), "충주": (36.97, 127.95), "영동": (36.17, 127.78), "순천": (34.95, 127.49),
    "광양": (34.94, 127.70), "나주": (35.02, 126.71), "군산": (36.00, 126.76), "정읍": (35.56, 126.87),
    "남원": (35.41, 127.33), "고창": (35.43, 126.70), "무주": (36.01, 127.66), "진주": (35.16, 128.04),
    "거창": (35.67, 127.91), "통영": (34.85, 128.44), "경주": (35.82, 129.20), "울진": (36.99, 129.41),
}

# 기본은 오른쪽(r). 점이 붙은 수도권·전라·경남에서 이웃을 피하는 쪽
SIDE: dict[str, str] = {
    "파주": "t", "인천": "l", "수원": "l", "평택": "b", "홍성": "l", "춘천": "t", "강릉": "t",
    "세종": "l", "군산": "l", "고창": "l", "나주": "l", "목포": "l", "순천": "l", "여수": "b",
    "창원": "t", "진주": "l", "거창": "l", "대구": "l", "제주": "t", "울릉도": "l",
}


def _spot(name: str) -> Spot | None:
    if (city := CITY_BY_NAME.get(name)) is not None:
        lat, lon = city.lat, city.lon
    elif (station := STATION_BY_NAME.get(name)) is not None:
        lat, lon = station.lat, station.lon
    elif name in _EXTRA:
        lat, lon = _EXTRA[name]
    else:
        return None
    return Spot(name, lat, lon, SIDE.get(name, "r"))


NAMES = ("서울", "인천", "수원", "파주", "이천", "평택", "춘천", "원주", "강릉", "대전", "세종", "홍성",
         "청주", "충주", "영동", "광주", "목포", "여수", "순천", "광양", "나주", "전주", "군산", "정읍",
         "남원", "고창", "무주", "부산", "울산", "창원", "진주", "거창", "통영", "대구", "안동", "포항",
         "경주", "울진", "울릉도", "제주", "서귀포")

SPOTS: dict[str, Spot] = {name: spot for name in NAMES if (spot := _spot(name))}
