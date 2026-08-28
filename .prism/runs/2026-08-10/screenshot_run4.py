"""Playwright screenshot script — Run 4 (2026-08-10, second session):
Ensemble Anomaly Consensus panel, native-theme dataframe fix (light theme),
and the mobile Atlas side-panel reflow fix.
"""
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"
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


def load_ensemble_demo_csv(page):
    page.goto(BASE_URL, timeout=60000)
    page.wait_for_timeout(3000)
    page.set_input_files('input[type="file"]', f"{SCREENSHOT_DIR}/ensemble_demo.csv")
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


def open_anomaly_expander_ensemble(page):
    page.get_by_text("Anomaly Detection", exact=True).click()
    page.wait_for_timeout(500)
    try:
        page.get_by_text("Ensemble mode", exact=False).click(timeout=3000)
        page.wait_for_timeout(300)
    except Exception as e:
        print(f"ensemble checkbox click failed: {e}")
    try:
        # NOTE: the Atlas side panel also has a lowercase "Find anomalies"
        # quick-action chip — get_by_role with exact=True (case-sensitive)
        # is required here, plain text= matched the wrong element.
        page.get_by_role("button", name="Find Anomalies", exact=True).click(timeout=3000)
        page.wait_for_timeout(3000)
    except Exception as e:
        print(f"find anomalies click failed: {e}")


def open_missing_outliers_tables(page):
    # Overview tab is default — the Missing Values / Outliers tables render
    # near the top, right after the PII/quality section.
    page.wait_for_timeout(500)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH)

        # ---- Desktop, dark: Ensemble Anomaly Consensus panel ----
        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_ensemble_demo_csv(page)
        open_anomaly_expander_ensemble(page)
        _scroll_main(page, 900)
        page.screenshot(path=f"{SCREENSHOT_DIR}/07_ensemble_anomaly_desktop_dark.png", full_page=False)
        print("Captured: ensemble anomaly panel (desktop, dark)")
        ctx.close()

        # ---- Desktop, light theme: dataframe styling fix + ensemble panel ----
        ctx = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = ctx.new_page()
        load_ensemble_demo_csv(page)
        switch_to_light_theme(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/08_overview_dataframes_desktop_light.png", full_page=False)
        print("Captured: Overview dataframes, light theme, native colors (desktop)")
        open_anomaly_expander_ensemble(page)
        _scroll_main(page, 900)
        page.screenshot(path=f"{SCREENSHOT_DIR}/09_ensemble_anomaly_desktop_light.png", full_page=False)
        print("Captured: ensemble anomaly panel (desktop, light)")
        ctx.close()

        # ---- Mobile, dark: Atlas side panel reflow fix ----
        ctx = browser.new_context(viewport=VIEWPORTS["mobile"])
        page = ctx.new_page()
        load_ensemble_demo_csv(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/10_atlas_panel_reflow_mobile_dark.png", full_page=False)
        print("Captured: Atlas panel reflow (mobile, dark)")
        _scroll_main(page, 1400)
        page.screenshot(path=f"{SCREENSHOT_DIR}/11_atlas_panel_reflow_mobile_dark_scrolled.png", full_page=False)
        print("Captured: Atlas panel reflow scrolled (mobile, dark)")
        ctx.close()

        browser.close()


if __name__ == "__main__":
    main()
