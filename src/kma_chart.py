"""기상청 일기도(분석일기도) PNG 원본을 직접 내려받는다.

페이지를 렌더링(Selenium 등)하지 않고 파일명 규칙으로 바로 받는다. 날씨누리 분석일기도
페이지(https://www.weather.go.kr/w/image/chart/analysis.do)는 아래 정적 저장소의 PNG를
<img>로 띄우기만 한다.

    https://www.weather.go.kr/w/repositary/image/cht/img/{product}_{YYYYMMDDHH}.png
      - YYYYMMDDHH 는 **UTC** 기준
      - surf(지상일기도) / ghmd_s24(지상 24시간 예상) 모두 00, 12 UTC 만 존재
        (= 09시, 21시 KST)
      - 보관 기간이 약 2일이라 오래된 일자는 사라진다

주의: 상태코드가 아니라 PNG 매직바이트로 검증한다. 존재하지 않는 시각을 요청해도 404가 아니라
**HTTP 200 + 4KB짜리 HTML 오류 페이지**가 돌아온다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import requests

from .config import KST, UA, UTC

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
    """현재 시각 이전의 00/12 UTC 발표 시각을 최신순으로."""
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
    """가장 최근에 실제로 올라와 있는 일기도 PNG를 반환한다."""
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
        # 200 + HTML 오류 페이지를 걸러내는 유일하게 믿을 수 있는 방법
        if resp.status_code == 200 and body.startswith(PNG_MAGIC):
            return Chart(product=product, valid_utc=slot, url=url, png=body)

    raise RuntimeError(
        "사용 가능한 일기도를 찾지 못했습니다. 시도한 URL:\n  " + "\n  ".join(tried)
    )
