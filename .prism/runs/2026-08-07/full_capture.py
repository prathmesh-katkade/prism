"""
Full Phase-5 screenshot capture — Auto-Insights, Regression Diagnostics, and
STL Decomposition — across desktop/mobile x dark/light.
"""
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"
DIR = "/home/user/prism/.prism/runs/2026-08-07"
CHROME_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

DESKTOP = {"width": 1440, "height": 1000}
MOBILE = {"width": 390, "height": 844}


def scroll_main(page, delta_y):
    page.evaluate(f"""
        document.querySelectorAll('section, div[data-testid="stAppViewContainer"], div[data-testid="stMain"]')
            .forEach(el => {{ el.scrollTop += {delta_y}; }});
        window.scrollBy(0, {delta_y});
    """)
    page.wait_for_timeout(400)


def open_app_and_load(page, sample_button_text, theme_light=False):
    page.goto(BASE_URL, timeout=60000)
    page.wait_for_timeout(2500)
    if theme_light:
        page.click("text=App Preferences")
        page.wait_for_timeout(500)
        # Streamlit selectbox — click to open, then pick Arctic (Light)
        page.click('[data-testid="stSelectbox"]')
        page.wait_for_timeout(400)
        page.click("text=Arctic (Light)")
        page.wait_for_timeout(1000)
    page.click(f"text={sample_button_text}")
    page.wait_for_timeout(4000)
    try:
        page.click("text=Got it, dismiss", timeout=2500)
        page.wait_for_timeout(400)
    except Exception:
        pass


def click_nav(page, label):
    """Click a top-level nav pill or, if not visible, open Advanced Tools popover."""
    try:
        page.click(f'button:has-text("{label}")', timeout=3000)
        page.wait_for_timeout(2500)
        return
    except Exception:
        pass
    # Try Advanced Tools popover
    try:
        page.click("text=Advanced Tools", timeout=3000)
        page.wait_for_timeout(600)
        page.click(f'button:has-text("{label}")', timeout=3000)
        page.wait_for_timeout(2500)
    except Exception as e:
        print(f"  ! Could not navigate to {label}: {e}")


def capture_auto_insights(page, viewport_name, theme_name):
    scroll_main(page, 350)
    page.screenshot(path=f"{DIR}/auto_insights_{viewport_name}_{theme_name}.png", full_page=False)
    print(f"  Captured auto_insights_{viewport_name}_{theme_name}")


def capture_regression_diagnostics(page, viewport_name, theme_name):
    click_nav(page, "ML Lab")
    page.wait_for_timeout(1000)
    # Select revenue as target (should default to first column, may need to pick)
    try:
        # Target column selectbox is usually the first one on the page
        selects = page.query_selector_all('[data-testid="stSelectbox"]')
        if selects:
            selects[0].click()
            page.wait_for_timeout(400)
            page.click("text=revenue", timeout=2000)
            page.wait_for_timeout(800)
    except Exception as e:
        print(f"  ! Could not set target column: {e}")

    try:
        page.click('button:has-text("Run Baseline Models")', timeout=5000)
        page.wait_for_timeout(6000)
    except Exception as e:
        print(f"  ! Could not run baseline models: {e}")
        return

    try:
        page.click('button:has-text("Run Regression Diagnostics")', timeout=5000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print(f"  ! Could not run regression diagnostics: {e}")
        return

    page.screenshot(path=f"{DIR}/regression_diag_{viewport_name}_{theme_name}.png", full_page=False)
    print(f"  Captured regression_diag_{viewport_name}_{theme_name}")


def capture_stl_decomposition(page, viewport_name, theme_name):
    click_nav(page, "Forecasting")
    page.wait_for_timeout(1500)
    try:
        page.click('button:has-text("Run Decomposition")', timeout=5000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print(f"  ! Could not run decomposition: {e}")
        return
    scroll_main(page, 400)
    page.screenshot(path=f"{DIR}/stl_decomp_{viewport_name}_{theme_name}.png", full_page=False)
    print(f"  Captured stl_decomp_{viewport_name}_{theme_name}")


def run_pass(browser, viewport, viewport_name, theme_light, theme_name):
    print(f"\n=== {viewport_name} / {theme_name} ===")
    ctx = browser.new_context(viewport=viewport)
    page = ctx.new_page()
    open_app_and_load(page, "Load Sales", theme_light=theme_light)
    capture_auto_insights(page, viewport_name, theme_name)
    capture_regression_diagnostics(page, viewport_name, theme_name)
    capture_stl_decomposition(page, viewport_name, theme_name)
    ctx.close()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH)
        run_pass(browser, DESKTOP, "desktop", False, "dark")
        run_pass(browser, DESKTOP, "desktop", True, "light")
        run_pass(browser, MOBILE, "mobile", False, "dark")
        run_pass(browser, MOBILE, "mobile", True, "light")
        browser.close()


if __name__ == "__main__":
    main()
