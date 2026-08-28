"""
Visualization — the smart chart picker. Every function returns a Plotly
figure (or None when the chart doesn't apply) so app.py and report.py can
both consume the same chart-building logic without duplicating it.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from modules import theme

# Registering the dark/cyan template here (module import time) — rather than
# only in app.py — means every chart is themed even when this module is used
# standalone, e.g. by the AI Analyst sandbox or a script/test that never
# touches app.py.
theme.apply_plotly_theme()

# Pie charts only read well with a handful of slices; beyond this, a bar chart
# of the top categories communicates the distribution more clearly.
PIE_CHART_MAX_CATEGORIES = 8
TOP_N_CATEGORIES = 10

# User-facing chart types offered in the Visualize tab's manual mode.
MANUAL_CHART_TYPES = ["Histogram", "Box", "Bar", "Pie", "Scatter", "Line"]
# Chart types where a Y-axis column is mandatory (not just an optional grouping).
MANUAL_CHART_TYPES_REQUIRING_Y = {"Scatter", "Line"}
# Chart types where an optional third "Color" column can split/group the marks —
# the encoding-channel slice toward a PyGWalker/Tableau-style grammar-of-graphics
# builder (Pie already encodes its one category via slices, so it's excluded).
MANUAL_CHART_TYPES_SUPPORTING_COLOR = {"Histogram", "Box", "Bar", "Scatter", "Line"}
# Chart types where an optional fourth "Facet" column splits the chart into a
# grid of small multiples (one subplot per category) instead of overlaying
# groups in a single plot — the next PyGWalker/Tableau-style encoding channel
# after Color. Same set as color support: Pie has no subplot concept of its
# own here (px.pie doesn't take facet_col) so it's excluded too.
MANUAL_CHART_TYPES_SUPPORTING_FACET = {"Histogram", "Box", "Bar", "Scatter", "Line"}
# Facets are full subplots, not just a color split, so a high-cardinality
# facet column would blow up into an unreadable (and slow-to-render) grid —
# cap to the N most frequent categories, same top-N-by-frequency convention
# TOP_N_CATEGORIES already uses for Bar/Pie.
MAX_FACET_CATEGORIES = 6
# How many facet subplots per row before wrapping to a new row.
FACET_COL_WRAP = 3
# The second facet dimension (row x column small multiples — the dual-axis
# faceting slice of the PyGWalker-style grammar-of-graphics builder). Capped
# tighter than MAX_FACET_CATEGORIES because it multiplies against the column
# facet's own cap (up to 6 x 4 = 24 subplots in the worst case, already a lot
# for a single chart) — a second uncapped dimension would make the grid
# unreadable and slow to render even faster than a single wide facet would.
MAX_FACET_ROW_CATEGORIES = 4
# Aggregation functions offered for Bar charts with a numeric Y-axis, keyed by
# the label shown in the UI.
MANUAL_CHART_AGG_FUNCS = {"Mean": "mean", "Sum": "sum", "Median": "median", "Min": "min", "Max": "max"}


def get_overview_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Return df.describe() across all dtypes, transposed for easier table display.

    When the dataframe mixes real numeric and real datetime64 columns (e.g.
    after Hell Mode's date resolver or a datetime dtype conversion), describe()
    puts a float mean next to a Timestamp mean in the same "mean" column,
    which pandas stores as `object` dtype with mixed Python types — that
    combination fails Arrow serialization when Streamlit renders it. Any
    column containing a Timestamp gets every non-null cell stringified (not
    just the Timestamps) so the whole column is homogeneously str, not a
    float/Timestamp mix — style_describe_table()'s to_numeric(errors="coerce")
    still recovers the numeric cells from their string form for coloring.
    """
    stats_df = df.describe(include="all").transpose()

    def _stringify_if_mixed(col: pd.Series) -> pd.Series:
        if col.dtype == object and col.map(lambda v: isinstance(v, pd.Timestamp)).any():
            return col.map(lambda v: v if pd.isna(v) else str(v))
        return col

    return stats_df.apply(_stringify_if_mixed)


