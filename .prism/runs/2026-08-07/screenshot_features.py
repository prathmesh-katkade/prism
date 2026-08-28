"""Playwright screenshot script — captures the 3 new features across
desktop/mobile x dark/light."""
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"
SCREENSHOT_DIR = "/home/user/prism/.prism/runs/2026-08-07"
CHROME_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}


def _scroll_main(page, delta_y):
    page.evaluate(f"""
        document.querySelectorAll('section, div[data-testid="stAppViewContainer"], div[data-testid="stMain"]')
            .forEach(el => {{ el.scrollTop += {delta_y}; }});
        window.scrollBy(0, {delta_y});
    """)
    page.wait_for_timeout(400)


def load_sales_dataset(page):
    page.goto(BASE_URL, timeout=60000)
    page.wait_for_timeout(3000)
    page.click("text=Load Sales")
    page.wait_for_timeout(4000)
    try:
        page.click("text=Got it, dismiss", timeout=3000)
        page.wait_for_timeout(500)
    except Exception:
        pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH)

        # ---- Desktop, dark theme (default) ----
        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_sales_dataset(page)
        _scroll_main(page, 350)
        page.screenshot(path=f"{SCREENSHOT_DIR}/03_overview_auto_insights_desktop_dark.png", full_page=False)
        print("Captured: Overview w/ Auto-Insights (desktop, dark)")
        ctx.close()

        # ---- Mobile, dark theme ----
        ctx = browser.new_context(viewport=VIEWPORTS["mobile"])
        page = ctx.new_page()
        load_sales_dataset(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/04a_mobile_dark_top.png", full_page=False)
        _scroll_main(page, 400)
        page.screenshot(path=f"{SCREENSHOT_DIR}/04b_mobile_dark_scroll400.png", full_page=False)
        _scroll_main(page, 400)
        page.screenshot(path=f"{SCREENSHOT_DIR}/04c_mobile_dark_scroll800.png", full_page=False)
        _scroll_main(page, 400)
        page.screenshot(path=f"{SCREENSHOT_DIR}/04d_mobile_dark_scroll1200.png", full_page=False)
        print("Captured: Overview w/ Auto-Insights (mobile, dark) — multi-scroll")
        ctx.close()

        browser.close()


if __name__ == "__main__":
    main()
