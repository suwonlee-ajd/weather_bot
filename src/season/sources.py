"""단풍·벚꽃이 함께 쓰는 수집 — 기상청 계절 관측(JSONP)과 웨더아이 예상 게시물(PDF).

예외는 부르는 쪽 것(FoliageError · BlossomError)으로 냄 — error 로 넘겨받음.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import urllib.parse

import requests

from src.common.config import UA

WEATHERI_BASE = "https://www.weatheri.co.kr/board/"
WEATHERI_LIST = WEATHERI_BASE + "board03_list.php"
OUTLOOK_SOURCE = "웨더아이"


def get(url: str, *, error: type[Exception], params: dict | None = None, timeout: float = 20.0,
        referer: str = "") -> requests.Response:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise error(f"요청 실패 {url}: {exc}") from exc
    return resp


# --- 기상청 계절 관측 ---------------------------------------------------------

def jsonp(text: str, callback: str, what: str, error: type[Exception]) -> dict:
    """`{callback}({...})` 응답의 자료."""
    m = re.search(rf"{callback}\((\{{.*\}})\)", text, re.S)
    if not m:
        raise error(f"기상청 {what} 응답에서 자료를 찾지 못했습니다 (형식 변경 의심)")
    try:
        return json.loads(m.group(1))
    except ValueError as exc:
        raise error(f"기상청 {what} 응답을 읽지 못했습니다: {exc}") from exc


def stage_of(place: dict, stages: tuple[str, ...]) -> int:
    """관측 단계 0~2 — 글자가 바뀌어도 코드(sts 1~3)는 남음."""
    text = place.get("status") or ""
    if text in stages:
        return stages.index(text)
    try:
        return max(0, min(2, int(place.get("sts", "1")) - 1))
    except (TypeError, ValueError):       # "sts": null 이 와도 첫 단계로
        return 0


def stages_in(data: dict, stages: tuple[str, ...], what: str, error: type[Exception]) -> tuple[dict[str, int], bool]:
    """(장소별 단계, 서비스 중인지). 서비스 기간 밖이면 모두 첫 단계 — 지난 시즌 단계를 올해 것으로 읽지 않게."""
    places = data.get("places") or []
    if not places:
        raise error(f"기상청 {what} 응답에 관측 지점이 없습니다")
    in_service = bool(data.get("isService"))
    return {p["obsPlace"]: (stage_of(p, stages) if in_service else 0)
            for p in places if p.get("obsPlace")}, in_service


def shot_date(raw: str | None, year: int) -> dt.date | None:
    """촬영일. 올해 것이 아니면 버림 — 서비스 전에는 지난해 기록이 그대로 내려옴."""
    if not raw:
        return None
    try:
        d = dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None
    return d if d.year == year else None


# --- 웨더아이 예상 게시물 -----------------------------------------------------

def find_post(list_html: str, year: int, title: str) -> str | None:
    """게시판 목록에서 «{year}년 {title}» 게시물 주소. title 은 정규식."""
    m = re.search(rf"href=['\"]?(board03_read\.php\?id=\d+[^'\"\s>]*)['\"]?\s*>\s*{year}년\s*{title}", list_html)
    return urllib.parse.urljoin(WEATHERI_BASE, m.group(1)) if m else None


def pdf_link(post_html: str) -> str | None:
    """게시물에 붙은 PDF 주소. 파일명에 대괄호가 들어 있어([Weatheri]2026_maple.pdf) 인코딩함."""
    m = re.search(r"https?://[^\"'\s<>]+\.pdf", post_html, re.I)
    return urllib.parse.quote(m.group(0), safe=":/?&=%") if m else None


def posted_on(post_html: str, year: int) -> dt.date | None:
    """게시일 — 머리 표 날짜 칸의 글자색으로 집음.

    맨 위 특보 띠에도 오늘 날짜가 흘러가고, 작성자 칸이 빈 해(2026 벚꽃)가 있어 '관리자' 뒤를 찾으면 놓침.
    """
    m = re.search(rf"#124c78\">\s*({year})-(\d{{2}})-(\d{{2}})", post_html)
    return dt.date(*map(int, m.groups())) if m else None


def pdf_text(blob: bytes, error: type[Exception]) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:            # 현황만으로라도 답함 — 서버에서 uv sync 를 빠뜨린 경우
        raise error("pypdf 가 설치되지 않아 웨더아이 예상을 읽지 못합니다") from exc
    try:
        reader = PdfReader(io.BytesIO(blob))
        return "\n".join(p.extract_text(extraction_mode="layout") for p in reader.pages)
    except Exception as exc:              # pypdf 는 깨진 파일마다 다른 예외를 냄
        raise error(f"웨더아이 PDF 를 읽지 못했습니다: {exc}") from exc