def _cyan_gradient_color(norm_value: float) -> str:
    """Blend from the Graphite theme's card surface (#12151B) to its accent (#22D3EE)."""
    start, end = (18, 21, 27), (34, 211, 238)
    norm_value = max(0.0, min(1.0, norm_value))
    r, g, b = (int(s + (e - s) * norm_value) for s, e in zip(start, end))
    return f"rgb({r}, {g}, {b})"


def style_describe_table(stats_df: pd.DataFrame):
    """Apply a cyan gradient to the numeric cells of a describe() table.

    `df.describe(include="all").transpose()` mixes numeric stats (mean, std, ...)
    with categorical ones (top, freq, ...) in the same table, which pandas
    stores as `object` dtype per column — so a plain `select_dtypes` misses
    everything. Instead we coerce each column with `pd.to_numeric(errors=
    "coerce")` and color whatever comes out numeric, cell by cell.

    Built without matplotlib (which pandas' built-in .background_gradient()
    requires) — just a manual per-column min/max blend — to keep the app's
    dependency footprint small. Returns a pandas Styler, which st.dataframe()
    renders natively.
    """

    def _gradient(col: pd.Series):
        numeric_vals = pd.to_numeric(col, errors="coerce")
        if numeric_vals.notna().sum() == 0:
            return [""] * len(col)
        col_min, col_max = numeric_vals.min(), numeric_vals.max()
        span = col_max - col_min
        styles = []
        for v in numeric_vals:
            if pd.isna(v):
                styles.append("")
                continue
            norm = (v - col_min) / span if span else 0.5
            text_color = "#04141A" if norm > 0.6 else "#F1F5F9"
            styles.append(f"background-color: {_cyan_gradient_color(norm)}; color: {text_color}")
        return styles

    return stats_df.style.apply(_gradient, axis=0).format(precision=2)


def plot_categorical(df: pd.DataFrame, column: str):
    """Pie chart for low-cardinality categoricals, bar chart (top N) otherwise."""
    counts = df[column].value_counts(dropna=True)
    if counts.empty:
        return None

    if counts.shape[0] <= PIE_CHART_MAX_CATEGORIES:
        fig = px.pie(values=counts.values, names=counts.index.astype(str), title=f"Distribution of {column}")
    else:
        top = counts.head(TOP_N_CATEGORIES)
        fig = px.bar(
            x=top.index.astype(str),
            y=top.values,
            title=f"Top {TOP_N_CATEGORIES} categories in {column}",
            labels={"x": column, "y": "Count"},
        )
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig


def plot_numeric(df: pd.DataFrame, column: str) -> tuple[go.Figure, go.Figure]:
    """Histogram + boxplot pair for a numeric column."""
    hist = px.histogram(df, x=column, nbins=30, title=f"Distribution of {column}")
    box = px.box(df, y=column, title=f"Spread & outliers in {column}", points="outliers")
    for fig in (hist, box):
        fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return hist, box


def plot_datetime_trend(df: pd.DataFrame, datetime_col: str, numeric_col: str) -> go.Figure:
    """Line chart of a numeric column over time."""
    series = df.dropna(subset=[datetime_col, numeric_col]).sort_values(datetime_col)
    fig = px.line(series, x=datetime_col, y=numeric_col, title=f"{numeric_col} over {datetime_col}")
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig


def plot_scatter(
    df: pd.DataFrame,
    col_x: str,
    col_y: str,
    color: Optional[str] = None,
    facet: Optional[str] = None,
    facet_row: Optional[str] = None,
) -> go.Figure:
    """Scatter plot between two numeric columns with an OLS trendline.
    An optional `color` column splits the trendline per group instead of
    fitting one line across the whole dataset. An optional `facet` column
    splits the chart into a grid of small-multiple subplots instead, and an
    optional `facet_row` adds a second, row-wise split for a true row x
    column grid (facet_col_wrap is ignored by Plotly whenever facet_row is
    set — passing it unconditionally is harmless)."""
    try:
        fig = px.scatter(
            df, x=col_x, y=col_y, color=color, facet_col=facet, facet_row=facet_row,
            facet_col_wrap=FACET_COL_WRAP, trendline="ols", title=f"{col_y} vs {col_x}",
        )
    except Exception:
        # statsmodels missing or the trendline fit failed — fall back to a plain scatter
        fig = px.scatter(
            df, x=col_x, y=col_y, color=color, facet_col=facet, facet_row=facet_row,
            facet_col_wrap=FACET_COL_WRAP, title=f"{col_y} vs {col_x}",
        )
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig


