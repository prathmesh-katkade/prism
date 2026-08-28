"""Playwright screenshot script — Run 31's new "Association interaction
check" panel (Stats Lab -> Hypothesis Sweep), the chi-square analog of the
existing ANOVA interaction check. Captures desktop dark, desktop light, and
mobile dark, matching prior runs' coverage."""
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"
SCREENSHOT_DIR = "/home/user/prism/.prism/runs/2026-08-12-run31"
CHROME_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
CSV_PATH = "/home/user/prism/.prism/runs/2026-08-12-run31/interaction_demo.csv"

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1100},
    "mobile": {"width": 390, "height": 844},
}


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


def scroll_main(page, delta_y):
    page.evaluate(
        f"""
        document.querySelectorAll('section, div[data-testid="stAppViewContainer"], div[data-testid="stMain"]')
            .forEach(el => {{ el.scrollTop += {delta_y}; }});
        window.scrollBy(0, {delta_y});
        """
    )
    page.wait_for_timeout(400)


def goto_tab(page, label, is_mobile=False):
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)
    page.click("text=Advanced Tools", timeout=5000)
    page.wait_for_timeout(500)
    page.get_by_text(label, exact=False).click(timeout=5000)
    page.wait_for_timeout(800)
    if is_mobile:
        page.keyboard.press("Escape")
        page.mouse.click(5, 5)
        page.wait_for_timeout(800)


def capture(page, prefix, is_mobile=False):
    goto_tab(page, "Stats Lab", is_mobile)
    if is_mobile:
        scroll_main(page, 1350)
    page.get_by_role("button", name="Run Hypothesis Sweep", exact=True).click(timeout=5000)
    page.wait_for_timeout(3000)

    # Expand the new "Association interaction check" finding so the
    # per-level Cramer's V table is visible in the screenshot.
    try:
        expander = page.get_by_text("association varies across", exact=False).first
        expander.click(timeout=5000)
        page.wait_for_timeout(600)
    except Exception as e:
        print(f"[{prefix}] expander click skipped: {e}")

    page.evaluate(
        """
        const el = [...document.querySelectorAll('*')].find(
          e => e.textContent && e.textContent.includes('Association interaction check')
        );
        if (el) el.scrollIntoView({block: 'center'});
        """
    )
    page.wait_for_timeout(500)

    page.screenshot(path=f"{SCREENSHOT_DIR}/{prefix}_association_interaction.png", full_page=False)
    print(f"Captured: {prefix}_association_interaction")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH)

        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_csv(page)
        capture(page, "01_desktop_dark")
        ctx.close()

        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_csv(page)
        switch_to_light_theme(page)
        capture(page, "02_desktop_light")
        ctx.close()

        ctx = browser.new_context(viewport=VIEWPORTS["mobile"])
        page = ctx.new_page()
        load_csv(page)
        capture(page, "03_mobile_dark", is_mobile=True)
        ctx.close()

        browser.close()


if __name__ == "__main__":
    main()
