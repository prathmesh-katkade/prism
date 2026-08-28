"""Playwright screenshot script — Run 5's two UI changes: the Hypothesis
Sweep panel (Stats Lab tab) and the Feature Selection Engine panel (ML Lab
tab). Captures desktop dark, desktop light, and mobile dark, matching prior
runs' coverage."""
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8531"
SCREENSHOT_DIR = "/home/user/prism/.prism/runs/2026-08-10-run5"
CHROME_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
CSV_PATH = "/home/user/prism/samples/stock_data.csv"

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1100},
    "mobile": {"width": 390, "height": 844},
}


def scroll_main(page, delta_y):
    page.evaluate(
        f"""
        document.querySelectorAll('section, div[data-testid="stAppViewContainer"], div[data-testid="stMain"]')
            .forEach(el => {{ el.scrollTop += {delta_y}; }});
        window.scrollBy(0, {delta_y});
        """
    )
    page.wait_for_timeout(400)


def load_csv(page):
    page.goto(BASE_URL, timeout=60000)
    page.wait_for_timeout(3000)
    page.set_input_files('input[type="file"]', CSV_PATH)
    page.wait_for_timeout(4000)
    try:
        page.click("text=Got it, dismiss", timeout=3000)
        page.wait_for_timeout(500)
    except Exception:
        pass


def switch_to_light_theme(page):
    page.click("text=⚙️ App Preferences")
    page.wait_for_timeout(500)
    page.locator('div[data-testid="stSelectbox"]').first.click()
    page.wait_for_timeout(300)
    page.click("text=Arctic (Light)")
    page.wait_for_timeout(1500)


def goto_tab(page, label, is_mobile=False):
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)
    page.click("text=Advanced Tools", timeout=5000)
    page.wait_for_timeout(500)
    page.get_by_text(label, exact=False).click(timeout=5000)
    page.wait_for_timeout(800)
    if is_mobile:
        # the "Advanced Tools" popover doesn't auto-close on mobile after a
        # selection — close it explicitly, same as prior runs' scripts.
        page.keyboard.press("Escape")
        page.mouse.click(5, 5)
        page.wait_for_timeout(800)


def capture_stats_lab(page, prefix, is_mobile=False):
    goto_tab(page, "Stats Lab", is_mobile)
    if is_mobile:
        scroll_main(page, 1350)
    page.get_by_role("button", name="Run Hypothesis Sweep", exact=True).click(timeout=5000)
    page.wait_for_timeout(2500)
    if not is_mobile:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
        page.wait_for_timeout(400)
    page.screenshot(path=f"{SCREENSHOT_DIR}/{prefix}_hypothesis_sweep.png", full_page=False)
    print(f"Captured: {prefix}_hypothesis_sweep")


def capture_ml_lab(page, prefix, is_mobile=False):
    goto_tab(page, "ML Lab", is_mobile)
    if is_mobile:
        scroll_main(page, 900)
    page.get_by_role("combobox", name="Target column").click(timeout=3000)
    page.wait_for_timeout(400)
    page.get_by_role("option", name="close", exact=True).click(timeout=3000)
    page.wait_for_timeout(1000)
    try:
        # drop the high-cardinality 'date' column from the default feature
        # set — it's a raw string here (no datetime parsing applied), so
        # one-hot encoding it would add ~200 noisy columns to what should
        # be a clean regression demo (open/high/low/ticker/volume -> close)
        date_tag = page.locator('span[data-baseweb="tag"]').filter(
            has=page.locator('span[title="date"]')
        )
        date_tag.locator('svg[title="Delete"]').click(timeout=3000)
        page.wait_for_timeout(600)
    except Exception as e:
        print(f"Removing 'date' feature skipped: {e}")
    if is_mobile:
        scroll_main(page, 700)
    page.get_by_role("button", name="Run Feature Selection", exact=True).click(timeout=5000)
    for _ in range(20):
        page.wait_for_timeout(1000)
        if page.get_by_text("Crunching correlations").count() == 0 and page.get_by_text("Untangling distributions").count() == 0:
            break
    page.wait_for_timeout(1000)
    if is_mobile:
        scroll_main(page, 500)
    else:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
        page.wait_for_timeout(400)
    page.screenshot(path=f"{SCREENSHOT_DIR}/{prefix}_feature_selection.png", full_page=False)
    print(f"Captured: {prefix}_feature_selection")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH)

        # ---- Desktop, dark (default) ----
        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_csv(page)
        capture_stats_lab(page, "01_desktop_dark")
        capture_ml_lab(page, "02_desktop_dark")
        ctx.close()

        # ---- Desktop, light ----
        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_csv(page)
        switch_to_light_theme(page)
        capture_stats_lab(page, "03_desktop_light")
        capture_ml_lab(page, "04_desktop_light")
        ctx.close()

        # ---- Mobile, dark ----
        ctx = browser.new_context(viewport=VIEWPORTS["mobile"])
        page = ctx.new_page()
        load_csv(page)
        capture_stats_lab(page, "05_mobile_dark", is_mobile=True)
        ctx.close()

        ctx = browser.new_context(viewport=VIEWPORTS["mobile"])
        page = ctx.new_page()
        load_csv(page)
        capture_ml_lab(page, "06_mobile_dark", is_mobile=True)
        ctx.close()

        browser.close()


if __name__ == "__main__":
    main()
