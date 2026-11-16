"""HTML 을 헤드리스 Chromium 으로 찍어 PNG 로 만듦."""
from __future__ import annotations

import threading

CARD_WIDTH = 700  # 카드·지도 폭을 맞춰 슬랙 미리보기에서 나란히 보이게 함

_ARGS = ["--force-color-profile=srgb", "--font-render-hinting=none"]
# 한 번에 하나만 띄움 — 겹치면 메모리가 몰림(주간 게시의 카드·지도 동시 렌더, 멘션 봇의 동시 답)
_LOCK = threading.Lock()


def probe() -> None:
    """capture 와 같은 설정으로 띄웠다 닫음 — 점검용. 못 띄우면 예외."""
    from playwright.sync_api import sync_playwright

    with _LOCK, sync_playwright() as p:
        p.chromium.launch(args=_ARGS).close()


def capture(markup: str, *, width: int = CARD_WIDTH, scale: int = 2) -> bytes:
    from playwright.sync_api import sync_playwright

    with _LOCK, sync_playwright() as p:
        browser = p.chromium.launch(args=_ARGS)
        try:
            page = browser.new_page(viewport={"width": width, "height": 600}, device_scale_factor=scale)
            page.set_content(markup, wait_until="load")
            page.wait_for_timeout(150)  # 레이아웃 안정화
            return page.locator("#card").screenshot(type="png")
        finally:
            browser.close()
