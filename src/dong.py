"""동네예보(동 단위) 조회.

기상청 날씨누리가 행정동 코드로 1시간 단위 예보를 내주는 RSS 가 아직 살아 있다.
표준 행정동코드 10자리를 그대로 쓴다 (예: 1168064000 = 서울 강남구 역삼1동).

    https://www.weather.go.kr/w/rss/dfs/hr1-forecast.do?zone=<행정동코드>

한계 두 가지를 분명히 해 둔다.
  1. **오늘~+3일**까지만 나온다. 주간(7일) 예보는 광역 구역(src/kma_scrape.py)으로만 가능하다.
  2. 이 엔드포인트는 2025-03-31 폐지 공지가 났던 경로다. 지금은 응답하지만 언제든 끊길 수
     있으므로, 실패하면 광역 예보로 안내하고 넘어간다 — 동 단위가 안 된다고 게시를 막지 않는다.

동 이름 → 코드 변환은 날씨누리의 지역 목록 API(/w/rest/zone/dong.do)를 그때그때 호출한다.
행정동은 통폐합·신설이 계속 있어 스냅샷을 리포에 두면 조용히 낡기 때문이다.
"""
from __future__ import annotations

import datetime as dt
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from .cache import get_or_set
from .config import KST

log = logging.getLogger(__name__)

RSS_URL = "https://www.weather.go.kr/w/rss/dfs/hr1-forecast.do"
UA = "ajd-slack-weather-bot/1.0 (+internal Slack bot)"
FORECAST_DAYS = 4  # 오늘 + 3일

ZONE_URL = "https://www.weather.go.kr/w/rest/zone/dong.do"

# 행정동은 통폐합·신설이 계속 있어 스냅샷을 리포에 두면 조용히 낡는다.
# 기상청에 그때그때 물어보고, 프로세스 안에서만 잠깐 들고 있는다.
ZONE_TTL_SEC = 24 * 3600

# 시/도를 짧게 부르는 말. "서울 강남" 처럼 앞에 붙여 동명이인을 가려낼 때 쓴다.
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


def _candidate_cities(text: str) -> list[tuple[dict, dict]]:
    """입력에서 시/도·시군구를 짚어 후보 (시도, 시군구) 목록을 만든다.

    전국 동을 다 받아오면 3,500건이 넘는다. 시/도와 시군구 목록만으로 범위를 좁힌 뒤
    해당 구역의 동만 받아온다 — 보통 요청 2~3번으로 끝난다.
    """
    wides = get_or_set("zone:wide", ZONE_TTL_SEC, lambda: _zone("WIDE"))
    rest = text

    # "서울 …" 처럼 시/도가 앞에 붙어 있으면 그 안에서만 찾는다
    scoped = None
    for alias, full in WIDE_ALIASES.items():
        if rest.startswith(alias) and len(rest) > len(alias):
            scoped, rest = full, rest[len(alias):]
            break

    pairs: list[tuple[dict, dict]] = []
    for wide in wides:
        if scoped and wide["name"] != scoped:
            continue
        cities = get_or_set(
            f"zone:city:{wide['code']}", ZONE_TTL_SEC,
            lambda w=wide: _zone("CITY", w["code"]),
        )
        for city in cities:
            name = _normalize(city["name"])
            # '성남시분당구' 처럼 합쳐진 이름은 앞 토막('성남')만 줘도 걸리게 한다
            heads = {name} | {name.split(cut)[0] for cut in ("시", "군", "구") if cut in name}
            if any(h and (rest.startswith(h) or h.startswith(rest)) for h in heads if h):
                pairs.append((wide, city))
    return pairs


def _all_dongs() -> list[Dong]:
    """전국 행정동. 하루 한 번만 받아 프로세스 안에 들고 있는다.

    기상청 지역 API 는 keyword 검색을 지원하지 않아, 동 이름만 주어졌을 땐 전국을
    훑는 수밖에 없다. 요청이 250번쯤 나가므로 캐시가 사실상 필수다. 리포에 스냅샷을
    두지 않는 이유는 행정동이 계속 바뀌기 때문이다 — 하루면 충분히 최신이다.
    """
    def build() -> list[Dong]:
        out: list[Dong] = []
        for wide in _zone("WIDE"):
            for city in _zone("CITY", wide["code"]):
                out += _dongs_in(wide, city)
        log.info("전국 행정동 %d건 수집", len(out))
        return out

    return get_or_set("zone:all", ZONE_TTL_SEC, build)


