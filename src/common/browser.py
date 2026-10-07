"""HTML 을 헤드리스 Chromium 으로 찍어 PNG 로 — 주간 카드와 단풍 지도가 함께 씀."""
from __future__ import annotations

CARD_WIDTH = 700  # 카드와 지도의 폭을 맞춤 — 슬랙 미리보기에서 나란히 보임


def capture(markup: str, *, width: int = CARD_WIDTH, scale: int = 2) -> bytes:
    """markup 의 #card 요소를 PNG 바이트로."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb", "--font-render-hinting=none"])
        try:
            page = browser.new_page(viewport={"width": width, "height": 600}, device_scale_factor=scale)
            page.set_content(markup, wait_until="load")
            page.wait_for_timeout(150)  # 레이아웃 안정화
            return page.locator("#card").screenshot(type="png")
        finally:
            browser.close()
