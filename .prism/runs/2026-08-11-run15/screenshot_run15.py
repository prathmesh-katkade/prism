"""Playwright verification script for Run 15 — Report Writer verification
badges (no new UI surface of their own; verified via generated HTML/PDF
content) and the Manual Chart Builder's new Facet Row (dual-axis small
multiples) channel. Both live on the "Visualize" nav section.

Navigation is st.segmented_control (button[kind="segmented_control..."] /
role="radio"), not st.tabs — labels are emoji + "\n\n" + text.

Usage: PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 screenshot_run15.py
"""
import os

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def shot(page, name):
    path = os.path.join(OUT_DIR, name)
    page.screenshot(path=path, full_page=False)
    print(f"  saved {name}")


def wait_streamlit(page, ms=1500):
    page.wait_for_timeout(ms)


def click_nav(page, label_substr):
    """Click a top-level segmented-control nav item by its visible text."""
    buttons = page.locator("button")
    n = buttons.count()
    for i in range(n):
        txt = buttons.nth(i).inner_text()
        if label_substr in txt:
            buttons.nth(i).click()
            return True
    return False


def select_by_label(page, label_substr, option_text):
    """Streamlit selectboxes expose role=combobox with an aria-label of the
    form "Selected <current value>. <Label>" — match on the trailing label
    substring (robust to DOM column order, unlike an xpath "following::"
    walk from the label text, which grabbed the wrong sibling column's
    select the first time this script was written).
    """
    combo = page.get_by_role("combobox", name=label_substr)
    combo.scroll_into_view_if_needed()
    combo.click()
    page.wait_for_timeout(400)
    page.get_by_role("option", name=option_text, exact=True).first.click()
    page.wait_for_timeout(500)


def load_hr_sample(page):
    page.get_by_role("button", name="Load Startup Funding").click()
    wait_streamlit(page, 3000)


def build_facet_row_chart(page):
    """Navigate to Visualize, scroll to Manual Chart Builder, pick Bar /
    sector / founded_year / facet=funding_round / facet_row=city, build.
    founded_year is genuinely numeric (unlike the currency-formatted
    salary/revenue/funding_amount columns most samples use), so the Bar
    chart takes the real aggregated-groupby path instead of the "no
    numeric Y" top-N-categories fallback.
    """
    click_nav(page, "Visualize")
    wait_streamlit(page, 2000)
    page.get_by_text("Manual Chart Builder", exact=False).first.scroll_into_view_if_needed()
    wait_streamlit(page, 600)

    select_by_label(page, "Chart type", "Bar")
    wait_streamlit(page, 800)
    select_by_label(page, "X-axis", "sector")
    wait_streamlit(page, 500)
    select_by_label(page, "Y-axis", "founded_year")
    wait_streamlit(page, 800)
    select_by_label(page, "Facet columns by", "funding_round")
    wait_streamlit(page, 500)
    select_by_label(page, "Facet rows by", "city")
    wait_streamlit(page, 800)


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ══════════════════════════════════════════════════════════════
        # Desktop, dark theme (default)
        # ══════════════════════════════════════════════════════════════
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE_URL)
        wait_streamlit(page, 3000)
        shot(page, "01_desktop_dark_landing.png")

        load_hr_sample(page)
        page.evaluate("window.scrollTo(0,0)")
        wait_streamlit(page, 500)
        shot(page, "02_desktop_dark_overview.png")

        build_facet_row_chart(page)
        shot(page, "03_desktop_dark_facet_row_controls.png")

        page.get_by_role("button", name="Build Chart").click()
        wait_streamlit(page, 3000)
        page.get_by_role("button", name="Build Chart").scroll_into_view_if_needed()
        wait_streamlit(page, 600)
        shot(page, "04_desktop_dark_facet_row_chart_built.png")

        # Scroll further to Auto-Report Writer (same Visualize section)
        page.get_by_text("Auto-Report Writer", exact=False).first.scroll_into_view_if_needed()
        wait_streamlit(page, 600)
        shot(page, "05_desktop_dark_report_writer_no_key.png")

        page.close()

        # ══════════════════════════════════════════════════════════════
        # Desktop, light (Arctic) theme
        # ══════════════════════════════════════════════════════════════
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE_URL)
        wait_streamlit(page, 3000)
        load_hr_sample(page)
        page.evaluate("window.scrollTo(0,0)")
        wait_streamlit(page, 500)

        # Sidebar "App Preferences" expander holds the theme selector.
        try:
            prefs = page.get_by_text("App Preferences", exact=False).first
            prefs.click()
            wait_streamlit(page, 600)
            theme_label = page.get_by_text("Theme", exact=False).first
            theme_label.scroll_into_view_if_needed()
            wait_streamlit(page, 400)
            combo = theme_label.locator("xpath=following::div[@data-baseweb='select'][1]")
            combo.click()
            wait_streamlit(page, 400)
            page.get_by_text("Arctic", exact=False).first.click()
            wait_streamlit(page, 1500)
        except Exception as e:
            print(f"  theme switch failed: {e}")

        page.evaluate("window.scrollTo(0,0)")
        wait_streamlit(page, 500)
        shot(page, "06_desktop_light_overview.png")

        build_facet_row_chart(page)
        page.get_by_role("button", name="Build Chart").click()
        wait_streamlit(page, 3000)
        page.get_by_role("button", name="Build Chart").scroll_into_view_if_needed()
        wait_streamlit(page, 600)
        shot(page, "07_desktop_light_facet_row_chart_built.png")

        page.get_by_text("Auto-Report Writer", exact=False).first.scroll_into_view_if_needed()
        wait_streamlit(page, 600)
        shot(page, "08_desktop_light_report_writer_no_key.png")

        page.close()

        # ══════════════════════════════════════════════════════════════
        # Mobile, dark theme
        # ══════════════════════════════════════════════════════════════
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(BASE_URL)
        wait_streamlit(page, 3000)
        shot(page, "09_mobile_dark_landing.png")

        load_hr_sample(page)
        page.evaluate("window.scrollTo(0,0)")
        wait_streamlit(page, 500)
        shot(page, "10_mobile_dark_overview.png")

        build_facet_row_chart(page)
        shot(page, "11_mobile_dark_facet_row_controls.png")

        page.get_by_role("button", name="Build Chart").click()
        wait_streamlit(page, 3000)
        page.get_by_role("button", name="Build Chart").scroll_into_view_if_needed()
        wait_streamlit(page, 600)
        shot(page, "12_mobile_dark_facet_row_chart_built.png")

        overflow_w = page.evaluate("document.documentElement.scrollWidth")
        inner_w = page.evaluate("window.innerWidth")
        print(f"  mobile scrollWidth={overflow_w} innerWidth={inner_w} (overflow={'YES' if overflow_w > inner_w else 'no'})")

        page.get_by_text("Auto-Report Writer", exact=False).first.scroll_into_view_if_needed()
        wait_streamlit(page, 600)
        shot(page, "13_mobile_dark_report_writer_no_key.png")

        page.close()
        browser.close()
        print("DONE")


if __name__ == "__main__":
    run()