def search_dong(query: str, limit: int = 5) -> list[Dong]:
    """가장 가까운 행정동 후보를 점수순으로 돌려준다.

    '강남' 처럼 구 이름만 줘도 그 구의 동을 찾고, 앞에 시/도나 시군구를 붙이면
    ('강릉 강남') 동명이인을 가려낸다.
    """
    text = _normalize(query)
    if not text:
        return []

    try:
        pairs = _candidate_cities(text)
        pool: list[Dong] = []
        for wide, city in pairs[:6]:
            pool += get_or_set(
                f"zone:dong:{city['code']}", ZONE_TTL_SEC,
                lambda w=wide, c=city: _dongs_in(w, c),
            )
        if not pool:
            pool = _all_dongs()          # 동 이름만 준 경우 (역삼, 봉담 …)
    except (requests.RequestException, ValueError) as exc:
        log.warning("행정동 조회 실패: %s", exc)
        return []

    stripped = text
    for alias in WIDE_ALIASES:
        if stripped.startswith(alias) and len(stripped) > len(alias):
            stripped = stripped[len(alias):]
            break
    # 시군구 이름까지 떼어내야 "성남 판교" 의 '판교' 로 동을 고를 수 있다
    for _, city in pairs:
        name = _normalize(city["name"])
        heads = {name} | {name.split(cut)[0] for cut in ("시", "군", "구") if cut in name}
        for head in sorted((h for h in heads if h), key=len, reverse=True):
            if stripped.startswith(head) and len(stripped) > len(head):
                stripped = stripped[len(head):]
                break
        else:
            continue
        break

    scored: list[tuple[int, Dong]] = []
    for d in pool:
        name, city = _normalize(d.name), _normalize(d.city)
        if stripped == name:
            score = 0
        elif name.startswith(stripped):
            score = 1
        elif stripped in name:
            score = 2
        elif city.startswith(stripped) or stripped.startswith(city.rstrip("시군구")):
            # 구 이름만 준 경우('강남'). 같은 이름을 가진 동이 있으면 그쪽을 대표로 삼는다
            score = 3 if stripped not in name else 2
        elif pairs:
            score = 4        # 시군구로 좁혀진 결과라 후보로 남긴다
        else:
            continue         # 전국을 훑는 중이면 무관한 동까지 담지 않는다
        scored.append((score, d))

    scored.sort(key=lambda pair: (pair[0], pair[1].full_name))
    hits = [d for _, d in scored[:limit]]

    # '역삼동' 의 실제 행정동은 '역삼1동'/'역삼2동' 이다. 접미사를 떼고 한 번 더 본다.
    if not hits and len(text) > 2 and text[-1] in "동읍면":
        return search_dong(text[:-1], limit)
    return hits


def find_dong(query: str) -> tuple[str, str] | None:
    """가장 가까운 동 하나. 행정동코드 10자리를 직접 줘도 받는다."""
    text = _normalize(query)
    if text.isdigit() and len(text) == 10:
        return text, text
    hits = search_dong(query, limit=1)
    return (hits[0].code, hits[0].full_name) if hits else None


@dataclass
class HourlyPoint:
    when: dt.datetime
    temp: float | None
    sky: str | None
    pop: int | None
    reh: int | None


@dataclass
class DongForecast:
    name: str
    zone: str
    issued: str
    points: list[HourlyPoint]

    def daily_summary(self) -> list[tuple[dt.date, float, float, str, int]]:
        """(날짜, 최저, 최고, 대표 하늘상태, 최대 강수확률)."""
        by_date: dict[dt.date, list[HourlyPoint]] = {}
        for p in self.points:
            by_date.setdefault(p.when.date(), []).append(p)
        out = []
        for date in sorted(by_date):
            pts = by_date[date]
            temps = [p.temp for p in pts if p.temp is not None]
            skies = [p.sky for p in pts if p.sky]
            pops = [p.pop for p in pts if p.pop is not None]
            if not temps:
                continue
            out.append((
                date, min(temps), max(temps),
                max(set(skies), key=skies.count) if skies else "-",
                max(pops) if pops else 0,
            ))
        return out


class DongError(RuntimeError):
    pass


def fetch_dong(zone: str, name: str, timeout: float = 20.0) -> DongForecast:
    try:
        resp = requests.get(RSS_URL, params={"zone": zone},
                            headers={"User-Agent": UA}, timeout=timeout)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as exc:
        raise DongError(f"동네예보를 가져오지 못했습니다: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise DongError("동네예보 응답 형식이 바뀌었습니다.")
    title = channel.findtext("title") or name
    issued = channel.findtext("pubDate") or ""
    body = channel.find("item/description/body")
    if body is None:
        raise DongError("동네예보 본문을 찾지 못했습니다.")

    base = dt.datetime.now(tz=KST).replace(hour=0, minute=0, second=0, microsecond=0)
    points: list[HourlyPoint] = []
    for data in body.findall("data"):
        def num(tag, cast=float):
            raw = data.findtext(tag)
            try:
                v = cast(raw)
            except (TypeError, ValueError):
                return None
            return None if v <= -900 else v

        day, hour = data.findtext("day"), data.findtext("hour")
        if day is None or hour is None:
            continue
        when = base + dt.timedelta(days=int(day), hours=int(hour))
        points.append(HourlyPoint(
            when=when, temp=num("temp"), sky=data.findtext("wfKor"),
            pop=num("pop", int), reh=num("reh", int),
        ))

    if not points:
        raise DongError("동네예보에 시간별 값이 없습니다.")
    display = title.split(" - ")[-1].strip() if " - " in title else name
    return DongForecast(name=display, zone=zone, issued=issued, points=points)
