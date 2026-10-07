"""단풍 — 기상청 유명산 단풍현황(21곳)과 웨더아이 예상일(15곳). «관측» 과 «예상» 은 섞어 쓰지 않음.

기상청은 관측만 하고 예보하지 않음. 예상일은 웨더아이 「YYYY년 단풍 예상시기」 첨부 PDF 의 [첨부1] 표.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from src.common.cache import get_or_set
from src.season import sources as shared
from src.season.mountains import BY_NAME

log = logging.getLogger(__name__)

KMA_URL = "https://www.kma.go.kr/kma/theme/maple_photojs.jsp"
KMA_PAGE = "https://www.weather.go.kr/w/forecast/life/seasonal-observation/autumn-leaves.do"

STAGES = ("단풍전", "첫단풍", "절정")
KINDS = ("first", "peak")             # Status·Outlook 의 필드 이름 (첫단풍·절정)

SEASON_TEXT = "9월 둘째 주 ~ 11월 둘째 주"
CRITERIA_TEXT = "첫단풍은 산 정상부터 20%, 절정은 80%가 물든 때"
NOT_STARTED_TEXT = "기상청 단풍 관측이 아직 시작되지 않았습니다 (해마다 9월 하순부터)"

STATUS_TTL_SEC = 3600                 # 현황은 사진이 올라올 때만 바뀜(하루 한두 번)
OUTLOOK_TTL_SEC = 24 * 3600           # 예상은 한 해 한 번(9월 첫 주)
DETAIL_TTL_SEC = 120 * 24 * 3600      # 키에 단계가 들어 있어 한 시즌 내내 들고 있어도 됨
OUTLOOK_RETRY_SEC = 1800              # 실패·미발표도 기억 — 멘션마다 PDF 를 받으러 가지 않게
STATUS_RETRY_SEC = 120                # 짧게 — 지역 날씨 답마다 현황을 붙여, 점검 중이면 답마다 기다림
DETAIL_WORKERS = 4                    # 늦가을엔 20곳 가까이 물들어 하나씩 받으면 김


class FoliageError(RuntimeError):
    pass


class _Incomplete(Exception):
    """단계는 올랐는데 촬영일이 아직 없음 — 목록이 상세보다 먼저 바뀜. 캐시하면 다음 단계까지 날짜가 빔."""


class _NotPublished(Exception):
    """웨더아이 예상 미발표 — 실패처럼 짧게만 캐시함."""


# --- 기간 ------------------------------------------------------------------

def _second_monday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(7 - first.weekday()) % 7 + 7)


def season_bounds(year: int) -> tuple[dt.date, dt.date]:
    """9월 둘째 월요일 ~ 11월 둘째 월요일이 든 주 — 예상 발표(9월 첫 주) 뒤부터 남부 절정(11월 초~중순)까지."""
    return _second_monday(year, 9), _second_monday(year, 11) + dt.timedelta(days=6)


def in_season(day: dt.date) -> bool:
    start, end = season_bounds(day.year)
    return start <= day <= end


def next_season(day: dt.date) -> tuple[dt.date, dt.date]:
    start, end = season_bounds(day.year)
    return (start, end) if day <= end else season_bounds(day.year + 1)


# --- 기상청 현황 -------------------------------------------------------------

@dataclass
class Status:
    stages: dict[str, int]                                  # 산 → 0 단풍전 / 1 첫단풍 / 2 절정
    first: dict[str, dt.date] = field(default_factory=dict)
    peak: dict[str, dt.date] = field(default_factory=dict)
    in_service: bool = True

    def stage(self, name: str) -> int:
        return self.stages.get(name, 0)

    @property
    def updated(self) -> dt.date | None:
        return max([*self.first.values(), *self.peak.values()], default=None)


def _jsonp(text: str) -> dict:
    return shared.jsonp(text, "applyMapleData", "단풍", FoliageError)


def parse_status(text: str, year: int) -> tuple[dict[str, int], bool, dict]:
    """(산별 단계, 서비스 중인지, obsPlace 한 곳의 상세)."""
    data = _jsonp(text)
    stages, in_service = shared.stages_in(data, STAGES, "단풍", FoliageError)
    return stages, in_service, data.get("flower") or {}


def _get(url: str, **kw) -> requests.Response:
    return shared.get(url, error=FoliageError, **kw)


def _kma(place: str = "") -> str:
    resp = _get(KMA_URL, params={"treeType": "4", "obsPlace": place}, referer=KMA_PAGE)
    resp.encoding = "utf-8"
    return resp.text


def _dates(flower: dict, year: int) -> tuple[dt.date | None, dt.date | None]:
    return shared.shot_date(flower.get("cfShotDate"), year), shared.shot_date(flower.get("ffShotDate"), year)


def _detail(name: str, stage: int, year: int) -> tuple[dt.date | None, dt.date | None]:
    def load():
        flower = _jsonp(_kma(name)).get("flower") or {}
        if flower.get("obsPlace") != name:
            raise FoliageError(f"{name} 상세를 요청했는데 {flower.get('obsPlace')} 가 왔습니다")
        dates = _dates(flower, year)
        if dates[stage - 1] is None:
            raise _Incomplete(*dates)
        return dates
    try:
        return get_or_set(("foliage-detail", name, stage, year), DETAIL_TTL_SEC, load)
    except _Incomplete as exc:
        return exc.args


def _safe_detail(name: str, stage: int, year: int) -> tuple[dt.date | None, dt.date | None]:
    try:
        return _detail(name, stage, year)
    except (FoliageError, KeyError, TypeError, AttributeError) as exc:
        # 날짜만 비움 — 단계는 목록 것이라 맞음
        log.warning("단풍 상세 실패 %s: %s", name, exc)
        return None, None


def fetch_status(today: dt.date) -> Status:
    """단계는 목록 한 번에, 촬영일은 obsPlace 로 산마다 따로 불러야 나옴."""
    def load() -> Status:
        try:
            stages, in_service, flower = parse_status(_kma(), today.year)
        except (KeyError, TypeError, AttributeError) as exc:
            raise FoliageError(f"기상청 단풍 응답 형식이 바뀌었습니다: {exc}") from exc
        status = Status(stages=stages, in_service=in_service)
        colored = [(name, stage) for name, stage in stages.items() if stage > 0]
        # 목록 응답에 딸려 온 한 곳(기본 설악산)은 다시 부르지 않음
        known = {flower.get("obsPlace"): _dates(flower, today.year)}

        def dates_of(item):
            name, stage = item
            if name in known and known[name][stage - 1] is not None:
                return known[name]
            return _safe_detail(name, stage, today.year)

        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            for (name, _), (first, peak) in zip(colored, pool.map(dates_of, colored)):
                if first:
                    status.first[name] = first
                if peak:
                    status.peak[name] = peak
        return status
    return get_or_set(("foliage-status", today), STATUS_TTL_SEC, load,
                      errors=(FoliageError,), error_ttl=STATUS_RETRY_SEC)


# --- 웨더아이 예상 -----------------------------------------------------------

@dataclass
class Outlook:
    first: dict[str, dt.date]
    peak: dict[str, dt.date]
    published: dt.date | None = None
    url: str = ""


# 산이름 해발고도 첫단풍(예상일 평년차 작년차) 절정(…). 날짜는 '09.27'(~2024), '10/3'(2025~).
_ROW = re.compile(
    r"^\s*([가-힣]{2,4}산)\s+[\d,]+\s+(\d{1,2})[/.](\d{1,2})\s+\S+\s+\S+\s+(\d{1,2})[/.](\d{1,2})"
)
# 형식 변경 감지 문턱 — 해마다 15곳, 그중 14곳이 기상청 목록과 겹침
_MIN_KNOWN_ROWS = 10


def parse_outlook_text(text: str, year: int) -> tuple[dict[str, dt.date], dict[str, dt.date]]:
    """산별 (첫단풍, 절정) 예상일. 기상청 목록에 없는 산(금강산)은 뺌.

    조금이라도 어긋나면 통째로 버림 — 그럴듯한 오독은 알아채기 어려움.
    """
    first: dict[str, dt.date] = {}
    peak: dict[str, dt.date] = {}
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m or m.group(1) not in BY_NAME:
            continue
        name = m.group(1)
        try:
            f = dt.date(year, int(m.group(2)), int(m.group(3)))
            p = dt.date(year, int(m.group(4)), int(m.group(5)))
        except ValueError as exc:
            raise FoliageError(f"웨더아이 표의 {name} 날짜가 이상합니다: {line.strip()}") from exc
        if not (dt.date(year, 9, 1) <= f <= p <= dt.date(year, 12, 15)):
            raise FoliageError(f"웨더아이 표의 {name} 날짜가 범위를 벗어났습니다: {line.strip()}")
        first[name], peak[name] = f, p
    if len(first) < _MIN_KNOWN_ROWS:
        raise FoliageError(f"웨더아이 표에서 산을 {len(first)}곳밖에 읽지 못했습니다 (형식 변경 의심)")
    return first, peak


def _find_post(list_html: str, year: int) -> str | None:
    return shared.find_post(list_html, year, r"단풍\s*예상시기")


def fetch_outlook(year: int) -> Outlook | None:
    """아직 안 올라왔으면 None, 읽다 실패하면 FoliageError."""
    try:
        return get_or_set(("foliage-outlook", year), OUTLOOK_TTL_SEC, lambda: _load_outlook(year),
                          errors=(FoliageError, _NotPublished), error_ttl=OUTLOOK_RETRY_SEC)
    except _NotPublished:
        return None


def _load_outlook(year: int) -> Outlook:
    listing = _get(shared.WEATHERI_LIST)
    listing.encoding = "utf-8"
    post_url = _find_post(listing.text, year)
    if post_url is None:
        log.info("웨더아이 %d년 단풍 예상시기가 아직 없습니다", year)
        raise _NotPublished(year)
    post = _get(post_url)
    post.encoding = "utf-8"
    pdf_url = shared.pdf_link(post.text)
    if not pdf_url:
        raise FoliageError(f"웨더아이 {year}년 단풍 게시물에 PDF 가 없습니다: {post_url}")
    first, peak = parse_outlook_text(shared.pdf_text(_get(pdf_url, timeout=30).content, FoliageError), year)
    published = shared.posted_on(post.text, year)
    log.info("웨더아이 %d년 단풍 예상 %d곳 (%s 발표)", year, len(first), published)
    return Outlook(first=first, peak=peak, published=published, url=post_url)


# --- 현황 + 예상 -----------------------------------------------------------

@dataclass
class Snapshot:
    status: Status
    outlook: Outlook | None
    outlook_error: str = ""

    def stage(self, name: str) -> int:
        return self.status.stage(name)

    def predicted(self, kind: str, name: str) -> dt.date | None:
        return getattr(self.outlook, kind).get(name) if self.outlook else None

    def when(self, kind: str, name: str) -> tuple[dt.date | None, bool]:
        """(날짜, 관측인지). 관측이 없으면 예상.

        이미 든 단계에 촬영일이 없으면 (None, True) — 지난 단계의 예상일을 보이면 앞뒤가 어긋남.
        """
        observed = getattr(self.status, kind).get(name)
        if observed:
            return observed, True
        if self.stage(name) > KINDS.index(kind):
            return None, True
        return self.predicted(kind, name), False

    def signature(self) -> tuple:
        """그린 지도의 캐시 키 — 내용이 같으면 같은 값."""
        s, o = self.status, self.outlook
        return (tuple(sorted(s.stages.items())), tuple(sorted(s.first.items())),
                tuple(sorted(s.peak.items())), s.in_service,
                o.published if o else None, bool(self.outlook_error))


def fetch_snapshot(today: dt.date) -> Snapshot:
    """현황은 꼭, 예상은 있으면."""
    status = fetch_status(today)
    try:
        outlook, error = fetch_outlook(today.year), ""
    except FoliageError as exc:
        log.warning("웨더아이 단풍 예상 실패: %s", exc)
        outlook, error = None, str(exc)
    return Snapshot(status=status, outlook=outlook, outlook_error=error)
