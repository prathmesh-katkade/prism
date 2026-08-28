"""Targeted capture for Regression Diagnostics (all viewports/themes) and
STL Decomposition mobile — the pieces the first pass missed."""
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


def open_app_and_load(page, theme_light=False, mobile=False, sample="Load Sales"):
    page.goto(BASE_URL, timeout=60000)
    page.wait_for_timeout(3000)
    if mobile:
        # Sidebar is collapsed on narrow viewports — expand it first via the » toggle
        try:
            page.click('[data-testid="stSidebarCollapsedControl"] button', timeout=3000, force=True)
            page.wait_for_timeout(600)
        except Exception:
            pass
    if theme_light:
        try:
            page.click("text=App Preferences", timeout=8000, force=True)
            page.wait_for_timeout(600)
            page.click('[data-testid="stSelectbox"]', timeout=5000, force=True)
            page.wait_for_timeout(500)
            page.click("text=Arctic (Light)", timeout=5000, force=True)
            page.wait_for_timeout(1200)
        except Exception as e:
            print(f"  ! Theme switch failed: {e}")
    page.click(f"text={sample}", timeout=10000, force=True)
    page.wait_for_timeout(4500)
    try:
        page.click("text=Got it, dismiss", timeout=2500, force=True)
        page.wait_for_timeout(500)
    except Exception:
        pass


def open_advanced_tab(page, tab_label):
    """Open the Advanced Tools popover and click a tab inside it. Retries
    the popover click since it's occasionally intercepted by an animating
    sibling element right after page load."""
    page.wait_for_timeout(800)
    last_err = None
    for _attempt in range(3):
        try:
            page.click('button:has-text("Advanced Tools")', timeout=6000, force=True)
            page.wait_for_timeout(700)
            page.click(f'button:has-text("{tab_label}")', timeout=6000, force=True)
            page.wait_for_timeout(2500)
            return
        except Exception as e:
            last_err = e
            page.wait_for_timeout(1000)
    raise last_err


def capture_regression_diag(page, viewport_name, theme_name):
    try:
        open_advanced_tab(page, "ML Lab")
    except Exception as e:
        print(f"  ! Could not open ML Lab: {e}")
        return
    page.wait_for_timeout(1000)
    # Set target column to 'close' (stock closing price) — a genuinely
    # continuous numeric column so detect_task_type() picks "regression"
    # and the diagnostics button actually renders. (Sales sample's numeric
    # columns are either low-cardinality integers that trip the
    # classification heuristic, or currency stored as text.) Selected by
    # its <label> text, not index — the page also has hidden selectboxes
    # (e.g. the collapsed sidebar's theme picker) earlier in DOM order.
    try:
        target_select = None
        for s in page.query_selector_all('[data-testid="stSelectbox"]'):
            label = s.query_selector("label")
            if label and "Target column" in (label.inner_text() or ""):
                target_select = s
                break
        if target_select:
            target_select.click(force=True)
            page.wait_for_timeout(500)
            page.click('li:has-text("close")', timeout=3000, force=True)
            page.wait_for_timeout(1000)
        else:
            print("  ! Target column selectbox not found by label")
    except Exception as e:
        print(f"  ! Target column select issue (may already default correctly): {e}")

    try:
        page.click('button:has-text("Run Baseline Models")', timeout=8000, force=True)
        page.wait_for_timeout(7000)
    except Exception as e:
        print(f"  ! Could not run baseline models: {e}")
        return

    try:
        page.click('button:has-text("Run Regression Diagnostics")', timeout=8000, force=True)
        page.wait_for_timeout(4500)
    except Exception as e:
        print(f"  ! Could not run regression diagnostics: {e}")
        return

    scroll_main(page, 300)
    page.screenshot(path=f"{DIR}/regression_diag_{viewport_name}_{theme_name}.png", full_page=False)
    print(f"  ✅ Captured regression_diag_{viewport_name}_{theme_name}")


def capture_stl_mobile(page, viewport_name, theme_name):
    try:
        open_advanced_tab(page, "Forecasting")
    except Exception as e:
        print(f"  ! Could not open Forecasting: {e}")
        return
    try:
        page.click('button:has-text("Run Decomposition")', timeout=8000, force=True)
        page.wait_for_timeout(4500)
    except Exception as e:
        print(f"  ! Could not run decomposition: {e}")
        return
    scroll_main(page, 700)
    page.screenshot(path=f"{DIR}/stl_decomp_{viewport_name}_{theme_name}.png", full_page=False)
    print(f"  ✅ Captured stl_decomp_{viewport_name}_{theme_name}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH)

        # Desktop dark — Regression Diagnostics
        print("\n=== desktop / dark — Regression Diagnostics ===")
        ctx = browser.new_context(viewport=DESKTOP)
        page = ctx.new_page()
        open_app_and_load(page, theme_light=False, mobile=False)
        capture_regression_diag(page, "desktop", "dark")
        ctx.close()

        # Desktop light — Regression Diagnostics
        print("\n=== desktop / light — Regression Diagnostics ===")
        ctx = browser.new_context(viewport=DESKTOP)
        page = ctx.new_page()
        open_app_and_load(page, theme_light=True, mobile=False)
        capture_regression_diag(page, "desktop", "light")
        ctx.close()

        # Mobile dark — Regression Diagnostics + STL
        print("\n=== mobile / dark — Regression Diagnostics + STL ===")
        ctx = browser.new_context(viewport=MOBILE)
        page = ctx.new_page()
        open_app_and_load(page, theme_light=False, mobile=True)
        capture_regression_diag(page, "mobile", "dark")
        capture_stl_mobile(page, "mobile", "dark")
        ctx.close()

        browser.close()


if __name__ == "__main__":
    main()
