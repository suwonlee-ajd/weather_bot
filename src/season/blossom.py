"""벚꽃 — 기상청 군락지 관측(13곳)과 웨더아이 개화 예상일(19개 도시).

기상청은 관측만 하고 예보하지 않음. 예상일은 웨더아이 「YYYY년 벚꽃 개화예상시기」 첨부 PDF 의 [첨부1] 표.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field

import requests

from src.common.text import bold, short_date
from src.season import sources as shared
from src.season.sources import OUTLOOK_SOURCE

log = logging.getLogger(__name__)

KMA_URL = "https://www.kma.go.kr/kma/theme/flower_photojs.jsp"
KMA_PAGE = "https://www.weather.go.kr/w/forecast/life/seasonal-observation/spring-flower.do"

STAGES = ("개화 전", "개화", "만발")
NOT_STARTED_TEXT = "기상청 벚꽃 관측이 아직 시작되지 않았습니다 (해마다 3월부터)"
NOT_PUBLISHED_TEXT = f"올해 개화 예상은 아직 나오지 않았습니다 ({OUTLOOK_SOURCE}, 해마다 2월 말 발표)"

# 형식 변경 감지 문턱 — 해마다 19곳
_MIN_ROWS = 15


class BlossomError(RuntimeError):
    pass


# --- 기간 ------------------------------------------------------------------

def _last_monday(year: int, month: int) -> dt.date:
    last = dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)
    return last - dt.timedelta(days=last.weekday())


def season_bounds(year: int) -> tuple[dt.date, dt.date]:
    """2월 마지막 월요일 ~ 3월 마지막 월요일이 든 주의 일요일."""
    return _last_monday(year, 2), _last_monday(year, 3) + dt.timedelta(days=6)


def in_season(day: dt.date) -> bool:
    start, end = season_bounds(day.year)
    return start <= day <= end


def _get(url: str, **kw) -> requests.Response:
    return shared.get(url, error=BlossomError, **kw)


# --- 기상청 관측 -------------------------------------------------------------

@dataclass
class Status:
    stages: dict[str, int]                                   # 군락지 → 0 개화 전 / 1 개화 / 2 만발
    bloom: dict[str, dt.date] = field(default_factory=dict)
    full: dict[str, dt.date] = field(default_factory=dict)
    in_service: bool = True


def _jsonp(text: str) -> dict:
    return shared.jsonp(text, "applyFlowerData", "봄꽃", BlossomError)


def parse_status(text: str) -> tuple[dict[str, int], bool]:
    """(군락지별 단계, 서비스 중인지)."""
    return shared.stages_in(_jsonp(text), STAGES, "봄꽃", BlossomError)


def _kma(place: str = "") -> str:
    resp = _get(KMA_URL, params={"treeType": "1", "obsPlace": place}, referer=KMA_PAGE)
    resp.encoding = "utf-8"
    return resp.text


def fetch_status(today: dt.date) -> Status:
    """단계는 목록 한 번에, 촬영일은 obsPlace 로 한 곳씩 불러야 나옴. 날짜를 못 받아도 단계는 둠."""
    try:
        stages, in_service = parse_status(_kma())
    except (KeyError, TypeError, AttributeError) as exc:
        raise BlossomError(f"기상청 봄꽃 응답 형식이 바뀌었습니다: {exc}") from exc
    status = Status(stages=stages, in_service=in_service)
    for name, stage in stages.items():
        if not stage:
            continue
        try:
            flower = _jsonp(_kma(name)).get("flower") or {}
        except BlossomError as exc:
            log.warning("벚꽃 상세 실패 %s: %s", name, exc)
            continue
        if flower.get("obsPlace") != name:
            log.warning("벚꽃 상세 %s 를 요청했는데 %s 가 왔습니다", name, flower.get("obsPlace"))
            continue
        if bloom := shared.shot_date(flower.get("cfShotDate"), today.year):
            status.bloom[name] = bloom
        if full := shared.shot_date(flower.get("ffShotDate"), today.year):
            status.full[name] = full
    return status


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


def fetch_outlook(year: int) -> Outlook:
    """없으면 지난해 표의 평년만 — 발표(2/21~28)가 시즌 첫 주와 엇갈림. 실패는 «없음» 과 섞지 않고 BlossomError."""
    listing = _get(shared.WEATHERI_LIST)
    listing.encoding = "utf-8"
    outlook = _load_post(listing.text, year)
    if outlook is not None:
        log.info("웨더아이 %d년 벚꽃 예상 %d곳 (%s 발표)", year, len(outlook.expected), outlook.published)
        return outlook
    log.info("웨더아이 %d년 벚꽃 예상이 아직 없어 지난해 표의 평년을 씁니다", year)
    last = _load_post(listing.text, year - 1)
    if last is None:
        return Outlook(expected={}, normal={})
    return Outlook(expected={}, normal={c: d.replace(year=year) for c, d in last.normal.items()},
                   url=last.url)


# --- 주간 게시 문구 -----------------------------------------------------------

def observed_line(status: Status) -> str:
    """관측 한 줄 — 핀 곳이 적으면 이름·날짜, 많으면 개수·최근 변화."""
    if not status.in_service:
        return NOT_STARTED_TEXT
    events = []   # (날짜 또는 None, 군락지, 단계)
    for name, stage in status.stages.items():
        if stage:
            events.append(((status.full if stage == 2 else status.bloom).get(name), name, stage))
    waiting = len(status.stages) - len(events)
    if not events:
        return f"아직 핀 곳이 없습니다 — {len(status.stages)}곳 모두 개화 전"

    def text(e) -> str:
        day, name, stage = e
        return f"{bold(name)} {STAGES[stage]}" + (f" {short_date(day)}" if day else "")

    def latest(e):
        return e[0] or dt.date.min

    if len(events) <= 2:
        head = " · ".join(text(e) for e in sorted(events, key=latest))
        return f"{head}, 나머지 {waiting}곳은 개화 전" if waiting else head
    counts = [(STAGES[k], sum(1 for e in events if e[2] == k)) for k in (2, 1)]
    tally = " · ".join(f"{label} {n}곳" for label, n in counts if n)
    if waiting:
        tally += f" · 개화 전 {waiting}곳"
    return f"{tally} — 최근 " + " · ".join(text(e) for e in sorted(events, key=latest, reverse=True)[:2])


def _grouped(days: list[tuple[str, dt.date]]) -> str:
    """[(서귀포, 3/25), (부산, 3/25), (울산, 3/26)] → '*서귀포*·*부산* 3/25 · *울산* 3/26'."""
    by_day: dict[dt.date, list[str]] = {}
    for city, d in days:
        by_day.setdefault(d, []).append(bold(city))
    return " · ".join(f"{'·'.join(cities)} {short_date(d)}" for d, cities in sorted(by_day.items()))


def week_line(outlook: Outlook | None, start: dt.date, end: dt.date) -> str:
    if outlook is None or not outlook.expected:
        return NOT_PUBLISHED_TEXT
    week = [(c, d) for c, d in outlook.expected.items() if start <= d <= end]
    if week:
        return f"개화 {_grouped(week)} (예상)"
    ahead = sorted(((c, d) for c, d in outlook.expected.items() if d > end), key=lambda x: x[1])
    if not ahead:
        return "개화가 예상된 곳이 없습니다"
    first = ahead[0][1]
    return f"개화 예상 없음 · 다음은 {_grouped([x for x in ahead if x[1] == first])} (예상)"


def year_line(outlook: Outlook | None) -> str:
    """평년보다 이른지 늦은지. 올해 예상이 없으면 평년 개화일."""
    if outlook is None or not outlook.normal:
        return ""
    seoul_normal = outlook.normal.get("서울")
    if not outlook.expected:
        first_city, first_day = min(outlook.normal.items(), key=lambda x: x[1])
        line = f"{bold(first_city)} {short_date(first_day)} 무렵 시작해"
        return line + (f" {bold('서울')} {short_date(seoul_normal)} 무렵 핍니다" if seoul_normal else " 북상합니다")
    gap = outlook.gap_days()
    if gap is None:
        return ""
    days = int(abs(gap) + 0.5)             # 사사오입 — round() 는 2.5 를 2 로 내림
    trend = ("평년과 비슷하겠습니다" if days == 0
             else f"평년보다 {days}일가량 {'이르겠습니다' if gap < 0 else '늦겠습니다'}")
    seoul = outlook.expected.get("서울")
    if seoul and seoul_normal:
        trend += f" (서울 {short_date(seoul)}, 평년 {short_date(seoul_normal)})"
    return trend


def sources(status: Status | None, outlook: Outlook | None) -> str:
    bits = ["관측 기상청 날씨누리"] if status is not None else []
    if outlook is not None:
        if outlook.expected:
            bits.append(f"예상 {OUTLOOK_SOURCE}" + (f"({short_date(outlook.published)} 발표)" if outlook.published else ""))
        else:
            bits.append(f"평년 {OUTLOOK_SOURCE}")
    return " · ".join(bits)
