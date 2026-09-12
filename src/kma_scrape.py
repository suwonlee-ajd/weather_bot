"""기상청 날씨누리 공개 페이지에서 이번 주 예보를 긁어온다. (API 키·결제 불필요)

두 페이지만 쓴다. 둘 다 서버 렌더링이라 requests + BeautifulSoup 로 충분하고,
robots.txt 는 `User-Agent: * / Allow: /` 로 이 경로들을 허용한다.

  예보 통보문  /w/forecast/notice.do
      총괄예보관이 쓴 종합 서술(□/○ 줄) + **전국** 최저/최고기온 범위 표 (오늘~그글피, D+0~D+4)
      "최저기온 14 ~ 22 / 최고기온 25 ~ 30" 처럼 지역 간 분포 범위로 나온다.
      원본 게시물의 "아침 기온 18~24℃, 낮 기온 25~33℃" 와 정확히 같은 형식이다.

  중기예보     /w/forecast/overall/mid-term.do
      기상전망 서술 + 도시별 최저/최고기온 표 + 지역별 오전/오후 하늘상태·강수확률 표 (D+4~D+10)
      도시별 값을 가로로 모으면 전국 분포 범위가 나온다.

특보·태풍 페이지는 지도 기반 JS 라 긁지 않는다. 대신 통보문의 종합 서술이 그것을 짚어준다
("내일까지 풍랑과 너울 유의" 처럼).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from .config import KST

log = logging.getLogger(__name__)

BASE = "https://www.weather.go.kr"
NOTICE_URL = f"{BASE}/w/forecast/notice.do"
MID_URL = f"{BASE}/w/forecast/overall/mid-term.do"
UA = "ajd-weekly-weather-bot/1.0 (+internal Slack bot)"

RANGE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*~\s*(-?\d+(?:\.\d+)?)")
DOM_RE = re.compile(r"(\d{1,2})\s*일")
ISSUED_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?(\d{1,2}):(\d{2})")
POP_RE = re.compile(r"(\d{1,3})\s*%")




@dataclass(frozen=True)
class Region:
    """기상청 페이지의 지역 구분.

    통보문(notice.do)은 지역별 페이지가 따로 있어 stnId 하나로 끝난다.
    중기예보(mid-term.do)는 두 지역을 한 페이지에 묶어 보여주는 경우가 있어
    (예: 부산·울산·경남 + 대구·경북), 표에서 해당 그룹 행만 골라내야 한다.
    """

    key: str
    label: str
    notice_stn: str
    mid_stn1: str
    mid_stn2: str | None = None
    mid_group: str | None = None  # 기온/날씨 표에서 이 문자열이 든 지역 행만 사용
    aliases: tuple[str, ...] = ()


REGIONS: tuple[Region, ...] = (
    Region("전국", "전국", "108", "108", aliases=("전체", "대한민국", "all")),
    Region("수도권", "서울·인천·경기", "109", "109",
           aliases=("서울", "인천", "경기", "경기도", "서울경기", "수도권", "기호")),
    # 기상청 중기예보는 강원을 영서/영동으로 나눠 준다. 전통 지명이 그대로 표의 그룹명이다.
    Region("강원", "강원", "105", "105",
           aliases=("강원도", "관동", "춘천", "원주")),
    Region("영서", "강원 영서", "105", "105", mid_group="강원도 영서",
           aliases=("강원영서", "영서지방")),
    Region("영동", "강원 영동", "105", "105", mid_group="강원도 영동",
           aliases=("강원영동", "영동지방", "강릉", "속초", "동해안")),
    Region("충남", "대전·세종·충남", "133", "133", "131", "대전",
           aliases=("대전", "세종", "충청남도", "천안")),
    Region("충북", "충북", "131", "133", "131", "충청북도",
           aliases=("충청북도", "청주")),
    Region("전남", "광주·전남", "156", "156", "146", "광주",
           aliases=("광주", "전라남도", "여수", "목포", "순천")),
    Region("전북", "전북", "146", "156", "146", "전북",
           aliases=("전라북도", "전주", "군산")),
    Region("경남", "부산·울산·경남", "159", "159", "143", "부산",
           aliases=("부산", "울산", "경상남도", "창원", "진주", "김해")),
    Region("경북", "대구·경북", "143", "159", "143", "대구",
           aliases=("대구", "경상북도", "포항", "안동", "구미")),
    Region("제주", "제주", "184", "184", aliases=("제주도", "서귀포")),
)

# 여러 광역 구역을 아우르는 말. 기상청에 대응하는 단일 페이지가 없어 대표 구역으로 보낸다.
# (예보 자체가 그 구역 기준이므로, 응답에 어떤 구역으로 해석했는지 함께 적는다.)
WIDE_AREAS: dict[str, tuple[str, str]] = {
    # 별칭 → (대표 REGIONS key, 사용자에게 보여줄 설명)
    "중부": ("수도권", "중부지방은 서울·인천·경기 기준으로 보여드립니다"),
    "중부지방": ("수도권", "중부지방은 서울·인천·경기 기준으로 보여드립니다"),
    "남부": ("경남", "남부지방은 부산·울산·경남 기준으로 보여드립니다"),
    "남부지방": ("경남", "남부지방은 부산·울산·경남 기준으로 보여드립니다"),
    "영남": ("경남", "영남은 부산·울산·경남 기준으로 보여드립니다 (경북은 '경북')"),
    "호남": ("전남", "호남은 광주·전남 기준으로 보여드립니다 (전북은 '전북')"),
    "충청": ("충남", "충청은 대전·세종·충남 기준으로 보여드립니다 (충북은 '충북')"),
    "충청도": ("충남", "충청은 대전·세종·충남 기준으로 보여드립니다 (충북은 '충북')"),
    "영동": ("영동", ""),   # 영동/영서는 실제 구역이 있으므로 설명이 필요 없다
    "영서": ("영서", ""),
}

NATIONWIDE = REGIONS[0]

# 안내문에 쓰는 구역 목록. REGIONS 에서 만들어 구역을 추가해도 따로 고칠 일이 없다.
REGION_HELP = " · ".join(r.key for r in REGIONS)


def extract_region(text: str) -> tuple[Region | None, str]:
    """문장에서 지역을 집어낸다. 조언 문장처럼 군더더기가 섞여 있어도 동작한다.

    지우는 방식(정규식으로 조언어 제거)은 '무등산' 의 '등산' 까지 지워 버린다.
    그래서 반대로 — 아는 지역 이름이 문장 안에 있는지 훑는다. 긴 이름부터 봐서
    '경기'보다 '경기도' 가 먼저 걸리게 한다.
    """
    flat = (text or "").replace(" ", "")
    if not flat:
        return NATIONWIDE, ""

    candidates: list[tuple[str, Region | None, str]] = []
    for name, (key, note) in WIDE_AREAS.items():
        region = next((r for r in REGIONS if r.key == key), None)
        candidates.append((name, region, note))
    for region in REGIONS:
        for name in (region.key, region.label.replace("·", ""), *region.aliases):
            candidates.append((name, region, ""))

    for name, region, note in sorted(candidates, key=lambda c: -len(c[0])):
        if name and name.replace(" ", "") in flat:
            return region, note
    return None, ""


def find_region(query: str | None) -> Region | None:
    """'부산', '영남', '중부' 같은 말에서 지역을 찾는다. 못 찾으면 None."""
    region, _ = resolve_region(query)
    return region


def resolve_region(query: str | None) -> tuple[Region | None, str]:
    """지역과 함께 '어떻게 해석했는지' 안내문을 돌려준다.

    '중부'·'남부'·'영남'처럼 기상청에 대응하는 단일 페이지가 없는 말은 대표 구역으로
    보내되, 무엇으로 바꿔 읽었는지 안내문에 담는다. 조용히 바꿔치기하면 사용자가
    자기가 물은 것과 다른 답을 받은 줄 모른다.
    """
    if not query:
        return NATIONWIDE, ""
    text = query.strip().lower().replace(" ", "")
    if not text:
        return NATIONWIDE, ""

    def by_key(key: str) -> Region | None:
        return next((r for r in REGIONS if r.key == key), None)

    # 광역 표현을 먼저 본다 ('영동'처럼 실제 구역과 겹치는 말이 있어 순서가 중요하다)
    for name, (key, note) in WIDE_AREAS.items():
        if text == name:
            return by_key(key), note

    for region in REGIONS:
        for name in (region.key, region.label, *region.aliases):
            if text == name.lower().replace(" ", "").replace("·", ""):
                return region, ""

    for name, (key, note) in WIDE_AREAS.items():
        if name in text:
            return by_key(key), note

    for region in REGIONS:
        for name in (region.key, *region.aliases):
            if name.lower() in text:
                return region, ""
    return None, ""


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


# --------------------------------------------------------------------------- #
# 공통 유틸
# --------------------------------------------------------------------------- #

def _get_soup(url: str, timeout: float = 25.0) -> BeautifulSoup:
    # 실패했을 때 기상청이 죽은 것인지 파서가 깨진 것인지 로그만 보고 갈라야 한다.
    # 그래서 상태코드와 본문 크기를 남긴다 — 200 인데 4KB 면 페이지 구조가 바뀐 것이다.
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
    """'14일' 같은 표기를 기준일 근처의 실제 날짜로 되돌린다 (월말/월초 넘어감 처리)."""
    for delta in range(-16, 17):
        cand = ref + dt.timedelta(days=delta)
        if cand.day == day_of_month:
            return cand
    return None


def _narrative_lines(soup: BeautifulSoup) -> list[str]:
    """□ / ○ 로 시작하는 예보관 서술만 뽑는다."""
    text = soup.get_text("\n", strip=True)
    lines: list[str] = []
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if line.startswith(("□", "○")) and len(line) > 4:
            lines.append(line)
        elif lines and not line.startswith(("□", "○")) and len(line) > 8 and len(lines) <= 6:
            # 서술이 <br> 로 이어지는 경우가 있어 직전 줄에 붙인다
            if lines[-1].endswith((",", "및")):
                lines[-1] += " " + line
    return lines


# --------------------------------------------------------------------------- #
# 1) 예보 통보문 — 전국 최저/최고기온 범위 (D+0 ~ D+4)
# --------------------------------------------------------------------------- #

# "○ (오늘, 12일) 가끔 구름많음, ..." 에서 날짜와 하늘상태를 뽑는다.
DAILY_LINE_RE = re.compile(r"^○\s*\([^,)]*,\s*(\d{1,2})일\)\s*(.+)$")
# 서술문의 하늘상태 표현을 표 값과 같은 어휘로 맞춘다 (앞에 오는 것이 우선)
SKY_WORDS = ("흐리", "구름많", "구름 많", "대체로 맑", "맑")
SKY_CANON = {"흐리": "흐림", "구름많": "구름많음", "구름 많": "구름많음",
             "대체로 맑": "맑음", "맑": "맑음"}
RAIN_WORDS = ("비", "눈", "소나기", "빗방울")


def _sky_from_line(text: str) -> str | None:
    """서술문에서 대표 하늘상태 하나. 비/눈이 있으면 그것을 우선한다."""
    for word in RAIN_WORDS:
        if word in text:
            # '빗방울' 처럼 약한 표현도 비로 본다 — 우산 여부가 갈리는 정보다
            base = next((SKY_CANON[w] for w in SKY_WORDS if w in text), "흐림")
            return f"{base}, 비" if word != "눈" else f"{base}, 눈"
    for word in SKY_WORDS:
        if word in text:
            return SKY_CANON[word]
    return None


def lines_for_dates(lines: list[str], ref: dt.date,
                    window: set[dt.date]) -> list[str]:
    """서술 줄 중 물어본 날짜에 해당하는 것만 고른다.

    "○ (모레, 14일) ..." 처럼 날짜가 박힌 줄은 그 날짜가 window 에 있을 때만 남긴다.
    날짜가 없는 줄(□ 종합, ○ (기온)/(하늘상태) 같은 기간 전체 서술)은 어느 날을
    물어도 유효하므로 그대로 남긴다.

    날짜가 박힌 줄이 하나도 안 맞으면 기간 전체 서술만 돌아간다 — 물은 날과
    다른 날의 이야기를 붙이느니 덜 보여주는 쪽이 낫다.
    """
    out: list[str] = []
    for line in lines:
        m = DAILY_LINE_RE.match(line)
        if not m:
            out.append(line)          # 날짜가 없는 줄은 항상 유효
            continue
        date = _resolve_date(int(m.group(1)), ref)
        if date is None or date in window:
            out.append(line)
    return out


def daily_sky(lines: list[str], ref: dt.date) -> dict[dt.date, str]:
    """통보문 서술문에서 날짜별 하늘상태를 뽑는다.

    통보문 표에는 기온과 파고만 있고 하늘상태·강수확률이 없다. 그래서 D+0~D+3 은
    서술문에서 읽어야 한다. 중기예보(D+4~)는 표에 하늘상태가 따로 있다.
    """
    out: dict[dt.date, str] = {}
    for line in lines:
        m = DAILY_LINE_RE.match(line)
        if not m:
            continue
        date = _resolve_date(int(m.group(1)), ref)
        sky = _sky_from_line(m.group(2))
        if date and sky:
            out[date] = sky
    return out


def fetch_notice(
    now: dt.datetime, region: Region = NATIONWIDE
) -> tuple[dict[dt.date, ScrapedDay], Narrative]:
    url = f"{NOTICE_URL}?stnId={region.notice_stn}"
    soup = _get_soup(url)
    issued = _issued_at(soup)
    ref = (issued or now).date()

    rows: dict[str, list[str]] = {}
    header: list[str] = []
    for tbl in soup.select("table"):
        cells0 = [c.get_text(" ", strip=True) for c in tbl.select("tr")[0].find_all(["th", "td"])]
        if not cells0 or "예보요소" not in cells0[0]:
            continue
        header = cells0
        for tr in tbl.select("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells and ("최저기온" in cells[0] or "최고기온" in cells[0]):
                rows[cells[0][:4]] = cells
        break

    if not header or "최저기온" not in rows or "최고기온" not in rows:
        raise ScrapeError(f"{url} 에서 기온 표를 찾지 못했습니다 (페이지 구조 변경 의심)")

    # 헤더에서 '오늘(10일)' 같은 칸만 날짜로 환산. '평년'/'어제' 는 건너뛴다.
    col_dates: dict[int, dt.date] = {}
    for idx, label in enumerate(header):
        if idx == 0 or "평년" in label or "어제" in label:
            continue
        m = DOM_RE.search(label)
        if not m:
            continue
        date = _resolve_date(int(m.group(1)), ref)
        if date:
            col_dates[idx] = date

    days: dict[dt.date, ScrapedDay] = {}
    for idx, date in col_dates.items():
        lo_hi = {}
        for key, cells in (("min", rows["최저기온"]), ("max", rows["최고기온"])):
            if idx >= len(cells):
                continue
            m = RANGE_RE.search(cells[idx])
            if m:
                lo_hi[key] = (float(m.group(1)), float(m.group(2)))
        if not lo_hi:
            continue
        day = ScrapedDay(date=date, source="통보문")
        if "min" in lo_hi:
            day.tmin_lo, day.tmin_hi = lo_hi["min"]
        if "max" in lo_hi:
            day.tmax_lo, day.tmax_hi = lo_hi["max"]
        days[date] = day

    if not days:
        raise ScrapeError(f"{url} 기온 표에서 날짜를 하나도 읽지 못했습니다")

    lines = _narrative_lines(soup)
    for date, sky in daily_sky(lines, ref).items():
        if date in days and not days[date].sky:
            days[date].sky = sky
    title = "기상청 예보 통보문" if region is NATIONWIDE else f"기상청 예보 통보문 ({region.label})"
    return days, Narrative(title, url, issued, lines)


# --------------------------------------------------------------------------- #
# 2) 중기예보 — 도시별 기온 표를 전국 범위로 집계 (D+4 ~ D+10)
# --------------------------------------------------------------------------- #

def _table_by_caption(soup: BeautifulSoup, keyword: str):
    for tbl in soup.select("table"):
        cap = tbl.caption.get_text(" ", strip=True) if tbl.caption else ""
        if keyword in cap:
            return tbl
    return None


def _header_dates(tbl, ref: dt.date) -> list[tuple[int, dt.date]]:
    """헤더의 '14일 (월)' 칸들을 (열 인덱스, 날짜) 로. 인덱스는 날짜 칸만 센 순번이다."""
    head = tbl.select_one("thead tr") or tbl.select("tr")[0]
    out: list[tuple[int, dt.date]] = []
    n = 0
    for th in head.find_all(["th", "td"]):
        label = th.get_text(" ", strip=True)
        m = DOM_RE.search(label)
        if not m or "지역" in label or "기온범위" in label:
            continue
        date = _resolve_date(int(m.group(1)), ref)
        if date:
            out.append((n, date))
        n += 1
    return out


def _row_group(cells, current: str | None) -> str | None:
    """지역 셀은 rowspan 으로 그룹 첫 행에만 나온다. 뒤 행들을 위해 값을 이어 나른다."""
    if cells and cells[0].get("rowspan"):
        return cells[0].get_text(" ", strip=True)
    return current


def fetch_mid_term(
    now: dt.datetime, region: Region = NATIONWIDE
) -> tuple[dict[dt.date, ScrapedDay], Narrative]:
    url = f"{MID_URL}?stnId1={region.mid_stn1}"
    if region.mid_stn2:
        url += f"&stnId2={region.mid_stn2}"
    soup = _get_soup(url)
    issued = _issued_at(soup)
    ref = (issued or now).date()

    temp_tbl = _table_by_caption(soup, "최저/최고기온")
    sky_tbl = _table_by_caption(soup, "강수 확률")
    if temp_tbl is None:
        raise ScrapeError(f"{url} 에서 기온 표를 찾지 못했습니다 (페이지 구조 변경 의심)")

    dates = _header_dates(temp_tbl, ref)
    n_dates = len(dates)
    days: dict[dt.date, ScrapedDay] = {}

    # --- 기온: 도시별 "18 / 27" 을 날짜별로 모아 전국 분포 범위를 만든다 ---
    mins: dict[dt.date, list[float]] = {d: [] for _, d in dates}
    maxs: dict[dt.date, list[float]] = {d: [] for _, d in dates}
    group: str | None = None
    for tr in temp_tbl.select("tbody tr"):
        raw_cells = tr.find_all(["th", "td"])
        group = _row_group(raw_cells, group)
        if region.mid_group and (group is None or region.mid_group not in group):
            continue
        cells = [c.get_text(" ", strip=True) for c in raw_cells]
        pairs = [c for c in cells if re.fullmatch(r"-?\d+(\.\d+)?\s*/\s*-?\d+(\.\d+)?", c)]
        if len(pairs) < n_dates:
            continue
        for (i, date), cell in zip(dates, pairs[:n_dates]):
            lo, hi = (float(x) for x in cell.split("/"))
            mins[date].append(lo)
            maxs[date].append(hi)

    for _, date in dates:
        if not mins[date]:
            continue
        days[date] = ScrapedDay(
            date=date,
            tmin_lo=min(mins[date]),
            tmin_hi=max(mins[date]),
            tmax_lo=min(maxs[date]),
            tmax_hi=max(maxs[date]),
            source="중기예보",
        )

    # --- 하늘상태·강수확률: 지역 × 날짜. 날짜별 대표값을 뽑는다 ---
    # 앞쪽 날짜는 오전/오후 두 칸, 뒤쪽 날짜(발표일 +8일 이후)는 하루 한 칸이라 열 수가 가변이다.
    # 페이지 안내: "18일~20일 은 오전, 오후 구분 없이 일별로 예보합니다."
    if sky_tbl is not None:
        sky_dates = [d for _, d in _header_dates(sky_tbl, ref)]
        per_date: dict[dt.date, tuple[list[str], list[int]]] = {d: ([], []) for d in sky_dates}
        for tr in sky_tbl.select("tbody tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if region.mid_group and not (cells and region.mid_group in cells[0]):
                continue
            vals = [c for c in cells if POP_RE.search(c)]
            if len(vals) < len(sky_dates):
                continue
            # 남는 칸 수가 곧 오전/오후로 쪼개진 날짜 수다
            split = min(len(vals) - len(sky_dates), len(sky_dates))
            cursor = 0
            for i, date in enumerate(sky_dates):
                width = 2 if i < split else 1
                skies, pops = per_date[date]
                for cell in vals[cursor : cursor + width]:
                    pm = POP_RE.search(cell)
                    if pm:
                        pops.append(int(pm.group(1)))
                    label = POP_RE.sub("", cell).strip()
                    if label:
                        skies.append(label)
                cursor += width
        for date, (skies, pops) in per_date.items():
            if date not in days:
                continue
            if skies:
                days[date].sky = max(set(skies), key=skies.count)  # 최빈값
            if pops:
                days[date].pop = max(pops)

    if not days:
        raise ScrapeError(f"{url} 기온 표에서 날짜를 하나도 읽지 못했습니다")

    title = "기상청 중기예보" if region is NATIONWIDE else f"기상청 중기예보 ({region.label})"
    return days, Narrative(title, url, issued, _narrative_lines(soup))


# --------------------------------------------------------------------------- #
# 합치기
# --------------------------------------------------------------------------- #

def scrape_range(
    now: dt.datetime,
    start: dt.date,
    num_days: int = 7,
    region: Region = NATIONWIDE,
) -> Scrape:
    """start 부터 num_days 일을 통보문(가까운 날) + 중기예보(먼 날) 로 채운다."""
    merged: dict[dt.date, ScrapedDay] = {}
    narratives: list[Narrative] = []
    errors: list[str] = []

    for fetch in (fetch_mid_term, fetch_notice):  # 통보문이 더 정확하므로 나중에 덮어쓴다
        try:
            days, narrative = fetch(now, region)
        except (requests.RequestException, ScrapeError) as exc:
            errors.append(f"{fetch.__name__}: {exc}")
            log.warning("수집 실패 — %s region=%s %s: %s",
                        fetch.__name__, region.key, type(exc).__name__, exc)
            continue
        merged.update(days)
        narratives.append(narrative)

    if not merged:
        raise ScrapeError("기상청 페이지에서 아무 값도 얻지 못했습니다: " + " / ".join(errors))

    window = {start + dt.timedelta(days=i) for i in range(num_days)}
    return Scrape(days={d: v for d, v in merged.items() if d in window}, narratives=narratives)


def scrape_week(now: dt.datetime, week_start: dt.date, region: Region = NATIONWIDE) -> Scrape:
    """월~일 한 주. 주간 게시(월요일 실행)가 쓴다."""
    return scrape_range(now, week_start, 7, region)
