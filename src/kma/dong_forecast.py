"""동네예보 RSS — 행정동 하나의 시간별 예보를 받아 날짜별로 묶음."""
from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from src.common.config import KST, UA

RSS_URL = "https://www.weather.go.kr/w/rss/dfs/hr1-forecast.do"


FORECAST_DAYS = 4  # 오늘 + 3일


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
            # 점이 모자란 끝자락 날은 버림 — 00시 한 점만 오는 날은 최저와 최고가
            # 같은 «22~22℃» 가 나와 하루 날씨처럼 읽히지 않음.
            if len(pts) < 4 and date != min(by_date):
                continue
            # 비·눈은 몇 시간만 있어도 그날의 날씨. 최빈값으로 고르면
            # 24시간 중 두 시간 오는 비가 «흐림» 에 묻혀 우산 조언까지 사라짐.
            wet = next((w for w in ("비", "눈", "소나기") for x in skies if w in x), None)
            out.append((
                date, min(temps), max(temps),
                next((x for x in skies if wet and wet in x), None)
                or (max(set(skies), key=skies.count) if skies else "-"),
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
    # 부르는 쪽이 이름을 정해 두었으면 그것을 씀 — '광주광역시' 를 기상청
    # 응답의 '전남광주통합특별시 북구' 로 되돌리면 물은 것과 다른 말이 됨.
    display = name or (title.split(" - ")[-1].strip() if " - " in title else name)
    return DongForecast(name=display, zone=zone, issued=issued, points=points)