def get_top_correlations(corr: pd.DataFrame, n: int = 3) -> list[tuple[str, str, float]]:
    """Return the n strongest |correlation| pairs, excluding self-pairs and duplicates."""
    pairs = []
    cols = corr.columns
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            value = corr.iloc[i, j]
            if pd.notna(value):
                pairs.append((cols[i], cols[j], float(value)))
    pairs.sort(key=lambda p: abs(p[2]), reverse=True)
    return pairs[:n]


def describe_correlation(value: float) -> str:
    """Turn a raw correlation coefficient into a plain-English label, e.g. 'strong positive: 0.87'."""
    magnitude = abs(value)
    if magnitude >= 0.9:
        strength = "very strong"
    elif magnitude >= 0.7:
        strength = "strong"
    elif magnitude >= 0.4:
        strength = "moderate"
    else:
        strength = "weak"
    direction = "positive" if value >= 0 else "negative"
    return f"{strength} {direction}: {value:.2f}"


def plot_correlation_heatmap(df: pd.DataFrame):
    """Correlation heatmap over numeric columns, plus the top strongest pairs.

    Returns (figure_or_None, top_correlations_list).
    """
    numeric_df = df.select_dtypes(include=np.number)
    if numeric_df.shape[1] < 2:
        return None, []

    corr = numeric_df.corr()
    fig = px.imshow(
        corr,
        text_auto=".2f",
        color_continuous_scale="RdBu_r",
        zmin=-1,
        zmax=1,
        title="Correlation Heatmap",
    )
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig, get_top_correlations(corr)


def plot_cate_by_subgroup(cate_result: dict) -> Optional[go.Figure]:
    """Bar chart of per-subgroup ATT (with 95% CI error bars) against the
    pooled ATT, for causal_inference.estimate_cate_by_subgroup() results.
    Bars are colored red/green by sign so a sign reversal across subgroups
    (the headline finding that panel calls out) is visible at a glance, not
    just stated in text. Returns None if there's nothing usable to plot.
    """
    usable = [s for s in cate_result["subgroups"] if s["ok"]]
    if not usable:
        return None

    pooled = cate_result["pooled"]
    subgroup_labels = [str(s["level"]) for s in usable]
    atts = [s["att"] for s in usable]
    ci_high_err = [s["ci_high"] - s["att"] for s in usable]
    ci_low_err = [s["att"] - s["ci_low"] for s in usable]

    fig = go.Figure()
    fig.add_hline(y=pooled["att"], line_dash="dash", line_color="gray", annotation_text="pooled ATT")
    fig.add_trace(go.Bar(
        x=subgroup_labels,
        y=atts,
        error_y=dict(type="data", array=ci_high_err, arrayminus=ci_low_err),
        marker_color=["#ef4444" if a < 0 else "#22c55e" for a in atts],
        name="Subgroup ATT",
    ))
    fig.update_layout(
        title=f"Effect of {pooled['treatment_col']} on {pooled['outcome_col']}, by {cate_result['subgroup_col']}",
        yaxis_title=f"ATT on {pooled['outcome_col']}",
        xaxis_title=cate_result["subgroup_col"],
        height=340,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
    )
    return fig


