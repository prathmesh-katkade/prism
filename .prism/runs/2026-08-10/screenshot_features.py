"""Playwright screenshot script — captures this run's two UI changes
(anomaly narration button, Atlas proactive alert HUD orb) across
desktop/mobile x dark/light.
"""
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8513"
SCREENSHOT_DIR = "/home/user/prism/.prism/runs/2026-08-10"
CHROME_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}


def _scroll_main(page, delta_y):
    page.evaluate(
        f"""
        document.querySelectorAll('section, div[data-testid="stAppViewContainer"], div[data-testid="stMain"]')
            .forEach(el => {{ el.scrollTop += {delta_y}; }});
        window.scrollBy(0, {delta_y});
        """
    )
    page.wait_for_timeout(400)


def load_alert_demo_csv(page):
    """A crafted CSV with a 75%-missing column (triggers a HIGH-severity
    Auto-Insight -> Atlas alert HUD) and a planted numeric outlier
    (triggers Anomaly Detection)."""
    page.goto(BASE_URL, timeout=60000)
    page.wait_for_timeout(3000)
    page.set_input_files('input[type="file"]', f"{SCREENSHOT_DIR}/alert_demo.csv")
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


def open_anomaly_expander(page):
    page.get_by_text("Anomaly Detection", exact=True).click()
    page.wait_for_timeout(500)
    try:
        page.click("text=Find Anomalies", timeout=3000)
        page.wait_for_timeout(2500)
    except Exception:
        pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH)

        # ---- Desktop, dark (default): orb alert state on landing after load ----
        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_alert_demo_csv(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/01_orb_alert_desktop_dark.png", full_page=False)
        print("Captured: orb alert state (desktop, dark)")

        # ---- Anomaly Detection expander + narration button ----
        open_anomaly_expander(page)
        _scroll_main(page, 900)
        page.screenshot(path=f"{SCREENSHOT_DIR}/02_anomaly_narrate_button_desktop_dark.png", full_page=False)
        print("Captured: anomaly narrate button (desktop, dark)")
        try:
            page.click("text=Explain these anomalies with AI", timeout=3000)
            page.wait_for_timeout(4000)
            page.screenshot(path=f"{SCREENSHOT_DIR}/03_anomaly_narration_result_desktop_dark.png", full_page=False)
            print("Captured: anomaly narration result (desktop, dark)")
        except Exception as e:
            print(f"Narration click skipped/failed (expected without a live Gemini key): {e}")
        ctx.close()

        # ---- Desktop, light theme ----
        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_alert_demo_csv(page)
        switch_to_light_theme(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/04_orb_alert_desktop_light.png", full_page=False)
        open_anomaly_expander(page)
        _scroll_main(page, 900)
        page.screenshot(path=f"{SCREENSHOT_DIR}/05_anomaly_narrate_button_desktop_light.png", full_page=False)
        print("Captured: desktop light theme (orb alert + anomaly panel)")
        ctx.close()

        # ---- Mobile, dark ----
        ctx = browser.new_context(viewport=VIEWPORTS["mobile"])
        page = ctx.new_page()
        load_alert_demo_csv(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/06_orb_alert_mobile_dark.png", full_page=False)
        print("Captured: orb alert state (mobile, dark)")
        ctx.close()

        browser.close()


if __name__ == "__main__":
    main()
