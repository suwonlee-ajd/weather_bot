"""벚꽃 — 기상청 봄꽃 관측 중인지(다룰 때인지만)와 웨더아이 개화 예상일(19개 도시).

기상청은 관측만 하고 예보하지 않음. 예상일은 웨더아이 「YYYY년 벚꽃 개화예상시기」 첨부 PDF 의 [첨부1] 표.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass

import requests

from src.season import sources as shared

log = logging.getLogger(__name__)

KMA_URL = "https://www.kma.go.kr/kma/theme/flower_photojs.jsp"
KMA_PAGE = "https://www.weather.go.kr/w/forecast/life/seasonal-observation/spring-flower.do"

# 형식 변경 감지 문턱 — 해마다 19곳
_MIN_ROWS = 15


class BlossomError(RuntimeError):
    pass


def _get(url: str, **kw) -> requests.Response:
    return shared.get(url, error=BlossomError, **kw)


# --- 기상청 관측 -------------------------------------------------------------

def parse_status(text: str) -> bool:
    """서비스 중인지(isService). 군락지 목록이 비었거나 꼴이 다르면 형식 변경."""
    data = shared.jsonp(text, "applyFlowerData", "봄꽃", BlossomError)
    places = data.get("places")
    if not places or not all(isinstance(p, dict) for p in places):
        raise BlossomError("기상청 봄꽃 응답에 관측 지점이 없습니다 (형식 변경 의심)")
    return bool(data.get("isService"))


def _kma() -> str:
    resp = _get(KMA_URL, params={"treeType": "1", "obsPlace": ""}, referer=KMA_PAGE)
    resp.encoding = "utf-8"
    return resp.text


def fetch_status() -> bool:
    """기상청이 봄꽃을 관측 중인지 — 목록 한 번. 군락지별 촬영일은 싣지 않아 받지 않음."""
    return parse_status(_kma())


# --- 웨더아이 예상 -----------------------------------------------------------

@dataclass
class Outlook:
    expected: dict[str, dt.date]    # 지난해 표를 빌렸으면 비어 있음
    normal: dict[str, dt.date]      # 평년 개화일, 올해 날짜로 옮겨 둠
    published: dt.date | None = None
    url: str = ""

    def gap_days(self) -> float | None:
        """평년 대비 도시 평균 날수 — 이르면 음수."""
        gaps = [(d - self.normal[c]).days for c, d in self.expected.items() if c in self.normal]
        return sum(gaps) / len(gaps) if gaps else None


# 도시  예상일  평년(평년차)  작년(편차). 날짜는 '3.24'·'4. 1'(~2024), '3/25'(2025~).
# 군락지 줄('진해 여좌천 3/27 …')은 이름이 두 낱말이라 걸리지 않음.
_DAY = r"(\d{1,2})\s*[/.]\s*(\d{1,2})"
_ROW = re.compile(rf"^\s*([가-힣]{{2,3}})\s+{_DAY}\s+{_DAY}\s*\(")


def parse_outlook_text(text: str, year: int) -> tuple[dict[str, dt.date], dict[str, dt.date]]:
    """도시별 (개화 예상일, 평년 개화일). 조금이라도 어긋나면 통째로 버림 — 그럴듯한 오독은 알아채기 어려움."""
    expected: dict[str, dt.date] = {}
    normal: dict[str, dt.date] = {}
    lo, hi = dt.date(year, 3, 1), dt.date(year, 4, 30)
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        city = m.group(1)
        try:
            e = dt.date(year, int(m.group(2)), int(m.group(3)))
            n = dt.date(year, int(m.group(4)), int(m.group(5)))
        except ValueError as exc:
            raise BlossomError(f"웨더아이 표의 {city} 날짜가 이상합니다: {line.strip()}") from exc
        if not (lo <= e <= hi and lo <= n <= hi):
            raise BlossomError(f"웨더아이 표의 {city} 날짜가 범위를 벗어났습니다: {line.strip()}")
        expected[city], normal[city] = e, n
    if len(expected) < _MIN_ROWS:
        raise BlossomError(f"웨더아이 표에서 도시를 {len(expected)}곳밖에 읽지 못했습니다 (형식 변경 의심)")
    return expected, normal


def _find_post(list_html: str, year: int) -> str | None:
    return shared.find_post(list_html, year, r"벚꽃\s*개화예상시기")


def _load_post(list_html: str, year: int) -> Outlook | None:
    post_url = _find_post(list_html, year)
    if post_url is None:
        return None
    post = _get(post_url)
    post.encoding = "utf-8"
    pdf_url = shared.pdf_link(post.text)
    if not pdf_url:
        raise BlossomError(f"웨더아이 {year}년 벚꽃 게시물에 PDF 가 없습니다: {post_url}")
    expected, normal = parse_outlook_text(shared.pdf_text(_get(pdf_url, timeout=30).content, BlossomError), year)
    return Outlook(expected=expected, normal=normal, published=shared.posted_on(post.text, year), url=post_url)


def fetch_outlook(year: int, *, borrow_normal: bool = True) -> Outlook:
    """없으면 지난해 표의 평년만(borrow_normal) — 발표(2/21~28)가 관측 시작과 엇갈림. 실패는 «없음» 과 섞지 않고 BlossomError."""
    listing = _get(shared.WEATHERI_LIST)
    listing.encoding = "utf-8"
    outlook = _load_post(listing.text, year)
    if outlook is not None:
        log.info("웨더아이 %d년 벚꽃 예상 %d곳 (%s 발표)", year, len(outlook.expected), outlook.published)
        return outlook
    if not borrow_normal:
        return Outlook(expected={}, normal={})
    log.info("웨더아이 %d년 벚꽃 예상이 아직 없어 지난해 표의 평년을 씁니다", year)
    last = _load_post(listing.text, year - 1)
    if last is None:
        return Outlook(expected={}, normal={})
    return Outlook(expected={}, normal={c: d.replace(year=year) for c, d in last.normal.items()},
                   url=last.url)


def showing(in_service: bool, outlook: Outlook, day: dt.date) -> bool:
    """다룰 때인지 — 기상청이 관측 중(isService)이거나, 관측 전이라도 올해 첫 개화 예상일이 아직 오지 않았을 때.

    기간은 우리가 정하지 않고 자료가 정함 — 서울·인천처럼 4월에 피는 곳까지 기상청 관측을 따라감. 관측 전은 첫
    예상일까지만: 그 뒤에 서비스가 꺼져 있으면 접은 것이라 «아직 시작 안 함» 이라고 말하지 않게.
    """
    return in_service or (bool(outlook.expected) and min(outlook.expected.values()) >= day)
