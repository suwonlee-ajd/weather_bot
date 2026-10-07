"""중기예보 — 도시별 기온 표를 전국 범위로 모으고 하늘상태·강수확률 (D+4~D+10)."""
from __future__ import annotations

import datetime as dt
import re

from bs4 import BeautifulSoup

from src.kma.page import (
    BASE,
    DOM_RE,
    POP_RE,
    Narrative,
    ScrapedDay,
    ScrapeError,
    _get_soup,
    _issued_at,
    _narrative_lines,
    _resolve_date,
)
from src.kma.regions import NATIONWIDE, Region

MID_URL = f"{BASE}/w/forecast/overall/mid-term.do"


def _table_by_caption(soup: BeautifulSoup, keyword: str):
    for tbl in soup.select("table"):
        cap = tbl.caption.get_text(" ", strip=True) if tbl.caption else ""
        if keyword in cap:
            return tbl
    return None


def _header_dates(tbl, ref: dt.date) -> list[tuple[int, dt.date]]:
    """헤더의 '14일 (월)' 칸들을 (열 인덱스, 날짜) 로. 인덱스는 날짜 칸만 센 순번."""
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
    """지역 그룹 값을 뒤 행으로 이어 넘김. 지역 셀은 rowspan 으로 그룹 첫 행에만 나옴."""
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

    # --- 기온: 도시별 "18 / 27" 을 날짜별로 모아 전국 분포 범위를 만듦 ---
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

    # --- 하늘상태·강수확률: 지역 × 날짜. 날짜별 대표값을 뽑음 ---
    # 열 수는 가변 — 앞쪽 날짜는 오전/오후 두 칸, 뒤쪽 날짜(발표일 +8일 이후)는 하루 한 칸.
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
            # 남는 칸 수가 곧 오전/오후로 쪼개진 날짜 수
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
