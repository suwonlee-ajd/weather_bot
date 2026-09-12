"""1개월 전망 (주 단위 확률 예보).

10일 예보 너머를 묻는 질문 — "올해 겨울은", "다음 달 어때" — 에 답하기 위한 자료다.
일별 예보와 성격이 다르다는 점이 중요하다.

  일별 예보   "수요일 아침 13℃, 낮 30℃, 맑음"      → 값
  1개월 전망  "평년보다 높을 확률 50%"               → 확률

기상청이 매주 목요일 발표하며 4주치를 담는다. 그보다 먼 계절 단위(3개월)는
확률조차 주 단위가 아니라 월 단위라 여기서는 다루지 않고, 안내만 한다.

  https://www.weather.go.kr/repositary/xml/fct/mon/img/fct_mon1rss_108_{YYYYMMDD}.xml
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from .cache import get_or_set
from .config import KST

log = logging.getLogger(__name__)

URL = "https://www.weather.go.kr/repositary/xml/fct/mon/img/fct_mon1rss_108_{:%Y%m%d}.xml"
UA = "ajd-slack-weather-bot/1.0 (+internal Slack bot)"
TTL_SEC = 6 * 3600
LOOKBACK_DAYS = 21          # 매주 목요일 발표라 3주면 충분하다

# 전망 본문의 지역명은 예보 페이지와 표기가 다르다 (가운뎃점 대신 'ㆍ')
REGION_ALIAS = {
    "전국": "전국(제주도,북한제외)",
    "수도권": "서울ㆍ인천ㆍ경기도",
    "강원": "강원도 영서",
    "영서": "강원도 영서",
    "영동": "강원도 영동",
    "충남": "대전ㆍ세종ㆍ충청남도",
    "충북": "충청북도",
    "전남": "광주ㆍ전라남도",
    "전북": "전북자치도",
    "경남": "부산ㆍ울산ㆍ경상남도",
    "경북": "대구ㆍ경상북도",
    "제주": "제주도",
}


@dataclass
class WeekOutlook:
    period: str          # "09.14.~09.20."
    summary: str         # 예보관 서술 (기압계 흐름)
    temp_normal: str     # 평년 범위 "19.8~21.0"
    temp_odds: tuple[int, int, int]   # (낮음, 비슷, 높음) %
    rain_odds: tuple[int, int, int]

    @staticmethod
    def _verdict(odds: tuple[int, int, int], words: tuple[str, str, str]) -> str:
        low, same, high = odds
        top = max(odds)
        picks = [w for w, v in zip(words, odds) if v == top]
        return " 또는 ".join(picks) + f" 확률 {top}%"

    @property
    def temp_text(self) -> str:
        return self._verdict(self.temp_odds, ("낮을", "비슷할", "높을"))

    @property
    def rain_text(self) -> str:
        return self._verdict(self.rain_odds, ("적을", "비슷할", "많을"))


@dataclass
class Outlook:
    issued: str
    period: str          # "2026년 9월 14일 ~ 10월 11일"
    region: str
    weeks: list[WeekOutlook]
    url: str


class OutlookError(RuntimeError):
    pass


def _latest_xml(now: dt.datetime) -> tuple[ET.Element, str]:
    """가장 최근 발표본. 매주 목요일이라 하루씩 거슬러 올라가며 찾는다."""
    for back in range(LOOKBACK_DAYS):
        day = now.date() - dt.timedelta(days=back)
        url = URL.format(day)
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        except requests.RequestException:
            continue
        if resp.status_code == 200 and resp.content.startswith(b"<?xml"):
            try:
                return ET.fromstring(resp.content), url
            except ET.ParseError:
                continue
    raise OutlookError(f"최근 {LOOKBACK_DAYS}일 안에 1개월 전망 발표본을 찾지 못했습니다.")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _odds(body: ET.Element, prefix: str, region_tag: str, region: str) -> tuple[int, int, int]:
    """지역별 확률 3종. 같은 태그가 지역 수만큼 반복돼서 순서로 짚는다.

    body 아래가 summary/weather_forecast/onemonth_*_forecast 로 한 겹 더 중첩돼 있어
    findall(직계) 이 아니라 iter(전체) 로 찾는다.
    """
    names = [e.text for e in body.iter(region_tag)]
    try:
        idx = names.index(region)
    except ValueError:
        idx = 0
    out = []
    for suffix in ("minVal", "similarVal", "maxVal"):
        vals = [e.text for e in body.iter(f"{prefix}_{suffix}")]
        out.append(int(vals[idx]) if idx < len(vals) else 0)
    return tuple(out)  # type: ignore[return-value]


def fetch_outlook(region_key: str = "전국", now: dt.datetime | None = None) -> Outlook:
    """1개월 전망. 6시간 캐시한다 — 주 1회 갱신이라 자주 받을 이유가 없다."""
    now = now or dt.datetime.now(tz=KST)

    def build() -> Outlook:
        root, url = _latest_xml(now)
        desc = root.find("channel/item/description")
        if desc is None:
            raise OutlookError("1개월 전망 본문을 찾지 못했습니다.")
        header, body = desc.find("header"), desc.find("body")
        if header is None or body is None:
            raise OutlookError("1개월 전망 구조가 바뀌었습니다.")

        target = REGION_ALIAS.get(region_key, REGION_ALIAS["전국"])
        ta_names = [e.text for e in body.iter("local_ta_name")]
        idx = ta_names.index(target) if target in ta_names else 0

        weeks: list[WeekOutlook] = []
        for n in range(1, 5):
            period = _clean(next((e.text for e in body.iter(f"week{n}_period")), None))
            summary = _clean(next((e.text for e in body.iter(f"week{n}_weather_review")), None))
            if not period:
                continue
            ranges = [e.text for e in body.iter(f"week{n}_local_ta_similarRange")]
            weeks.append(WeekOutlook(
                period=period,
                # 확률 서술은 따로 보여주므로 기압계 흐름만 남긴다
                summary=summary.split("(주평균기온)")[0].strip(),
                temp_normal=(ranges[idx] if idx < len(ranges) else "") or "",
                temp_odds=_odds(body, f"week{n}_local_ta", "local_ta_name", target),
                rain_odds=_odds(body, f"week{n}_local_rn", "local_rn_name", target),
            ))
        if not weeks:
            raise OutlookError("1개월 전망에서 주간 항목을 읽지 못했습니다.")

        return Outlook(
            issued=_clean(header.findtext("ydate")),
            period=_clean(header.findtext("date")),
            region=target,
            weeks=weeks,
            url=url,
        )

    return get_or_set(f"outlook:{region_key}", TTL_SEC, build)
