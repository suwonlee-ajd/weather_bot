"""단풍 — 기상청 현황과 웨더아이 예상일.

«관측» 과 «예상» 은 어디서든 섞어 쓰지 않는다. 기상청은 단풍 시기를 예보하지 않고 산마다
지금 단계를 관측해 알릴 뿐이며, 예상일은 민간 업체(웨더아이)가 해마다 9월 첫 주에 낸다.

  현황  기상청 날씨누리 유명산 단풍현황 (21곳, 9/20 무렵 ~ 11월 중하순)
        https://www.kma.go.kr/kma/theme/maple_photojs.jsp?treeType=4&obsPlace=<산>
        JSONP `applyMapleData({...})`. places[] 에 21곳의 단계가, flower 에
        obsPlace 로 고른 한 곳의 촬영일(bf 단풍전 / cf 첫단풍 / ff 절정)이 온다.
        산마다 날짜를 보려면 한 번씩 따로 불러야 한다.

  예상  웨더아이 공지 「YYYY년 단풍 예상시기」 첨부 PDF 의 [첨부1] 표 (15곳)
        https://www.weatheri.co.kr/board/board03_list.php
        2023~2026 네 해 모두 같은 표다. 날짜 표기만 '09.27'(~2024) → '10/3'(2025~) 로 바뀌었다.

첫단풍은 산 정상부터 20%, 절정은 80% 가량 물든 때다(양쪽 기준이 같다).

봇이 단풍을 다루는 기간은 9월 둘째 월요일 ~ 11월 둘째 월요일이 든 주까지다.
웨더아이 예상이 9월 첫 주에 나오고, 남부 산의 절정이 11월 초~중순이라 그 사이를 덮는다.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from .cache import get_or_set
from .config import UA
from .mountains import BY_NAME

log = logging.getLogger(__name__)

KMA_URL = "https://www.kma.go.kr/kma/theme/maple_photojs.jsp"
KMA_PAGE = "https://www.weather.go.kr/w/forecast/life/seasonal-observation/autumn-leaves.do"
WEATHERI_BASE = "https://www.weatheri.co.kr/board/"
WEATHERI_LIST = WEATHERI_BASE + "board03_list.php"

STAGES = ("단풍전", "첫단풍", "절정")
KINDS = ("first", "peak")             # 첫단풍 · 절정 — Status / Outlook 의 필드 이름

# 지도·멘션·CLI 가 함께 쓰는 문구
OUTLOOK_SOURCE = "웨더아이"
SEASON_TEXT = "9월 둘째 주 ~ 11월 둘째 주"
CRITERIA_TEXT = "첫단풍은 산 정상부터 20%, 절정은 80%가 물든 때"
NOT_STARTED_TEXT = "기상청 단풍 관측이 아직 시작되지 않았습니다 (해마다 9월 하순부터)"

# 현황은 관측 담당자가 사진을 올릴 때 바뀐다(하루 한두 번).
STATUS_TTL_SEC = 3600
# 예상은 한 해 한 번, 9월 첫 주에 나온다. 다루는 기간(9월 둘째 주~) 안에는 늘 나와 있다.
OUTLOOK_TTL_SEC = 24 * 3600
# 산별 날짜는 한 시즌 내내 들고 있어도 된다. 단계가 바뀌지 않는 한 그대로이고,
# 키에 단계가 들어 있어 바뀐 산만 다시 부른다.
DETAIL_TTL_SEC = 120 * 24 * 3600
# 예상 조회가 실패했거나 아직 안 올라왔을 때 다시 보기까지. 멘션마다 PDF 를 받으러 가지 않게 한다.
OUTLOOK_RETRY_SEC = 1800
# 현황 조회가 실패했을 때 다시 보기까지. 실패를 기억하되 짧게 잡는다 — 단풍철엔 지역 날씨
# 답마다 현황을 붙여(mention) 기상청 점검 중이면 답마다 실패할 요청을 기다리게 되고,
# 단풍을 직접 물은 사람에게는 «잠시 뒤 다시 불러 주세요» 라고 답한다.
STATUS_RETRY_SEC = 120
# 산별 날짜를 동시에 몇 개까지 받을지. 늦가을엔 20곳 가까이 물들어 하나씩 받으면 길어진다.
DETAIL_WORKERS = 4


class FoliageError(RuntimeError):
    pass


class _Incomplete(Exception):
    """단계는 올랐는데 그 단계의 촬영일이 아직 없다. 캐시하지 않고 다음에 다시 본다.

    목록과 상세가 따로 갱신되어, 목록이 먼저 첫단풍으로 바뀌고 촬영일은 나중에 올라오기도 한다.
    이 상태를 한 시즌 캐시하면 그 산의 날짜가 다음 단계까지 비어 있게 된다.
    """


class _NotPublished(Exception):
    """웨더아이 예상이 아직 안 올라왔다. 실패처럼 짧게만 기억한다."""


# --- 기간 ------------------------------------------------------------------

def _second_monday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(7 - first.weekday()) % 7 + 7)


def season_bounds(year: int) -> tuple[dt.date, dt.date]:
    """9월 둘째 월요일 ~ 11월 둘째 월요일이 든 주의 일요일."""
    return _second_monday(year, 9), _second_monday(year, 11) + dt.timedelta(days=6)


def in_season(day: dt.date) -> bool:
    start, end = season_bounds(day.year)
    return start <= day <= end


def next_season(day: dt.date) -> tuple[dt.date, dt.date]:
    """지금이 기간이면 이번 기간, 아니면 다음에 올 기간."""
    start, end = season_bounds(day.year)
    return (start, end) if day <= end else season_bounds(day.year + 1)


# --- 기상청 현황 -------------------------------------------------------------

@dataclass
class Status:
    stages: dict[str, int]                                  # 산 → 0 단풍전 / 1 첫단풍 / 2 절정
    first: dict[str, dt.date] = field(default_factory=dict)  # 관측된 첫단풍일
    peak: dict[str, dt.date] = field(default_factory=dict)   # 관측된 절정일
    in_service: bool = True

    def stage(self, name: str) -> int:
        return self.stages.get(name, 0)

    @property
    def updated(self) -> dt.date | None:
        """가장 최근 촬영일."""
        return max([*self.first.values(), *self.peak.values()], default=None)


def _jsonp(text: str) -> dict:
    m = re.search(r"applyMapleData\((\{.*\})\)", text, re.S)
    if not m:
        raise FoliageError("기상청 단풍 응답에서 자료를 찾지 못했습니다 (형식 변경 의심)")
    try:
        return json.loads(m.group(1))
    except ValueError as exc:
        raise FoliageError(f"기상청 단풍 응답을 읽지 못했습니다: {exc}") from exc


def _stage_of(place: dict) -> int:
    text = place.get("status") or ""
    if text in STAGES:
        return STAGES.index(text)
    # 글자가 바뀌어도 코드(1 단풍전 / 2 첫단풍 / 3 절정)는 남는다
    try:
        return max(0, min(2, int(place.get("sts", "1")) - 1))
    except (TypeError, ValueError):       # "sts": null 이 와도 단풍전으로
        return 0


def _date(raw: str | None, year: int) -> dt.date | None:
    """촬영일. 올해 것이 아니면 버린다 — 서비스 전에는 지난해 기록이 그대로 내려온다."""
    if not raw:
        return None
    try:
        d = dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None
    return d if d.year == year else None


def parse_status(text: str, year: int) -> tuple[dict[str, int], bool, dict]:
    """목록 응답에서 (산별 단계, 서비스 중인지, 고른 산의 상세) 를 뽑는다."""
    data = _jsonp(text)
    places = data.get("places") or []
    if not places:
        raise FoliageError("기상청 단풍 응답에 관측 지점이 없습니다")
    in_service = bool(data.get("isService"))
    # 서비스 기간 밖이면 단풍전으로 둔다 — 남아 있는 지난 시즌 단계를 올해 것으로 읽지 않게.
    stages = {p["obsPlace"]: (_stage_of(p) if in_service else 0) for p in places if p.get("obsPlace")}
    return stages, in_service, data.get("flower") or {}


def _get(url: str, *, params: dict | None = None, timeout: float = 20.0, referer: str = "") -> requests.Response:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FoliageError(f"요청 실패 {url}: {exc}") from exc
    return resp


def _kma(place: str = "") -> str:
    resp = _get(KMA_URL, params={"treeType": "4", "obsPlace": place}, referer=KMA_PAGE)
    resp.encoding = "utf-8"
    return resp.text


def _dates(flower: dict, year: int) -> tuple[dt.date | None, dt.date | None]:
    """상세에서 (첫단풍, 절정) 촬영일."""
    return _date(flower.get("cfShotDate"), year), _date(flower.get("ffShotDate"), year)


def _detail(name: str, stage: int, year: int) -> tuple[dt.date | None, dt.date | None]:
    """한 산의 (첫단풍, 절정) 관측일. 지금 단계의 날짜가 있어야만 캐시한다."""
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
        # 날짜만 비워 둔다 — 한 산의 날짜를 못 받아도 단계는 맞다.
        log.warning("단풍 상세 실패 %s: %s", name, exc)
        return None, None


def fetch_status(today: dt.date) -> Status:
    """21곳의 단계와, 물들기 시작한 산의 관측일."""
    def load() -> Status:
        try:
            stages, in_service, flower = parse_status(_kma(), today.year)
        except (KeyError, TypeError, AttributeError) as exc:
            raise FoliageError(f"기상청 단풍 응답 형식이 바뀌었습니다: {exc}") from exc
        status = Status(stages=stages, in_service=in_service)
        colored = [(name, stage) for name, stage in stages.items() if stage > 0]
        # 목록 응답에 딸려 온 한 곳(기본 설악산)의 상세는 다시 부르지 않는다.
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


# 산이름 해발고도 첫단풍(예상일 평년차 작년차) 절정(예상일 평년차 작년차)
_ROW = re.compile(
    r"^\s*([가-힣]{2,4}산)\s+[\d,]+\s+(\d{1,2})[/.](\d{1,2})\s+\S+\s+\S+\s+(\d{1,2})[/.](\d{1,2})"
)
# 표가 통째로 바뀌었는지 가려낼 문턱. 해마다 15곳이 나왔고, 그중 14곳이 기상청 목록과 겹친다.
_MIN_KNOWN_ROWS = 10


def parse_outlook_text(text: str, year: int) -> tuple[dict[str, dt.date], dict[str, dt.date]]:
    """PDF 에서 뽑은 글자에서 산별 (첫단풍, 절정) 예상일. 기상청 목록에 없는 산(금강산)은 뺀다.

    조금이라도 어긋나면 통째로 버리고 FoliageError 를 낸다. 잘못 읽은 날짜는 지도에서
    그럴듯해 보여 알아채기 어려우니, 예상 없이 현황만 그리는 편이 낫다.
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


