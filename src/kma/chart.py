"""기상청 분석일기도 PNG 를 정적 저장소에서 바로 내려받음.

URL 시각은 UTC 00·12시뿐이고 약 2일만 보관함. 성공 여부는 PNG 매직바이트로 봄 — 없는 시각도
404 가 아니라 200 + HTML 오류 페이지가 옴.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import requests

from src.common.config import KST, UA, UTC

BASE = "https://www.weather.go.kr/w/repositary/image/cht/img"
REFERER = "https://www.weather.go.kr/w/image/chart/analysis.do"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

PRODUCT_LABEL = {
    "surf": "지상일기도",
    "ghmd_s24": "지상 24시간 예상일기도",
}


@dataclass(frozen=True)
class Chart:
    product: str
    valid_utc: dt.datetime
    url: str
    png: bytes

    @property
    def valid_kst(self) -> dt.datetime:
        return self.valid_utc.astimezone(KST)

    @property
    def label(self) -> str:
        base = PRODUCT_LABEL.get(self.product, self.product)
        return f"{base} ({self.valid_kst:%m월 %d일 %H시} KST 기준)"

    @property
    def filename(self) -> str:
        return f"{self.product}_{self.valid_utc:%Y%m%d%H}.png"


def _slots(now_utc: dt.datetime, back: int) -> list[dt.datetime]:
    anchor = now_utc.replace(minute=0, second=0, microsecond=0)
    anchor = anchor.replace(hour=12 if anchor.hour >= 12 else 0)
    return [anchor - dt.timedelta(hours=12 * i) for i in range(back)]


def fetch_latest_chart(
    product: str = "surf",
    *,
    now: dt.datetime | None = None,
    back: int = 5,
    timeout: float = 30.0,
) -> Chart:
    now_utc = (now or dt.datetime.now(tz=UTC)).astimezone(UTC)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Referer": REFERER,
        }
    )

    tried: list[str] = []
    for slot in _slots(now_utc, back):
        url = f"{BASE}/{product}_{slot:%Y%m%d%H}.png"
        tried.append(url)
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException:
            continue
        body = resp.content
        if resp.status_code == 200 and body.startswith(PNG_MAGIC):
            return Chart(product=product, valid_utc=slot, url=url, png=body)

    raise RuntimeError(
        "사용 가능한 일기도를 찾지 못했습니다. 시도한 URL:\n  " + "\n  ".join(tried)
    )