def auto_generate_charts(df: pd.DataFrame, column_types: dict[str, str]):
    """Build the full auto-chart set (used by both the Visualize tab and the HTML export).

    Returns (charts_dict, top_correlations_list) where charts_dict maps a
    human-readable title to a Plotly figure.
    """
    charts: dict[str, go.Figure] = {}

    categorical_cols = [c for c, t in column_types.items() if t == "categorical"]
    numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
    datetime_cols = [c for c, t in column_types.items() if t == "datetime"]

    for col in categorical_cols:
        fig = plot_categorical(df, col)
        if fig is not None:
            charts[f"{col} (categorical)"] = fig

    for col in numeric_cols:
        hist, box = plot_numeric(df, col)
        charts[f"{col} — histogram"] = hist
        charts[f"{col} — boxplot"] = box

    # Cap datetime x numeric trends so a wide dataset doesn't generate dozens of charts.
    if datetime_cols and numeric_cols:
        dt_col = datetime_cols[0]
        for num_col in numeric_cols[:3]:
            charts[f"{num_col} over {dt_col}"] = plot_datetime_trend(df, dt_col, num_col)

    heatmap, top_corr = plot_correlation_heatmap(df)
    if heatmap is not None:
        charts["Correlation Heatmap"] = heatmap
        # Scatter the most strongly correlated pairs — more informative than
        # an arbitrary combination of numeric columns.
        for col_x, col_y, _ in top_corr:
            charts[f"Scatter: {col_x} vs {col_y}"] = plot_scatter(df, col_x, col_y)

    return charts, top_corr


# --- Explore Mode: PyGWalker-style auto-suggested encodings -----------------
# The oldest standing backlog item (first logged Run 13, unbuilt through Run
# 19): instead of only letting the user hand-pick X/Y/color in the Manual
# Chart Builder, rank candidate charts by how much signal they're likely to
# reveal and surface the top ones automatically — the "explore mode" a
# PyGWalker/Tableau-style tool offers on load. Entirely deterministic
# (correlation, ANOVA-style effect size, skew) — zero extra Gemini calls, so
# it works even when the API is rate-limited or unavailable.
EXPLORE_CARDINALITY_MIN = 2
EXPLORE_CARDINALITY_MAX = 15
EXPLORE_MAX_SUGGESTIONS = 6
# A categorical/numeric split only "explains" real signal if there's a
# meaningful group difference; near-zero effect sizes would just clutter the
# ranking with flat bars, so they're filtered out below this floor.
EXPLORE_MIN_EFFECT_SIZE = 0.01
# Below this |skew|, a histogram looks like an ordinary bell curve — not
# worth flagging as "a look at this distribution is likely to be useful".
EXPLORE_MIN_SKEW = 1.0


def _eta_squared(df: pd.DataFrame, cat_col: str, num_col: str) -> float:
    """ANOVA-style effect size: the fraction of `num_col`'s total variance
    explained by splitting on `cat_col`'s groups (0 = no group difference,
    1 = groups fully separate the values). Returns 0.0 when there isn't
    enough data or variance to compute a meaningful ratio."""
    valid = df[[cat_col, num_col]].dropna()
    if valid.empty:
        return 0.0
    groups = valid.groupby(cat_col)[num_col]
    counts = groups.size()
    if counts.shape[0] < 2:
        return 0.0
    overall_mean = valid[num_col].mean()
    ss_total = ((valid[num_col] - overall_mean) ** 2).sum()
    if ss_total <= 0:
        return 0.0
    ss_between = float(((groups.mean() - overall_mean) ** 2 * counts).sum())
    return max(0.0, min(1.0, ss_between / ss_total))


