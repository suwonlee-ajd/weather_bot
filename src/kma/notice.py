"""예보 통보문 — 전국 아침·낮 기온 범위와 총괄예보관 서술 (오전 발표 기준 D+0~D+3)."""
from __future__ import annotations

import datetime as dt
import re

from src.kma.page import (
    BASE,
    DOM_RE,
    RANGE_RE,
    Narrative,
    ScrapedDay,
    ScrapeError,
    _get_soup,
    _issued_at,
    _narrative_lines,
    _resolve_date,
)
from src.kma.regions import NATIONWIDE, Region

NOTICE_URL = f"{BASE}/w/forecast/notice.do"


# "○ (오늘, 12일) 가끔 구름많음, ..." 에서 날짜와 하늘상태를 뽑음.
DAILY_LINE_RE = re.compile(r"^○\s*\([^,)]*,\s*(\d{1,2})일\)\s*(.+)$")


# 서술문의 하늘상태 표현을 표 값과 같은 어휘로 맞춤 (앞에 오는 것이 우선)
SKY_WORDS = ("흐리", "구름많", "구름 많", "대체로 맑", "맑")


SKY_CANON = {"흐리": "흐림", "구름많": "구름많음", "구름 많": "구름많음",
             "대체로 맑": "맑음", "맑": "맑음"}


RAIN_WORDS = ("비", "눈", "소나기", "빗방울")


def _sky_from_line(text: str) -> str | None:
    """서술문에서 대표 하늘상태 하나. 비/눈이 있으면 그것을 우선함."""
    for word in RAIN_WORDS:
        if word in text:
            # '빗방울' 처럼 약한 표현도 비로 봄 — 우산 여부가 갈리는 정보
            base = next((SKY_CANON[w] for w in SKY_WORDS if w in text), "흐림")
            return f"{base}, 비" if word != "눈" else f"{base}, 눈"
    for word in SKY_WORDS:
        if word in text:
            return SKY_CANON[word]
    return None


def lines_for_dates(lines: list[str], ref: dt.date,
                    window: set[dt.date]) -> list[str]:
    """서술 줄 중 물어본 날짜에 해당하는 것만 고름.

    "○ (모레, 14일) ..." 처럼 날짜가 박힌 줄은 그 날짜가 window 에 있을 때만 남김.
    날짜가 없는 줄(□ 종합, ○ (기온)/(하늘상태) 같은 기간 전체 서술)은 그대로 남김 —
    어느 날을 물어도 유효함.

    날짜가 박힌 줄이 하나도 안 맞으면 기간 전체 서술만 돌아감 — 물은 날과
    다른 날의 이야기를 붙이느니 덜 보여주는 쪽이 나음.
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
    """통보문 서술문에서 날짜별 하늘상태를 뽑음.

    D+0~D+3 은 서술문에서 읽음 — 통보문 표에는 기온과 파고만 있고 하늘상태·강수확률이
    없음. 중기예보(D+4~)는 표에 하늘상태가 따로 있음.
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

    # 헤더에서 '오늘(10일)' 같은 칸만 날짜로 환산. '평년'/'어제' 는 건너뜀.
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
