"""HTML 을 헤드리스 Chromium 으로 찍어 PNG 로 만듦."""
from __future__ import annotations

CARD_WIDTH = 700  # 카드·지도 폭을 맞춰 슬랙 미리보기에서 나란히 보이게 함


def capture(markup: str, *, width: int = CARD_WIDTH, scale: int = 2) -> bytes:
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
