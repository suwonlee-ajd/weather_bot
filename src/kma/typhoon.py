"""기상청 태풍정보 — 진행 중인 태풍의 현재 위치·중심기압·최대풍속과 예상 위치.

날씨누리 태풍 지도(typhoon_02.jsp)가 읽는 정적 파일을 받음 — 목록 RTKO63.tbl 과 태풍마다 경로표 .osp(CSV).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import urllib.parse
from dataclasses import dataclass

import requests

from src.common.cache import get_or_set
from src.common.config import KST, UA
from src.common.text import short_day_label
from src.kma.page import BASE

log = logging.getLogger(__name__)

# 열대저압부 목록(RTKO64)은 읽지 않음 — 이름이 붙은 태풍만 다룸
LIST_URL = f"{BASE}/w/repositary/xml/typ/raw/DAOU/RTKO63/RTKO63.tbl"
TIMEOUT_SEC = 10.0
TTL_SEC = 1800
RETRY_SEC = 120
# 경로표 한 줄 19칸 — 칸 뜻은 날씨누리 typhoonContent.js(loadTyphoon) 그대로
_AT, _LAT, _LON, _PLACE, _PRESSURE, _WIND, _KIND, _RADIUS, _LINKED = 0, 1, 2, 3, 6, 7, 8, 15, 18
_FIELDS = 19
# 날씨누리 지도가 약화된 태풍에 붙이는 문구 그대로 — 종류 칸이나 연관 칸의 «-END» 로 앎
_WEAKENED = {"TD": "열대저압부로 약화", "LOW": "온대저기압으로 변질"}


class TyphoonError(RuntimeError):
    pass


@dataclass(frozen=True)
class Point:
    at: dt.datetime
    place: str                  # «괌 남동쪽 약 1370 km 부근 해상»
    pressure: int | None        # 중심기압 hPa
    wind: int | None            # 최대풍속 m/s

    @property
    def when(self) -> str:
        return f"{short_day_label(self.at.date())} {self.at.hour}시"

    @property
    def summary(self) -> str:
        parts = (self.place, self.pressure and f"중심기압 {self.pressure}hPa", self.wind and f"최대풍속 {self.wind}m/s")
        return " · ".join(p for p in parts if p)


@dataclass(frozen=True)
class Typhoon:
    year: int
    no: int
    name: str
    en_name: str
    issued: dt.datetime | None          # 발표시각 — 경로표 파일 이름에만 있음
    now: Point
    forecast: tuple[Point, ...] = ()
    weakened: str = ""

    @property
    def title(self) -> str:
        return f"제{self.no}호 태풍 {self.name}" + (f"({self.en_name})" if self.en_name else "")


def _not_html(text: str, what: str) -> None:
    # 없는 경로도 404 가 아니라 200 + HTML 오류 페이지가 옴
    if text.lstrip().startswith("<"):
        raise TyphoonError(f"기상청 {what} 자리에 HTML 이 왔습니다 (경로 변경 의심)")


def parse_list(text: str) -> list[str]:
    """경로표 주소들. 한 줄이 «경로표,진로선» 이고 진행 중인 태풍이 없으면 빈 응답(200, 0바이트)."""
    _not_html(text, "태풍 목록")
    urls = []
    for line in filter(None, (raw.strip() for raw in text.splitlines())):
        osp = line.split(",")[0].strip()
        if ".osp" not in osp:
            raise TyphoonError(f"기상청 태풍 목록 줄을 읽지 못했습니다 (형식 변경 의심): {line[:80]}")
        # 목록은 /repositary/… 로 주지만 실제 자리는 /w/repositary/… — 날씨누리 지도도 같게 바꿈
        urls.append(urllib.parse.urljoin(BASE, re.sub(r"^/repositary/", "/w/repositary/", osp)))
    return urls


def issued_of(url: str) -> dt.datetime | None:
    m = re.search(r"RTKO63_(\d{12})", url)
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d%H%M").replace(tzinfo=KST) if m else None
    except ValueError:                  # 발표시각은 출처 줄에만 씀 — 못 읽으면 빼고 실음
        return None


def _number(raw: str) -> float | None:
    try:
        return float(raw)
    except ValueError:
        return None


def _usable(row: list[str]) -> bool:
    """날씨누리 지도와 같은 기준 — 19칸이고 시각·위경도가 있음. 뒤에 붙는 빈 줄(,,,,…)을 거름."""
    if len(row) < _FIELDS or not row[_AT].strip():
        return False
    return all((v := _number(row[i])) is not None and v > -999 for i in (_LAT, _LON))


def _point(row: list[str]) -> Point:
    try:
        at = dt.datetime.strptime(row[_AT].strip(), "%Y%m%d%H%M").replace(tzinfo=KST)
    except ValueError as exc:
        raise TyphoonError(f"기상청 태풍 경로표의 시각을 읽지 못했습니다: {row[_AT]!r}") from exc
    # 빈 칸·0·-999 는 값 없음
    pressure, wind = (int(v) if (v := _number(row[i])) and v > 0 else None for i in (_PRESSURE, _WIND))
    return Point(at, row[_PLACE].strip(), pressure, wind)


def _is_forecast(row: list[str]) -> bool:
    # 70% 확률반경이 비었거나 0보다 크면 예상, 0 이면 지난·현재 위치 — 날씨누리 지도의 구분
    radius = row[_RADIUS].strip()
    return not radius or (_number(radius) or 0) > 0


def _weakened(row: list[str]) -> str:
    linked = row[_LINKED].strip()
    if linked.endswith("-END"):
        return _WEAKENED.get(linked.removesuffix("-END"), "")
    # 연관 칸이 찬 줄은 태풍이 되기 전의 열대저압부 — 약화가 아님
    return "" if linked else _WEAKENED.get(row[_KIND].strip(), "")


def parse_track(text: str, issued: dt.datetime | None = None) -> Typhoon:
    """첫 줄 «연도,번호,이름,영문 이름», 다음 줄부터 시각순 위치. 현재는 예상 앞의 마지막 위치."""
    _not_html(text, "태풍 경로표")
    lines = text.splitlines()
    head = [c.strip() for c in lines[0].split(",")] if lines else []
    if len(head) < 4 or not (head[0].isdigit() and head[1].isdigit()) or not head[2]:
        raise TyphoonError(f"기상청 태풍 경로표 머리를 읽지 못했습니다 (형식 변경 의심): {head[:4]}")
    rows = [row for line in lines[1:] if _usable(row := line.split(","))]
    observed = [row for row in rows if not _is_forecast(row)]
    if not observed:
        raise TyphoonError(f"기상청 태풍 경로표에 현재 위치가 없습니다 ({head[2]})")
    now = _point(observed[-1])          # 같은 시각이 두 줄이면 뒤의 것 — 날씨누리 지도도 뒤의 것을 씀
    forecast = tuple(p for row in rows if _is_forecast(row) and (p := _point(row)).at > now.at)
    return Typhoon(int(head[0]), int(head[1]), head[2], head[3], issued, now, forecast, _weakened(observed[-1]))


def _decode(raw: bytes) -> str:
    # 경로표 한글의 인코딩은 진행 중인 태풍이 없을 때 만들어 확인하지 못함 — UTF-8 이 아니면 CP949
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


def _get(url: str, timeout: float) -> str:
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise TyphoonError(f"요청 실패 {url}: {exc}") from exc
    return _decode(resp.content)


def _load(timeout: float) -> list[Typhoon]:
    storms = [parse_track(_get(url, timeout), issued_of(url)) for url in parse_list(_get(LIST_URL, timeout))]
    log.info("기상청 태풍정보 — 진행 중 %d개%s", len(storms), "".join(f" · {t.title}" for t in storms))
    return storms


def fetch_active(*, timeout: float = TIMEOUT_SEC) -> list[Typhoon]:
    """진행 중인 태풍. 없으면 빈 목록 — 받지 못했거나 형식이 바뀌었으면 TyphoonError."""
    return get_or_set("typhoon-active", TTL_SEC, lambda: _load(timeout),
                      errors=(TyphoonError,), error_ttl=RETRY_SEC)