def suggest_encodings(
    df: pd.DataFrame,
    column_types: dict[str, str],
    max_suggestions: int = EXPLORE_MAX_SUGGESTIONS,
) -> list[dict]:
    """Rank candidate chart encodings by how much signal they're likely to
    reveal, for the Visualize tab's "Explore Mode" — a PyGWalker-style
    "here's what's worth looking at" panel shown before the user touches the
    Manual Chart Builder.

    Four deterministic signal sources, each producing candidates shaped for
    `build_manual_chart` plus a plain-English `reason` and a 0-1 `score`:
      - numeric x numeric pairs, scored by |correlation| -> Scatter
      - categorical x numeric, scored by ANOVA eta-squared effect size -> Bar
        (only for categoricals with EXPLORE_CARDINALITY_MIN..MAX distinct
        values — a constant column has nothing to split on, and a
        near-unique ID column would just be noise)
      - the first datetime column x numeric, scored by |correlation with
        time ordinal| -> Line
      - single numeric columns with |skew| >= EXPLORE_MIN_SKEW -> Histogram

    Returns the top `max_suggestions` by score, descending, deduplicated by
    (chart_type, col_x, col_y). Returns [] when nothing clears the signal
    thresholds (e.g. a tiny or entirely flat dataset) — callers should show
    an empty state rather than an error.
    """
    categorical_cols = [c for c, t in column_types.items() if t == "categorical"]
    numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
    datetime_cols = [c for c, t in column_types.items() if t == "datetime"]

    candidates: list[dict] = []

    if len(numeric_cols) >= 2:
        corr = df[numeric_cols].corr()
        for col_x, col_y, value in get_top_correlations(corr, n=len(numeric_cols)):
            candidates.append(
                {
                    "chart_type": "Scatter",
                    "col_x": col_x,
                    "col_y": col_y,
                    "color": None,
                    "reason": f"{describe_correlation(value)} correlation between {col_x} and {col_y}",
                    "score": round(abs(value), 3),
                }
            )

    for cat_col in categorical_cols:
        nunique = df[cat_col].nunique(dropna=True)
        if not (EXPLORE_CARDINALITY_MIN <= nunique <= EXPLORE_CARDINALITY_MAX):
            continue
        for num_col in numeric_cols:
            eta_sq = _eta_squared(df, cat_col, num_col)
            if eta_sq < EXPLORE_MIN_EFFECT_SIZE:
                continue
            candidates.append(
                {
                    "chart_type": "Bar",
                    "col_x": cat_col,
                    "col_y": num_col,
                    "color": None,
                    "reason": f"{num_col} varies strongly across {cat_col} groups (η²={eta_sq:.2f})",
                    "score": round(eta_sq, 3),
                }
            )

    if datetime_cols and numeric_cols:
        dt_col = datetime_cols[0]
        ordinal = pd.to_datetime(df[dt_col], errors="coerce").map(
            lambda ts: ts.toordinal() if pd.notna(ts) else np.nan
        )
        for num_col in numeric_cols:
            valid = pd.DataFrame({"t": ordinal, "y": df[num_col]}).dropna()
            if valid.shape[0] < 3 or valid["y"].std() == 0 or valid["t"].std() == 0:
                continue
            trend_corr = valid["t"].corr(valid["y"])
            if pd.isna(trend_corr):
                continue
            candidates.append(
                {
                    "chart_type": "Line",
                    "col_x": dt_col,
                    "col_y": num_col,
                    "color": None,
                    "reason": f"{describe_correlation(trend_corr)} trend over time in {num_col}",
                    "score": round(abs(trend_corr), 3),
                }
            )

    for num_col in numeric_cols:
        series = df[num_col].dropna()
        if series.shape[0] < 5 or series.std() == 0:
            continue
        skew = float(series.skew())
        if pd.isna(skew) or abs(skew) < EXPLORE_MIN_SKEW:
            continue
        candidates.append(
            {
                "chart_type": "Histogram",
                "col_x": num_col,
                "col_y": None,
                "color": None,
                "reason": f"{num_col} is {'right' if skew > 0 else 'left'}-skewed (skew={skew:.2f}) — worth a look",
                "score": round(min(abs(skew) / 5, 1.0), 3),
            }
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    seen: set[tuple] = set()
    ranked: list[dict] = []
    for c in candidates:
        key = (c["chart_type"], c["col_x"], c["col_y"])
        if key in seen:
            continue
        seen.add(key)
        ranked.append(c)
    return ranked[:max_suggestions]


# The "(none)" sentinel string the Manual Chart Builder's optional selectboxes
# (Y-axis, Color, Facet columns/rows) use in app.py — a suggestion's None
# needs to become this exact string, or Streamlit's selectbox raises
# "value not in options" when the widget is instantiated with it preloaded.
MANUAL_BUILDER_NONE_SENTINEL = "(none)"


def suggestion_to_builder_state(suggestion: dict) -> dict:
    """Translate one `suggest_encodings()` suggestion into the exact Manual
    Chart Builder widget `st.session_state` keys/values needed to preload it
    — the "Load into Manual Builder" click-through that makes Explore Mode
    actionable instead of just informational (open backlog item since Run
    20, built Run 23).

    Facet and aggregation channels are always reset to their defaults
    (`"(none)"` / `"Mean"`) rather than carried over from whatever the user
    had picked before: the Manual Builder's facet options dynamically
    exclude the current X/Y/color (see app.py), so a stale facet value can
    collide with the newly-loaded encoding and Streamlit would raise a
    "value not in options" error on the next rerun instead of silently
    dropping it.

    Pure and Streamlit-free by design (matches every other function in this
    module) so it's directly unit-testable — app.py is responsible for
    actually writing the returned dict into `st.session_state` before the
    Manual Chart Builder's widgets are instantiated in the same rerun.
    """
    return {
        "manual_x": suggestion["col_x"],
        "manual_y": suggestion["col_y"] if suggestion["col_y"] is not None else MANUAL_BUILDER_NONE_SENTINEL,
        "manual_chart_type": suggestion["chart_type"],
        "manual_color": suggestion.get("color") or MANUAL_BUILDER_NONE_SENTINEL,
        "manual_facet": MANUAL_BUILDER_NONE_SENTINEL,
        "manual_facet_row": MANUAL_BUILDER_NONE_SENTINEL,
        "manual_agg": "Mean",
    }


def _cap_facet_categories(df: pd.DataFrame, facet: Optional[str], max_categories: int = MAX_FACET_CATEGORIES) -> pd.DataFrame:
    """Keep only rows whose `facet` value is among its `max_categories` most
    frequent. Facets are full subplots (not just a color split), so an
    uncapped high-cardinality column would render an unreadable, slow-to-
    build grid — same top-N-by-frequency capping convention Bar/Pie already
    use for their X-axis categories. Returns df unchanged when facet is None.

    Used for both facet dimensions — the column facet (MAX_FACET_CATEGORIES)
    and, since this run, the row facet (MAX_FACET_ROW_CATEGORIES), applied
    independently one after the other so each dimension's own frequency
    ranking is respected rather than one column's cap starving the other's.
    """
    if not facet:
        return df
    top_categories = df[facet].value_counts(dropna=True).head(max_categories).index
    return df[df[facet].isin(top_categories)]


def build_manual_chart(
    df: pd.DataFrame,
    chart_type: str,
    col_x: str,
    col_y: Optional[str] = None,
    color: Optional[str] = None,
    agg: str = "mean",
    facet: Optional[str] = None,
    facet_row: Optional[str] = None,
) -> go.Figure:
    """Build a chart from explicit user picks — the manual escape hatch next to
    the automatic per-dtype chart picker above. A lightweight grammar-of-
    graphics builder: X and Y are the required axes, `color` is an optional
    third encoding channel that splits/groups the marks (a PyGWalker/Tableau-
    style "pill" without the drag-and-drop), `agg` picks how a Bar chart's
    numeric Y is summarized per X category, `facet` is a fourth channel that
    splits the chart into a grid of column small multiples (one subplot per
    category), and `facet_row` is a fifth channel that adds a second,
    row-wise split — a true row x column small-multiples grid instead of a
    single wrapped strip (the dual-axis faceting slice of the PyGWalker-style
    builder).

    chart_type: one of MANUAL_CHART_TYPES ("Histogram", "Box", "Bar", "Pie", "Scatter", "Line").
    col_y is required for "Scatter"/"Line" and optional (used as a grouping) for "Box"/"Bar".
    color is only meaningful for MANUAL_CHART_TYPES_SUPPORTING_COLOR; silently ignored
    elsewhere (Pie) and silently dropped if it duplicates col_x/col_y (no self-encoding).
    agg is one of MANUAL_CHART_AGG_FUNCS's values, only used by "Bar" with a numeric col_y.
    facet and facet_row are only meaningful for MANUAL_CHART_TYPES_SUPPORTING_FACET;
    silently ignored elsewhere (Pie) and silently dropped if either duplicates
    col_x/col_y/color, or if facet_row duplicates facet (no self-encoding).
    facet is capped to its MAX_FACET_CATEGORIES most frequent values; facet_row to
    its (smaller) MAX_FACET_ROW_CATEGORIES, since the two dimensions multiply.
    Raises ValueError for an invalid combination, so callers can surface it as a friendly message.
    """
    if chart_type in MANUAL_CHART_TYPES_REQUIRING_Y and not col_y:
        raise ValueError(f"{chart_type} needs a Y-axis column.")
    if color is not None and color not in df.columns:
        raise ValueError(f"Unknown color column: {color}")
    if facet is not None and facet not in df.columns:
        raise ValueError(f"Unknown facet column: {facet}")
    if facet_row is not None and facet_row not in df.columns:
        raise ValueError(f"Unknown facet row column: {facet_row}")
    if color in (col_x, col_y):
        color = None  # would just re-encode an axis — ignore rather than error
    if facet in (col_x, col_y, color):
        facet = None  # same self-encoding rule as color
    if facet_row in (col_x, col_y, color, facet):
        facet_row = None  # same self-encoding rule, including against the column facet
    agg_label = next((label for label, fn in MANUAL_CHART_AGG_FUNCS.items() if fn == agg), agg.title())

    df = _cap_facet_categories(df, facet, MAX_FACET_CATEGORIES)
    df = _cap_facet_categories(df, facet_row, MAX_FACET_ROW_CATEGORIES)

    if chart_type == "Histogram":
        fig = px.histogram(
            df, x=col_x, color=color, facet_col=facet, facet_row=facet_row, facet_col_wrap=FACET_COL_WRAP,
            nbins=30, title=f"Histogram of {col_x}",
        )
    elif chart_type == "Box":
        if col_y:
            fig = px.box(
                df, x=col_x, y=col_y, color=color, facet_col=facet, facet_row=facet_row,
                facet_col_wrap=FACET_COL_WRAP, title=f"{col_y} by {col_x}",
            )
        else:
            fig = px.box(
                df, y=col_x, color=color, facet_col=facet, facet_row=facet_row,
                facet_col_wrap=FACET_COL_WRAP, title=f"Spread of {col_x}", points="outliers",
            )
    elif chart_type == "Pie":
        counts = df[col_x].value_counts(dropna=True).head(TOP_N_CATEGORIES)
        fig = px.pie(values=counts.values, names=counts.index.astype(str), title=f"Distribution of {col_x}")
    elif chart_type == "Bar":
        if col_y and pd.api.types.is_numeric_dtype(df[col_y]):
            group_cols = (
                [col_x] + ([color] if color else []) + ([facet] if facet else []) + ([facet_row] if facet_row else [])
            )
            grouped = df.groupby(group_cols)[col_y].agg(agg).reset_index()
            top_x = (
                df.groupby(col_x)[col_y].agg(agg).sort_values(ascending=False).head(TOP_N_CATEGORIES).index
            )
            grouped = grouped[grouped[col_x].isin(top_x)]
            fig = px.bar(
                grouped, x=col_x, y=col_y, color=color, facet_col=facet, facet_row=facet_row,
                facet_col_wrap=FACET_COL_WRAP, barmode="group",
                title=f"{agg_label} {col_y} by {col_x}" + (f", split by {color}" if color else ""),
                labels={col_y: f"{agg_label} {col_y}"},
            )
        else:
            counts = df[col_x].value_counts(dropna=True).head(TOP_N_CATEGORIES)
            fig = px.bar(
                x=counts.index.astype(str), y=counts.values,
                title=f"Top {TOP_N_CATEGORIES} values in {col_x}", labels={"x": col_x, "y": "Count"},
            )
    elif chart_type == "Scatter":
        fig = plot_scatter(df, col_x, col_y, color=color, facet=facet, facet_row=facet_row)
    elif chart_type == "Line":
        cols = [c for c in [col_x, col_y, color, facet, facet_row] if c]
        subset = df[cols].dropna().sort_values(col_x)
        fig = px.line(
            subset, x=col_x, y=col_y, color=color, facet_col=facet, facet_row=facet_row,
            facet_col_wrap=FACET_COL_WRAP, title=f"{col_y} over {col_x}",
        )
    else:
        raise ValueError(f"Unknown chart type: {chart_type}")

    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig
