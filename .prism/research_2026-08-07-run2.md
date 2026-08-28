# Prism Research — 2026-08-07

## Source Classes Surveyed

1. **Industry Practice**: Data analyst/scientist job descriptions (India 2026), Kaggle trending, portfolio advice
2. **Competitor Tools**: Julius AI, Hex, Deepnote, ChatGPT ADA, Databricks Assistant, Tellius, ThoughtSpot
3. **Ecosystem Tech**: Polars 1.38+, DuckDB 1.4, pandas 3.0, SHAP (already integrated), statsmodels
4. **Agentic EDA Research**: QUIS (question-guided insights), EDATracer, InsightLab, Discovery Agents, proactive insight systems

## Ranked Candidate Table

| # | Feature | Evidence | Depth | Effort | Risk | Roadmap Theme |
|---|---------|----------|-------|--------|------|---------------|
| 1 | **Auto-Insight Engine (proactive insights on upload)** | Tellius, ThoughtSpot Spotter, Discovery Agents paper — 40% enterprise adoption of proactive insight gen; Prism's Auto Analyst requires a button click, competitors surface insights automatically | 5 | M | Low | Agentic AI |
| 2 | **Automated Hypothesis Testing Suite** | QUIS paper (question-guided insights), job descriptions emphasize hypothesis-driven analysis; Prism's Stats Lab requires manual column selection — competitors auto-suggest hypotheses | 4 | M | Low | Agentic AI / Stats Rigor |
| 3 | **Cross-Column Correlation Intelligence & Multicollinearity Detection** | Job interviews test VIF/multicollinearity knowledge; competitors (Hex, Deepnote) surface pairwise insights; Prism only shows heatmap, no narration | 4 | S | Low | Stats Rigor |
| 4 | **Data Quality Score with Exportable Scorecard** | Tellius, Hex — automated data quality scores; Prism has profiling but no unified quality score | 3 | S | Low | Portfolio Polish |
| 5 | **Polars Integration for Large Dataset Performance** | Polars 1.38 + DuckDB power combo; pandas struggles on 500K+ rows | 4 | L | Med | Ecosystem Tech |
| 6 | **Advanced Outlier Detection (LOF, DBSCAN)** | Job descriptions test outlier detection methods; Prism only has IsolationForest | 4 | M | Low | ML Depth |
| 7 | **Feature Selection Engine (mutual info, RFE, L1)** | Interview staple; Prism's ML Lab suggests but doesn't auto-select features | 4 | M | Low | ML Lab |
| 8 | **Time Series Decomposition (STL)** | Forecasting interviews test seasonal decomposition; Prism forecasts but doesn't decompose | 3 | S | Low | Stats Rigor |
| 9 | **Atlas Proactive Insights (JARVIS copilot track)** | Julius AI & ChatGPT ADA auto-surface insights without being asked; Atlas currently only responds to commands | 4 | M | Med | Atlas Copilot |
| 10 | **Regression Diagnostics Panel** | Interview standard — residual plots, QQ plots, VIF, heteroscedasticity tests; no competitor at Prism's level offers this | 5 | M | Low | ML Lab / Stats |
| 11 | **Natural Language Summary of Every Tab** | Tellius, ThoughtSpot — plain-English summaries of analysis results | 3 | M | Low | Agentic AI |
| 12 | **PDF Report with Embedded Charts** | Already partial in report_writer.py — needs chart embedding | 2 | S | Low | Portfolio Polish |

## Selection Rationale

### Selected Features (3):

**1. Auto-Insight Engine (Proactive Insights on Upload)** — Depth 5, Effort M
- **Why**: This is THE differentiator for 2026 data tools. Tellius, ThoughtSpot, and Julius AI all surface insights automatically. Prism requires manual exploration. An auto-insight engine that runs on upload and surfaces 5-8 statistical findings (distribution anomalies, strong correlations, potential segments, data quality red flags) without user action demonstrates agentic AI capability.
- **Technical depth**: Statistical computation (skewness/kurtosis thresholds, Pearson/Spearman correlation scanning, IQR outlier detection, cardinality analysis, missing-value pattern detection), priority ranking algorithm, Gemini narration.
- **Roadmap theme**: Agentic AI ✓

**2. Regression Diagnostics Panel** — Depth 5, Effort M
- **Why**: This is a standard interview topic that no competitor at Prism's level offers. Residual vs fitted plots, QQ plots for normality, VIF for multicollinearity, Breusch-Pagan for heteroscedasticity, Durbin-Watson for autocorrelation — these are the exact things hiring panels ask about.
- **Technical depth**: scipy.stats, statsmodels OLS, VIF calculation, diagnostic plot generation with plotly.
- **Roadmap theme**: ML Lab / Statistical Rigor ✓

**3. Time Series Decomposition (STL)** — Depth 3, Effort S
- **Why**: Natural complement to the existing Forecasting tab. STL decomposition (trend + seasonal + residual) is an interview staple and helps users understand their time series before forecasting. Quick win that adds real analytical depth.
- **Technical depth**: statsmodels STL, interactive plotly decomposition plots.
- **Roadmap theme**: Stats Rigor ✓
