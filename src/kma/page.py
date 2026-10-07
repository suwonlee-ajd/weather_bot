"""기상청 페이지 받기와 공통 파싱, 수집 결과의 모양."""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from src.common.config import KST, UA

log = logging.getLogger(__name__)

BASE = "https://www.weather.go.kr"


RANGE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*~\s*(-?\d+(?:\.\d+)?)")


DOM_RE = re.compile(r"(\d{1,2})\s*일")


ISSUED_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?(\d{1,2}):(\d{2})")


POP_RE = re.compile(r"(\d{1,3})\s*%")


class ScrapeError(RuntimeError):
    pass


@dataclass
class ScrapedDay:
    date: dt.date
    tmin_lo: float | None = None
    tmin_hi: float | None = None
    tmax_lo: float | None = None
    tmax_hi: float | None = None
    sky: str | None = None
    pop: int | None = None
    source: str = ""


@dataclass
class Narrative:
    title: str
    url: str
    issued_at: dt.datetime | None
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Scrape:
    days: dict[dt.date, ScrapedDay]
    narratives: list[Narrative]

    def as_text(self) -> str:
        blocks = []
        for n in self.narratives:
            stamp = f" ({n.issued_at:%m월 %d일 %H시} 발표)" if n.issued_at else ""
            blocks.append(f"[{n.title}{stamp}]\n{n.text}")
        return "\n\n".join(blocks)


def _get_soup(url: str, timeout: float = 25.0) -> BeautifulSoup:
    # 상태코드와 본문 크기를 로그에 남김 — 실패했을 때 기상청이 죽었는지 파서가
    # 깨졌는지 로그만 보고 갈라야 함. 200 인데 4KB 면 페이지 구조가 바뀐 것.
    started = time.monotonic()
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    except requests.RequestException as exc:
        log.warning("요청 실패 url=%s %.1fs %s: %s",
                    url, time.monotonic() - started, type(exc).__name__, exc)
        raise
    took = time.monotonic() - started
    if resp.status_code >= 400:
        log.warning("요청 실패 url=%s status=%d %dB %.1fs", url, resp.status_code, len(resp.content), took)
        resp.raise_for_status()
    log.debug("요청 성공 url=%s status=%d %dB %.1fs", url, resp.status_code, len(resp.content), took)
    resp.encoding = resp.apparent_encoding or "utf-8"
    return BeautifulSoup(resp.text, "lxml")


def _issued_at(soup: BeautifulSoup) -> dt.datetime | None:
    m = ISSUED_RE.search(soup.get_text(" ", strip=True))
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    try:
        return dt.datetime(y, mo, d, h, mi, tzinfo=KST)
    except ValueError:
        return None


def _resolve_date(day_of_month: int, ref: dt.date) -> dt.date | None:
    """'14일' 같은 표기를 기준일 근처의 실제 날짜로 되돌림 (월말/월초 넘어감 처리)."""
    for delta in range(-16, 17):
        cand = ref + dt.timedelta(days=delta)
        if cand.day == day_of_month:
            return cand
    return None


def _narrative_lines(soup: BeautifulSoup) -> list[str]:
    """□ / ○ 로 시작하는 예보관 서술만 뽑음."""
    text = soup.get_text("\n", strip=True)
    lines: list[str] = []
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if line.startswith(("□", "○")) and len(line) > 4:
            lines.append(line)
        elif lines and not line.startswith(("□", "○")) and len(line) > 8 and len(lines) <= 6:
            # 직전 줄에 붙임 — 서술이 <br> 로 이어지는 경우가 있음
            if lines[-1].endswith((",", "및")):
                lines[-1] += " " + line
    return lines
