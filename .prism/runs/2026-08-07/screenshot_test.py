"""Playwright screenshot script for Prism's new features (Phase 5 verification)."""
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"
SCREENSHOT_DIR = "/home/user/prism/.prism/runs/2026-08-07"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()

    print("Loading app...")
    page.goto(BASE_URL, timeout=60000)
    page.wait_for_timeout(3000)

    # Screenshot landing page
    page.screenshot(path=f"{SCREENSHOT_DIR}/01_landing_dark.png", full_page=False)
    print("Captured landing page")

    # Try to find and click a sample dataset button
    try:
        page.wait_for_selector("text=Sales", timeout=10000)
        page.click("text=Sales")
        page.wait_for_timeout(4000)
    except Exception as e:
        print(f"Could not click sample dataset by text 'Sales': {e}")
        # Try alternate approach - look for buttons
        buttons = page.query_selector_all("button")
        print(f"Found {len(buttons)} buttons")
        for b in buttons[:20]:
            print("  -", b.inner_text()[:50])

    page.wait_for_timeout(3000)
    page.screenshot(path=f"{SCREENSHOT_DIR}/02_after_load.png", full_page=False)
    print("Captured after-load screenshot")

    browser.close()
    print("Done")
