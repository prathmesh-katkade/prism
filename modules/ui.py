"""
UI — the landing screen (hero, feature cards, command palette, sample
datasets, load-session), the site-wide footer, per-tab help expanders,
first-visit onboarding, and (v2 Part 2) the shared "delight" primitives used
across every tab: empty states, a sticky mini-header, a shimmer skeleton
loader, and rotating analyst-themed loading messages.

Kept separate from theme.py: theme.py owns *styling* (CSS + the Plotly
template); this module owns page *content* built out of that styling.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

DEVELOPER_NAME = "Prathmesh Katkade"
GITHUB_URL = "https://github.com/anonymousnotavailable"
LINKEDIN_URL = "https://linkedin.com/in/your-profile"

SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "samples"
SAMPLE_DATASETS = {
    "Sales": {
        "file": "sales_data.csv",
        "description": "500 retail orders — nulls, duplicates, and revenue stored as currency text (₹1,200).",
    },
    "HR": {
        "file": "hr_data.csv",
        "description": "300 employee records — nulls, duplicates, and salary stored as currency text (₹1,200).",
    },
    "Stocks": {
        "file": "stock_data.csv",
        "description": "400 daily OHLCV rows across 2 tickers — includes a multi-week date gap.",
    },
    "Startup Funding": {
        "file": "indian_startup_funding_messy.csv",
        "description": "274 Indian startup funding rounds — mixed currency/date formats, dupes. "
        "Also what Atlas's Demo Mode uses.",
    },
}

# Inline stroke-icons (Lucide-derived paths) — vector, themeable via
# `currentColor`, no emoji. Sized/colored by the .prism-card-icon CSS class.
_ICON_SPARKLES = (
    '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5'
    'l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063'
    'a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/>'
    '<path d="M4 17v2"/><path d="M5 18H3"/>'
)
_ICON_BAR_CHART = '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>'
_ICON_MESSAGE = '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>'
_ICON_TERMINAL = '<path d="m7 11 2-2-2-2"/><path d="M11 13h4"/><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>'
_ICON_DATABASE = '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>'


def _icon(paths: str) -> str:
    return (
        f'<svg class="prism-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )


FEATURE_CARDS = [
    (_ICON_SPARKLES, "Clean", "One-click null handling, dedup, and dtype fixes — with full undo history."),
    (_ICON_BAR_CHART, "Visualize", "Auto-picked charts per column type, plus a correlation heatmap."),
    (_ICON_MESSAGE, "Ask AI", "Chat with your data in plain English — typed or by voice."),
    (_ICON_TERMINAL, "SQL Lab", "Run raw SQL against your dataset via DuckDB, no server required."),
]

# Rotating loading-message pool — used in place of generic "Loading..." spinner
# text for the app's longer-running AI/stats/model calls.
LOADING_MESSAGES = [
    "Crunching correlations…",
    "Interrogating outliers…",
    "Reticulating scatterplots…",
    "Consulting the data gods…",
    "Chasing down duplicates…",
    "Untangling distributions…",
    "Whispering to the dataframe…",
    "Counting on pandas…",
    "Polishing p-values…",
    "Auditing the averages…",
    "Teaching the model some manners…",
    "Herding rows into columns…",
]

# Keyword -> tab label, for the landing screen's command palette. Order
# matters only in that the first substring match wins, so more specific
# phrases are listed before their more generic overlaps.
PALETTE_KEYWORDS: dict[str, str] = {
    "full analysis": "Auto Analyst",
    "auto analy": "Auto Analyst",
    "agent": "Auto Analyst",
    "clean": "Clean",
    "missing": "Clean",
    "duplicate": "Clean",
    "null": "Clean",
    "dashboard": "Visualize",
    "report": "Visualize",
    "visuali": "Visualize",
    "chart": "Visualize",
    "plot": "Visualize",
    "sql": "SQL Lab",
    "query": "SQL Lab",
    "ask": "AI Analyst",
    "chat": "AI Analyst",
    "question": "AI Analyst",
    "signific": "Stats Lab",
    "hypothes": "Stats Lab",
    "t-test": "Stats Lab",
    "anova": "Stats Lab",
    "stat": "Stats Lab",
    "forecast": "Forecasting",
    "predict": "Forecasting",
    "trend": "Forecasting",
    "cluster": "Clustering",
    "segment": "Clustering",
    "combine": "Combine",
    "join": "Combine",
    "merge": "Combine",
    "drift": "Combine",
    "compare": "Combine",
    "overview": "Overview",
    "quality": "Overview",
    "pii": "Overview",
    "privacy": "Overview",
    "anomaly": "Overview",
    "correlat": "Visualize",
}


def get_loading_message() -> str:
    """A random analyst-themed loading line, for spinners on longer AI/model calls."""
    return random.choice(LOADING_MESSAGES)


def match_palette_query(query: str) -> Optional[str]:
    """Best-effort keyword match from a free-text query to a tab name."""
    lowered = query.lower()
    for keyword, tab_label in PALETTE_KEYWORDS.items():
        if keyword in lowered:
            return tab_label
    return None


def render_hero() -> None:
    """Render the dimensional landing hero and its concise product promise.

    The decorative layers are deliberately CSS-only and ``aria-hidden`` so the
    page stays fast, themeable, and intelligible to screen readers.
    """
    st.markdown(
        """
        <section class="prism-hero" aria-labelledby="prism-hero-heading">
            <div class="prism-hero-glow glow-one" aria-hidden="true"></div>
            <div class="prism-hero-glow glow-two" aria-hidden="true"></div>
            <div class="prism-orbit orbit-one" aria-hidden="true"><i></i></div>
            <div class="prism-orbit orbit-two" aria-hidden="true"><i></i></div>
            <div class="prism-hero-content">
                <span class="prism-badge prism-ready"><span class="prism-live-dot"></span>Workspace ready</span>
                <div class="prism-kicker">FROM RAW DATA TO CLEAR DECISIONS</div>
                <h1 id="prism-hero-heading" class="prism-hero-title">PRISM</h1>
                <div class="prism-hero-subtitle">Your AI-powered data workspace</div>
                <p class="prism-hero-copy">
                    Clean, explore, visualize, and question any dataset in one focused workspace.
                    Start with your own file or a ready-made sample — no code required.
                </p>
                <div class="prism-hero-pills" aria-label="Product capabilities">
                    <span>Auto-clean</span><span>Visual insights</span><span>Natural-language analysis</span>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_workflow_strip() -> None:
    """Show the landing-page mental model in three quickly scannable steps."""
    st.markdown(
        """
        <div class="prism-workflow" aria-label="How Prism works">
            <div class="prism-workflow-step"><b>01</b><span><strong>Bring your data</strong><small>CSV or Excel, safely in-browser</small></span></div>
            <div class="prism-workflow-line" aria-hidden="true"></div>
            <div class="prism-workflow-step"><b>02</b><span><strong>Prism maps the mess</strong><small>Quality, types, anomalies, and patterns</small></span></div>
            <div class="prism-workflow-line" aria-hidden="true"></div>
            <div class="prism-workflow-step"><b>03</b><span><strong>Leave with answers</strong><small>Charts, SQL, forecasts, and reports</small></span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_feature_cards() -> None:
    """4 feature cards: Clean / Visualize / Ask AI / SQL Lab, staggered entrance.

    Streamlit renders each st.markdown() call as its own sibling element —
    you can't open a wrapping <div> in one call and close it in another and
    expect it to actually contain what's rendered in between. So the stagger
    is a per-card inline animation-delay instead of a CSS :nth-child rule
    keyed off a wrapper that would never really wrap anything.
    """
    cols = st.columns(len(FEATURE_CARDS))
    for i, (col, (icon_paths, title, desc)) in enumerate(zip(cols, FEATURE_CARDS)):
        with col:
            st.markdown(
                f"""
                <div class="prism-card" style="min-height:168px; animation-delay:{i * 0.06:.2f}s;">
                    {_icon(icon_paths)}
                    <div class="prism-card-title">{title}</div>
                    <div class="prism-card-desc">{desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_command_palette() -> tuple[Optional[str], Optional[str]]:
    """The landing screen's "what do you want to do?" search box.

    Returns (query, matched_tab) for this run — both None if nothing was
    typed. Doesn't load data or switch tabs itself; app.py decides what to
    do with a match (load a sample, remember which tab to jump to).
    """
    st.markdown("#### What do you want to do?")
    query = st.text_input(
        "Command palette",
        placeholder='Try "clean my messy data", "forecast next month", or "find segments"...',
        key="command_palette_query",
        label_visibility="collapsed",
    )
    if not query:
        return None, None

    matched_tab = match_palette_query(query)
    if matched_tab:
        st.markdown(
            f'<div class="glass-card prism-palette-hit">'
            f'Sounds like <b>{matched_tab}</b> is what you need — pick a sample below (or upload your '
            f"own) and Prism will jump you straight there.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("Not sure which tool that is — try a sample dataset below and explore the tabs.")
    return query, matched_tab


def render_tab_jump_script(tab_label: str) -> None:
    """Best-effort: click the tab whose visible text contains tab_label.

    Streamlit's tabs have no Python API to select one programmatically, so
    this reaches into the parent document via a small JS snippet (the
    standard workaround used across the Streamlit component ecosystem for
    this exact gap). If the DOM shape ever changes upstream and the click
    doesn't land, the user can just click the tab by hand — this is
    best-effort polish, not load-bearing navigation.
    """
    import streamlit.components.v1 as components

    safe_label = tab_label.replace("\\", "").replace('"', "").replace("\n", "")
    components.html(
        f"""
        <script>
        const target = "{safe_label}".trim().toLowerCase();
        const tryClick = () => {{
            const doc = window.parent.document;
            const tabs = doc.querySelectorAll('button[data-baseweb="tab"]');
            for (const tab of tabs) {{
                if (tab.innerText.trim().toLowerCase().includes(target)) {{
                    tab.click();
                    return true;
                }}
            }}
            return false;
        }};
        if (!tryClick()) {{ setTimeout(tryClick, 300); }}
        </script>
        """,
        height=0,
    )


def render_sample_buttons() -> Optional[str]:
    """Render the 3 'Try a sample dataset' cards. Returns the chosen label, or None."""
    st.markdown("#### Try a sample dataset")
    cols = st.columns(len(SAMPLE_DATASETS))
    chosen = None
    for i, (col, (label, info)) in enumerate(zip(cols, SAMPLE_DATASETS.items())):
        with col:
            st.markdown(
                f"""
                <div class="prism-card" style="min-height:96px; padding:1rem 1.1rem;
                            animation-delay:{i * 0.06:.2f}s;">
                    {_icon(_ICON_DATABASE)}
                    <div class="prism-card-title" style="font-size:0.92rem;">{label}</div>
                    <div class="prism-card-desc">{info["description"]}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(f"Load {label}", key=f"sample_{label}", use_container_width=True):
                chosen = label
    return chosen


def load_sample_dataframe(label: str):
    """Read a bundled sample CSV by label. Returns a pandas DataFrame."""
    import pandas as pd

    info = SAMPLE_DATASETS[label]
    return pd.read_csv(SAMPLE_DATA_DIR / info["file"])


def render_load_session_widget():
    """File uploader for restoring a previously saved .json session. Returns
    the uploaded file object (or None) — app.py owns the actual load/parsing.
    """
    st.markdown("#### Restore a saved session")
    return st.file_uploader("Upload a Prism session file (.json)", type=["json"], key="session_upload")


FOOTER_HTML = f"""
<div class="prism-footer">
    Developed by {DEVELOPER_NAME}
    &nbsp;·&nbsp;
    <a href="{GITHUB_URL}" target="_blank">GitHub</a>
    &nbsp;·&nbsp;
    <a href="{LINKEDIN_URL}" target="_blank">LinkedIn</a>
</div>
"""


def render_footer() -> None:
    """Site-wide footer — call once at the bottom of every page (landing and main app)."""
    st.markdown(FOOTER_HTML, unsafe_allow_html=True)


def render_help_expander(text: str) -> None:
    """A small '? Help' expander explaining the current tab in ~2 lines."""
    with st.expander("? Help"):
        st.caption(text)


def render_sticky_header(
    dataset_name: str, n_rows: int, n_cols: int, health_score: int, memory_usage: str = ""
) -> None:
    """Always-visible top-of-page dataset context chip (green dot = loaded,
    filename, shape, size) plus a health score readout, so context never
    scrolls out of view on a long tab.
    """
    if health_score >= 80:
        health_label, health_class = "Healthy", "ok"
    elif health_score >= 50:
        health_label, health_class = "Needs attention", "warn"
    else:
        health_label, health_class = "Poor", "warn"

    size_part = f' <span class="sep">&middot;</span> {memory_usage}' if memory_usage else ""
    st.markdown(
        f"""
        <div class="glass-card prism-sticky-header">
            <span class="prism-dataset-chip">
                <span class="dot" aria-hidden="true"></span>
                <span class="mono">{dataset_name}</span>
                <span class="sep">&middot;</span> <b>{n_rows:,} &times; {n_cols}</b>{size_part}
            </span>
            <span class="chip v-{health_class}">Health {health_score}/100 — {health_label}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_label(text: str) -> None:
    """HUD-styled section caption with a trailing rule (Column Profiler,
    Atlas Insight Feed, ...) — breaks a long tab into scannable zones.
    """
    st.markdown(f'<div class="prism-sec">{text}</div>', unsafe_allow_html=True)


def render_health_ring(score: int) -> None:
    """The 0-100 Data Health gauge: a conic-gradient ring (cyan -> indigo ->
    magenta sweep proportional to score, muted track for the remainder)
    with the number in the middle. Recomputed after every cleaning action
    so users watch the score climb — see data_engine.get_health_score().
    """
    score = max(0, min(100, score))
    sweep_deg = round(score / 100 * 360)
    mid_deg = round(sweep_deg * 0.55)
    ring = (
        f"conic-gradient(var(--prism-accent) 0deg, var(--prism-accent2) {mid_deg}deg, "
        f"var(--prism-accent3) {sweep_deg}deg, rgba(138,147,166,.15) {sweep_deg}deg)"
    )
    st.markdown(
        f"""
        <div class="prism-health-wrap">
            <div class="prism-health-ring" style="background:{ring};">
                <div class="in">{score}</div>
            </div>
            <div class="prism-health-label">Data Health</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _spark_bars(values: list[float]) -> str:
    """8-ish CSS bars (relative-height <i> tags) summarizing a column's
    shape — a bucketed histogram for numerics, top-N counts for
    categoricals, or a monthly trend for datetimes. Pure decoration: no
    axis, no tooltip, just a shape at a glance.
    """
    if not values:
        return ""
    peak = max(values) or 1
    bars = "".join(f'<i style="height:{max(6, round(v / peak * 100))}%"></i>' for v in values)
    return f'<div class="prism-spark" aria-hidden="true">{bars}</div>'


_CURRENCY_NAME_HINTS = ("amount", "revenue", "price", "salary", "cost", "funding", "value", "valuation", "fee", "income")


def render_column_profiler_grid(
    df: "pd.DataFrame", column_types: dict, quality: dict, india_mode: bool = False
) -> None:
    """Column Profiler: one card per column — type badge (NUM/CAT/DATE,
    color-coded), a CSS sparkline shaped from the column's own
    distribution, a missing-value bar, and key stats. Replaces a plain
    "detected types" table with something a user can actually scan.

    india_mode=True (India Mode toggle): numeric mean/std use Indian digit
    grouping (1,20,000), and columns whose name suggests currency
    (revenue, amount, salary, ...) get the compact ₹1.2L/₹3.4Cr form via
    modules.india.format_inr instead of plain grouping.
    """
    missing_by_col = quality.get("missing_by_column", {})
    cards = []
    for col in df.columns:
        col_type = column_types.get(col, "text")
        series = df[col]
        missing_pct = missing_by_col.get(col, 0)

        if col_type == "numeric":
            badge_cls, badge_txt = "b-num", "NUM"
            clean = series.dropna()
            if len(clean) > 0:
                n_bins = max(1, min(8, clean.nunique()))
                counts = pd.cut(clean, bins=n_bins, duplicates="drop").value_counts(sort=False)
                spark_values = counts.tolist()
                mean, std = clean.mean(), clean.std()
                if pd.notna(mean):
                    if india_mode:
                        from modules import india
                        is_currency = any(hint in col.lower() for hint in _CURRENCY_NAME_HINTS)

                        def _fmt(v: float, format_currency: bool = is_currency) -> str:
                            # Indian grouping is a no-op under 1,000 — for small
                            # stats (e.g. an average of 7.4), prefer the plain
                            # decimal over india.indian_comma_group() rounding
                            # it away to "7".
                            if format_currency:
                                return india.format_inr(v)
                            if abs(v) >= 1000:
                                return india.indian_comma_group(v)
                            return f"{v:,.1f}"

                        meta_left = f"μ {_fmt(mean)} &middot; σ {_fmt(std)}"
                    else:
                        meta_left = f"μ {mean:,.1f} &middot; σ {std:,.1f}"
                else:
                    meta_left = "no data"
            else:
                spark_values, meta_left = [], "no data"
            meta_right = f"{missing_pct}% missing"
        elif col_type == "categorical":
            badge_cls, badge_txt = "b-cat", "CAT"
            counts = series.value_counts().head(5)
            spark_values = counts.tolist()
            n_unique = series.nunique()
            top_val = counts.index[0] if len(counts) else "—"
            meta_left = f"{n_unique} unique &middot; top: {top_val}"
            meta_right = f"{missing_pct}% missing"
        elif col_type == "datetime":
            badge_cls, badge_txt = "b-dt", "DATE"
            dt = pd.to_datetime(series, errors="coerce").dropna()
            if len(dt) > 0:
                monthly = dt.dt.to_period("M").value_counts().sort_index()
                spark_values = monthly.tolist()
                meta_left = f"{dt.min():%b %Y} &rarr; {dt.max():%b %Y}"
            else:
                spark_values, meta_left = [], "no data"
            meta_right = f"{missing_pct}% missing"
        else:
            badge_cls, badge_txt = "b-txt", "TEXT"
            spark_values = []
            meta_left = f"{series.nunique()} unique"
            meta_right = f"{missing_pct}% missing"

        cards.append(
            f'<div class="prism-col-card">'
            f'<div class="hd"><span class="cn" title="{col}">{col}</span>'
            f'<span class="prism-badge {badge_cls}">{badge_txt}</span></div>'
            f"{_spark_bars(spark_values)}"
            f'<div class="prism-miss"><i style="width:{min(100, missing_pct)}%"></i></div>'
            f'<div class="meta"><span>{meta_left}</span><span>{meta_right}</span></div>'
            f"</div>"
        )

    st.markdown(f'<div class="prism-col-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_assertion_results(results: list[dict]) -> None:
    """SQL Lab's Data Tests: one row per assertion — pass/fail/error badge,
    name, and a one-line detail. Same per-item-HTML-string-then-single-
    markdown-call construction as render_column_profiler_grid just above,
    reusing the .prism-badge pattern with new b-pass/b-fail/b-err variants
    (modules/theme.py) instead of inventing separate card CSS.
    """
    if not results:
        return
    badge_map = {"pass": ("b-pass", "PASS"), "fail": ("b-fail", "FAIL"), "error": ("b-err", "ERROR")}
    rows = []
    for r in results:
        badge_cls, badge_txt = badge_map.get(r.get("status"), ("b-txt", "?"))
        rows.append(
            f'<div class="prism-test-row">'
            f'<span class="prism-badge {badge_cls}">{badge_txt}</span>'
            f'<span class="tn">{r.get("name", "")}</span>'
            f'<span class="td">{r.get("detail", "")}</span>'
            f"</div>"
        )
    n_pass = sum(1 for r in results if r.get("status") == "pass")
    st.markdown(
        f'<div class="prism-test-summary">{n_pass}/{len(results)} passed</div>'
        f'<div class="prism-test-list">{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


# Shared with app.py's two "insight card list" render sites — Auto
# Analyst's "Run Full Analysis" findings (Run 10) and the AI Analyst tab's
# standalone "Generate Key Insights" button (this run). Factored out here,
# deliberately pure (no st.markdown call), so both call sites render
# identical markup and the badge logic is unit-testable on its own.
INSIGHT_VERIFICATION_BADGES = {
    "confirmed": (
        '<span class="prism-badge b-pass" title="Every number in this finding matches a '
        'value recomputed directly from the data.">✓ verified</span>'
    ),
    "flagged": (
        '<span class="prism-badge b-fail" title="At least one number here could not be '
        'matched to a recomputed value — double-check before citing.">⚠ unconfirmed</span>'
    ),
    "unverifiable": "",
}


def build_insight_cards_html(findings: list[str], verification: Optional[list[dict]] = None) -> str:
    """Render a list of Gemini-written findings as "insight-card" HTML,
    optionally with a modules.insight_verifier fact-check badge next to each
    finding number.

    `verification` (if given) is the same-order, same-length-or-shorter list
    of {"status": "confirmed"|"flagged"|"unverifiable", ...} dicts
    insight_verifier.verify_findings() returns — a finding past the end of
    `verification` (or with no verification passed at all) simply renders
    without a badge rather than erroring, since a badge is a nice-to-have
    annotation, never a precondition for showing the finding itself.

    Returns "" for an empty findings list (nothing to render) and the raw
    HTML string otherwise — callers pass it to st.markdown(..., unsafe_
    allow_html=True) themselves, same as every other *_html builder in this
    module family.
    """
    if not findings:
        return ""
    cards = []
    for i, finding in enumerate(findings):
        status = verification[i]["status"] if verification and i < len(verification) else None
        badge = INSIGHT_VERIFICATION_BADGES.get(status, "") if status else ""
        badge_html = f" {badge}" if badge else ""
        cards.append(
            f'<div class="insight-card"><div class="insight-number">FINDING {i + 1:02d}{badge_html}</div>'
            f'<div class="insight-text">{finding}</div></div>'
        )
    return "".join(cards)


def build_verification_caption(verification: list[dict]) -> Optional[str]:
    """One-line summary of a verification pass, e.g. "🔎 Fact-checked
    against the data: 3 finding(s) with confirmed figures, 1 with an
    unconfirmed number — verify before citing." Returns None when there's
    nothing worth captioning (empty list, or every finding unverifiable —
    i.e. no numeric claims were checkable at all), so callers can skip
    rendering a caption entirely rather than showing an empty/all-zero one.
    """
    confirmed_count = sum(1 for v in verification if v.get("status") == "confirmed")
    flagged_count = sum(1 for v in verification if v.get("status") == "flagged")
    if not confirmed_count and not flagged_count:
        return None
    tail = (
        f", {flagged_count} with an unconfirmed number — verify before citing."
        if flagged_count else "."
    )
    return f"🔎 Fact-checked against the data: {confirmed_count} finding(s) with confirmed figures{tail}"


def render_empty_state(icon: str, title: str, message: str) -> None:
    """A designed "nothing here yet" block (icon + title + one-line
    guidance) used in place of a bare st.info() across every tab's
    not-yet-run state. Callers add their own action button below it.
    """
    st.markdown(
        f"""
        <div class="glass-card prism-empty-state">
            <div class="icon">{icon}</div>
            <div class="title">{title}</div>
            <div class="message">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_shimmer(height: int = 90) -> None:
    """A shimmering skeleton placeholder — an alternative to a bare
    st.spinner for a couple of the app's longer-running actions.
    """
    st.markdown(f'<div class="prism-shimmer" style="height:{height}px;"></div>', unsafe_allow_html=True)


ONBOARDING_STEPS = [
    ("1. Overview", "Check the data-quality report, column health, and drill into any column."),
    ("2. Clean", "Use the sidebar's Data Processing panel — cleaning, Datetime Features, and Type Coercion tools."),
    ("3. Combine", "Optionally join a second file onto your active dataset."),
    ("4. Visualize", "Browse auto-generated charts or build your own in Manual mode."),
    ("5. SQL Lab", "Run raw SQL against your data, with example queries to get started."),
    ("6. AI Analyst", "Ask questions in plain English — by typing or by voice."),
]


def render_onboarding() -> None:
    """First-visit, dismissible step-by-step intro. Shown once per session
    unless dismissed; state lives in st.session_state.onboarding_dismissed.
    """
    if st.session_state.get("onboarding_dismissed"):
        return
    with st.expander("New here? Quick tour", expanded=True):
        for title, desc in ONBOARDING_STEPS:
            st.markdown(f"**{title}** — {desc}")
        if st.button("Got it, dismiss"):
            st.session_state.onboarding_dismissed = True
            st.rerun()