def _pdf_text(blob: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:            # 현황만으로라도 답한다 — 서버에서 uv sync 를 빠뜨린 경우
        raise FoliageError("pypdf 가 설치되지 않아 웨더아이 예상을 읽지 못합니다") from exc
    try:
        reader = PdfReader(io.BytesIO(blob))
        return "\n".join(p.extract_text(extraction_mode="layout") for p in reader.pages)
    except Exception as exc:          # pypdf 는 깨진 파일마다 다른 예외를 낸다
        raise FoliageError(f"웨더아이 PDF 를 읽지 못했습니다: {exc}") from exc


def _find_post(list_html: str, year: int) -> str | None:
    m = re.search(rf"href=['\"]?(board03_read\.php\?id=\d+[^'\"\s>]*)['\"]?\s*>\s*{year}년\s*단풍\s*예상시기", list_html)
    return urllib.parse.urljoin(WEATHERI_BASE, m.group(1)) if m else None


def posted_on(post_html: str, year: int) -> dt.date | None:
    """웨더아이 게시물의 게시일. 머리 표의 날짜 칸에 있다 — 벚꽃 게시물도 같은 판이다.

    날짜 칸은 글자색으로 집는다. 페이지 맨 위 특보 띠에도 오늘 날짜가 흘러가고,
    작성자 칸이 비어 있는 해(2026 벚꽃)가 있어 '관리자' 뒤를 찾으면 놓친다.
    """
    m = re.search(rf"#124c78\">\s*({year})-(\d{{2}})-(\d{{2}})", post_html)
    return dt.date(*map(int, m.groups())) if m else None


def fetch_outlook(year: int) -> Outlook | None:
    """올해 웨더아이 예상. 아직 안 올라왔으면 None, 읽다 실패하면 FoliageError.

    받은 예상은 하루 들고 있고, 실패와 «아직 없음» 은 30분만 기억한다 — 단풍을 물을 때마다
    PDF 를 다시 받으러 가지 않되, 늦게 올라와도 반나절씩 놓치지 않게.
    """
    try:
        return get_or_set(("foliage-outlook", year), OUTLOOK_TTL_SEC, lambda: _load_outlook(year),
                          errors=(FoliageError, _NotPublished), error_ttl=OUTLOOK_RETRY_SEC)
    except _NotPublished:
        return None


def _load_outlook(year: int) -> Outlook:
    listing = _get(WEATHERI_LIST)
    listing.encoding = "utf-8"
    post_url = _find_post(listing.text, year)
    if post_url is None:
        log.info("웨더아이 %d년 단풍 예상시기가 아직 없습니다", year)
        raise _NotPublished(year)
    post = _get(post_url)
    post.encoding = "utf-8"
    pdf = re.search(r"https?://[^\"'\s<>]+\.pdf", post.text, re.I)
    if not pdf:
        raise FoliageError(f"웨더아이 {year}년 단풍 게시물에 PDF 가 없습니다: {post_url}")
    # 파일명에 대괄호가 들어 있다 ([Weatheri]2026_maple.pdf)
    pdf_url = urllib.parse.quote(pdf.group(0), safe=":/?&=%")
    first, peak = parse_outlook_text(_pdf_text(_get(pdf_url, timeout=30).content), year)
    published = posted_on(post.text, year)
    log.info("웨더아이 %d년 단풍 예상 %d곳 (%s 발표)", year, len(first), published)
    return Outlook(first=first, peak=peak, published=published, url=post_url)


# --- 한 산 ---------------------------------------------------------------

@dataclass
class Snapshot:
    """한 시점의 현황과 예상. 지도와 멘션 답이 같은 값을 쓰게 묶어 둔다."""
    status: Status
    outlook: Outlook | None
    outlook_error: str = ""

    def stage(self, name: str) -> int:
        return self.status.stage(name)

    def predicted(self, kind: str, name: str) -> dt.date | None:
        """웨더아이 예상일. kind 는 'first'(첫단풍) 또는 'peak'(절정)."""
        return getattr(self.outlook, kind).get(name) if self.outlook else None

    def when(self, kind: str, name: str) -> tuple[dt.date | None, bool]:
        """(날짜, 관측인지). 관측이 있으면 관측, 없으면 예상.

        이미 그 단계에 들었는데 촬영일이 안 올라왔으면 (None, True) — 지난 단계의 예상일을
        보여주면 "지금 첫단풍" 옆에 "첫단풍 예상이었지만 아직" 이 붙어 앞뒤가 어긋난다.
        """
        observed = getattr(self.status, kind).get(name)
        if observed:
            return observed, True
        if self.stage(name) > KINDS.index(kind):
            return None, True
        return self.predicted(kind, name), False

    def signature(self) -> tuple:
        """내용이 같으면 같은 값. 그린 지도를 캐시할 때 글과 그림이 어긋나지 않게 키로 쓴다."""
        s, o = self.status, self.outlook
        return (tuple(sorted(s.stages.items())), tuple(sorted(s.first.items())),
                tuple(sorted(s.peak.items())), s.in_service,
                o.published if o else None, bool(self.outlook_error))


def fetch_snapshot(today: dt.date) -> Snapshot:
    """현황은 꼭, 예상은 있으면. 예상을 못 받아도 현황만으로 답한다."""
    status = fetch_status(today)
    try:
        outlook, error = fetch_outlook(today.year), ""
    except FoliageError as exc:
        log.warning("웨더아이 단풍 예상 실패: %s", exc)
        outlook, error = None, str(exc)
    return Snapshot(status=status, outlook=outlook, outlook_error=error)
