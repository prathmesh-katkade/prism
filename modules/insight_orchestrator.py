"""
Agentic Insight Orchestrator — synthesizes findings across Prism's
independent detector modules (auto_insights, confounder_detection,
causal_inference's ATT + CATE, anomaly, drift, hypothesis_sweep's FDR-
corrected automated hypothesis tests, and Auto Analyst's own
insight_verifier safety net) into one ranked "what matters most" list.

Why this exists: Prism has grown a whole bench of self-contained analysis
agents that each run and render independently — Auto-Insights flags a
strong correlation, Confounder Check stress-tests it, the Causal Effect
Estimator tries to quantify it, Anomaly Detection flags unusual rows,
Drift compares two snapshots — but nothing ties their outputs together.
A user staring at five separate panels has no signal for which of a dozen
findings is the one that actually matters, and no way to notice when two
detectors are quietly agreeing (higher confidence) or, worse, when one
detector's methodology contradicts another's assumptions (e.g. a causal
ATT estimate that never adjusted for a variable Confounder Check just
flagged as reversing that exact relationship).

This module is a pure synthesis layer — it does not re-run any detection.
It takes the already-computed structured findings each detector module
produces for its own panel, normalizes them into a common `Claim` shape,
groups claims that share the same subject columns (the "de-duplication" —
two detectors independently flagging the same variable pair collapse into
one topic instead of two disconnected panel entries), flags cross-detector
agreement and the one specific contradiction pattern described above as a
"check this" flag (never a hard error — confounding is a reason to look
closer, not proof the causal estimate is wrong), and severity-ranks the
result into a top-N list.

Deliberately silent by design, same convention as every other detector in
this codebase: with fewer than two detectors contributing any findings at
all, there is nothing to cross-check, so `orchestrate_insights()` returns
a result with `silent=True` and an empty `top` list, and the caller should
render nothing rather than a one-detector list dressed up as a synthesis.

An optional Gemini narration pass (`narrate_orchestration`) turns the
ranked list into one stakeholder paragraph, following the exact same
call_gemini() / cached-by-caller / graceful-fallback convention as every
other narrate_* helper in the app (see modules/auto_insights.py,
modules/confounder_detection.py).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ── Tunables ─────────────────────────────────────────────────────────────

MAX_TOP = 5                 # cap the "what matters most" list
MIN_DETECTORS_FOR_OUTPUT = 2  # fewer distinct detectors firing -> nothing to orchestrate, stay silent

_SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}
_AGREEMENT_BONUS_PER_EXTRA_DETECTOR = 1.5
_CONTRADICTION_BONUS = 2.5  # keeps a "check this" flag above a lone same-severity claim (a mismatch
                            # between two independent checks is more actionable than one detector's
                            # unconfirmed opinion), while still ranking below genuine multi-detector
                            # agreement on the strongest findings

_DRIFT_NOTABLE_SCORE = 50.0  # drift_score (0-100) at/above this is worth surfacing
_ANOMALY_HIGH_PCT = 10.0
_ANOMALY_MEDIUM_PCT = 3.0

_ANOMALY_REASON_COL_RE = re.compile(r"([A-Za-z0-9_ ]+?) is \d")


# ── Data shapes ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Claim:
    """One normalized finding from a single detector, ready to be grouped
    and cross-checked against claims from other detectors."""

    detector: str            # "auto_insights" | "confounder" | "causal_att" | "causal_cate" | "anomaly" | "drift" | "hypothesis_sweep" | "verifier"
    subjects: frozenset       # column name(s) this claim is about; empty = dataset-wide
    severity: str             # "high" | "medium" | "low"
    kind: str                 # fine-grained tag, e.g. "confounder:paradox"
    message: str
    meta: dict = field(default_factory=dict)


@dataclass
class ClaimGroup:
    """All claims that share the same subject columns, treated as one topic."""

    subjects: frozenset
    claims: list  # list[Claim], sorted worst-first
    severity: str
    score: float
    detectors: list  # sorted distinct detector names contributing to this group
    agreement: bool
    contradiction: Optional[str]
    headline: str


@dataclass
class OrchestrationResult:
    groups: list         # list[ClaimGroup], all groups, ranked worst/most-important-first
    top: list             # list[ClaimGroup], top MAX_TOP
    contradictions: list  # subset of `groups` where contradiction is set
    n_detectors_fired: int
    n_total_claims: int
    silent: bool           # True -> caller should render nothing


# ── Adapters: raw detector output -> list[Claim] ────────────────────────


def _subjects_from_column_label(label: Optional[str]) -> frozenset:
    """auto_insights encodes pairs as 'colA ↔ colB' and dataset-wide
    findings (duplicate rows) as '(all columns)'."""
    if not label or label == "(all columns)":
        return frozenset()
    if " ↔ " in label:
        a, b = label.split(" ↔ ", 1)
        return frozenset({a.strip(), b.strip()})
    return frozenset({label.strip()})


def _adapt_auto_insights(raw: Any) -> list:
    claims = []
    for ins in raw or []:
        try:
            claims.append(
                Claim(
                    detector="auto_insights",
                    subjects=_subjects_from_column_label(ins.get("column")),
                    severity=ins.get("severity", "low"),
                    kind=f"auto_insights:{ins.get('category', 'other')}",
                    message=ins["message"],
                )
            )
        except (KeyError, AttributeError):
            continue
    return claims


_CONFOUNDER_SEVERITY = {"paradox": "high", "attenuated": "medium"}
_CONFOUNDER_ACTION = {"paradox": "reverses sign", "attenuated": "weakens substantially"}


def _adapt_confounder(raw: Any) -> list:
    """raw = confounder_detection.auto_scan_for_confounding() result:
    [{x, y, overall_r, findings: [{confounder, type, verdict, ...}]}]."""
    claims = []
    for scan in raw or []:
        x, y = scan.get("x"), scan.get("y")
        if not x or not y:
            continue
        subjects = frozenset({x, y})
        for finding in scan.get("findings", []):
            verdict = finding.get("verdict")
            severity = _CONFOUNDER_SEVERITY.get(verdict)
            if severity is None:
                continue
            confounder = finding.get("confounder")
            action = _CONFOUNDER_ACTION[verdict]
            claims.append(
                Claim(
                    detector="confounder",
                    subjects=subjects,
                    severity=severity,
                    kind=f"confounder:{verdict}",
                    message=(
                        f"The relationship between '{x}' and '{y}' {action} once you "
                        f"control for '{confounder}'."
                    ),
                    meta={"confounder": confounder},
                )
            )
    return claims


def _adapt_causal_att(raw: Any) -> list:
    """raw = causal_inference.estimate_causal_effect() result (single dict, or None)."""
    if not raw or not raw.get("ok"):
        return []
    treatment, outcome = raw.get("treatment_col"), raw.get("outcome_col")
    if not treatment or not outcome:
        return []
    ci_low, ci_high = raw.get("ci_low"), raw.get("ci_high")
    significant = ci_low is not None and ci_high is not None and (ci_low > 0) == (ci_high > 0)
    severity = "high" if significant else "low"
    att = raw.get("att", 0.0)
    covariates = set(raw.get("covariates") or [])
    n_cov = len(covariates)
    return [
        Claim(
            detector="causal_att",
            subjects=frozenset({treatment, outcome}),
            severity=severity,
            kind="causal_att",
            message=(
                f"Estimated causal effect of '{treatment}' on '{outcome}': ATT = {att:.3g} "
                f"(matched, adjusting for {n_cov} covariate{'s' if n_cov != 1 else ''})."
            ),
            meta={"covariates": covariates, "treatment": treatment, "outcome": outcome},
        )
    ]


def _adapt_causal_cate(raw: Any) -> list:
    """raw = causal_inference.estimate_cate_by_subgroup() result (single dict, or None)."""
    if not raw or not raw.get("ok"):
        return []
    pooled = raw.get("pooled") or {}
    treatment, outcome = pooled.get("treatment_col"), pooled.get("outcome_col")
    subgroup_col = raw.get("subgroup_col")
    if not treatment or not outcome:
        return []
    subjects = frozenset({treatment, outcome})
    if raw.get("sign_reversal"):
        message = (
            f"The effect of '{treatment}' on '{outcome}' reverses sign across "
            f"'{subgroup_col}' segments — a single pooled estimate would hide this."
        )
        return [Claim(detector="causal_cate", subjects=subjects, severity="high",
                       kind="causal_cate:sign_reversal", message=message,
                       meta={"subgroup_col": subgroup_col})]
    if raw.get("heterogeneity_detected"):
        message = (
            f"The effect of '{treatment}' on '{outcome}' varies meaningfully across "
            f"'{subgroup_col}' segments."
        )
        return [Claim(detector="causal_cate", subjects=subjects, severity="medium",
                       kind="causal_cate:heterogeneity", message=message,
                       meta={"subgroup_col": subgroup_col})]
    return []


def _top_anomaly_column(reasons: list) -> Optional[str]:
    """Best-effort extraction of the numeric column most often cited in a
    set of anomaly_reason strings (see modules/anomaly.py's _reason_for_row /
    find_anomalies_ensemble), used only to give the anomaly claim a subject
    to potentially cross-reference against other detectors' claims. None if
    no reason string had an extractable column (e.g. the generic fallback
    "Unusual combination of values...")."""
    counts: dict = {}
    for reason in reasons or []:
        match = _ANOMALY_REASON_COL_RE.search(reason or "")
        if match:
            col = match.group(1).strip()
            counts[col] = counts.get(col, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _adapt_anomaly(raw: Any) -> list:
    """raw = {"count": int, "total_rows": int, "reasons": [str, ...]} — a
    small summary the caller builds from find_anomalies()/find_anomalies_
    ensemble()'s flagged DataFrame; this module never touches pandas."""
    if not raw:
        return []
    count = raw.get("count", 0)
    if not count:
        return []
    total = raw.get("total_rows") or 0
    pct = (count / total * 100) if total else 0.0
    top_col = _top_anomaly_column(raw.get("reasons", []))
    subjects = frozenset({top_col}) if top_col else frozenset()
    severity = "high" if pct >= _ANOMALY_HIGH_PCT else "medium" if pct >= _ANOMALY_MEDIUM_PCT else "low"
    message = f"{count:,} row(s) flagged as statistical anomalies ({pct:.1f}% of the dataset)"
    if top_col:
        message += f", most often driven by '{top_col}'."
    else:
        message += "."
    return [Claim(detector="anomaly", subjects=subjects, severity=severity, kind="anomaly", message=message)]


def _adapt_drift(raw: Any) -> list:
    """raw = drift.compare_datasets() result: {"column_reports": [...], ...}."""
    if not raw:
        return []
    claims = []
    for rep in raw.get("column_reports", []):
        score = rep.get("drift_score", 0) or 0
        if score < _DRIFT_NOTABLE_SCORE:
            continue
        col = rep.get("column")
        severity = "high" if score >= 75 else "medium"
        message = f"'{col}' shows notable drift between the two datasets (drift score {score:.0f}/100)."
        claims.append(
            Claim(
                detector="drift",
                subjects=frozenset({col}) if col else frozenset(),
                severity=severity,
                kind="drift",
                message=message,
            )
        )
    return claims


def _subjects_in_text(text: str, columns: list) -> frozenset:
    """Best-effort subject extraction for free-text findings: which of the
    dataset's own column names are mentioned (whole-word, case-insensitive)
    in a synthesized Auto Analyst sentence. Unlike every other adapter,
    verifier findings have no structured per-column field to read — the
    finding is a sentence Gemini wrote, so this is the only way to let a
    flagged finding join the same subject-based grouping as the other
    detectors."""
    if not text or not columns:
        return frozenset()
    lowered = text.lower()
    found = set()
    for col in columns:
        if not col:
            continue
        if re.search(r"\b" + re.escape(str(col).lower()) + r"\b", lowered):
            found.add(col)
    return frozenset(found)


def _adapt_verifier(raw: Any) -> list:
    """raw = {"findings": [str, ...], "verification": [dict, ...], "columns":
    [str, ...]} — Auto Analyst's synthesized findings, modules.insight_
    verifier.verify_findings()'s parallel per-finding result, and the
    dataset's column names (for subject extraction, see _subjects_in_text).

    Only "flagged" findings (a quoted number didn't match anything
    recomputed straight from the DataFrame) become claims — "confirmed"
    findings are already badged in the Auto Analyst tab and would just be
    noise here, and "unverifiable" (no numeric claim at all) has nothing
    to cross-check. This is Auto Analyst's own self-verification safety
    net feeding into the same cross-detector synthesis every other
    detector's findings go through, rather than a separate, disconnected
    signal the user has to notice on a different tab."""
    if not raw:
        return []
    findings = raw.get("findings") or []
    verification = raw.get("verification") or []
    columns = raw.get("columns") or []
    claims = []
    for finding, result in zip(findings, verification):
        if not isinstance(result, dict) or result.get("status") != "flagged":
            continue
        snippet = str(finding).strip()
        if len(snippet) > 140:
            snippet = snippet[:137].rstrip() + "..."
        message = (
            f"An Auto Analyst finding cites a number that doesn't match what's "
            f'recomputed from the data: "{snippet}"'
        )
        claims.append(
            Claim(
                detector="verifier",
                subjects=_subjects_in_text(str(finding), columns),
                severity="medium",
                kind="verifier:unmatched_number",
                message=message,
            )
        )
    return claims


_HYPOTHESIS_SWEEP_SEVERITY = {"large": "high", "medium": "medium", "small": "low"}


def _adapt_hypothesis_sweep(raw: Any) -> list:
    """raw = hypothesis_sweep.sweep_hypotheses() result: {"tested": [{col_a,
    col_b, test, test_label, p_adj, significant, effect_size_label, ...}],
    ...}. Only pairs with significant=True (i.e. still significant *after*
    Benjamini-Hochberg FDR correction across the whole sweep) become claims
    — the entire point of the sweep's correction step is that a raw p<0.05
    out of a batch of N tests is not reportable on its own, so anything that
    didn't survive it has nothing to contribute here either. Severity reuses
    the sweep's own small/medium/large effect-size label (the same Cohen's-
    convention thresholds Stats Lab already applies per test type), so a
    large-effect relationship outranks a merely-significant-but-tiny one the
    same way every other detector's severity already does."""
    if not raw:
        return []
    claims = []
    for row in raw.get("tested", []):
        if not row.get("significant"):
            continue
        col_a, col_b = row.get("col_a"), row.get("col_b")
        if not col_a or not col_b:
            continue
        label = row.get("effect_size_label", "small")
        severity = _HYPOTHESIS_SWEEP_SEVERITY.get(label, "low")
        p_adj = row.get("p_adj")
        p_text = f"{p_adj:.3g}" if isinstance(p_adj, (int, float)) else "n/a"
        message = (
            f"Automated hypothesis sweep found a {label}-effect, FDR-significant "
            f"relationship between '{col_a}' and '{col_b}' "
            f"({row.get('test_label') or row.get('test', 'test')}, adjusted p={p_text})."
        )
        claims.append(
            Claim(
                detector="hypothesis_sweep",
                subjects=frozenset({col_a, col_b}),
                severity=severity,
                kind="hypothesis_sweep:significant",
                message=message,
                meta={"test": row.get("test"), "p_adj": p_adj, "effect_size": row.get("effect_size")},
            )
        )
    return claims


_ADAPTERS = {
    "auto_insights": _adapt_auto_insights,
    "confounder": _adapt_confounder,
    "causal_att": _adapt_causal_att,
    "causal_cate": _adapt_causal_cate,
    "anomaly": _adapt_anomaly,
    "drift": _adapt_drift,
    "verifier": _adapt_verifier,
    "hypothesis_sweep": _adapt_hypothesis_sweep,
}


def normalize_findings(findings_by_detector: dict) -> list:
    """Adapt every detector's raw, already-computed output into a flat
    list of Claim objects. Unknown detector keys are ignored (forward
    compatible with new detectors); a malformed value from one detector
    never breaks orchestration of the others."""
    claims: list = []
    for name, raw in (findings_by_detector or {}).items():
        adapter = _ADAPTERS.get(name)
        if adapter is None:
            continue
        try:
            claims.extend(adapter(raw))
        except Exception:
            continue
    return claims


def _dedupe_exact(claims: list) -> list:
    """Collapse literally-identical claims (same detector, kind, subjects,
    message) — defensive against a detector's raw output containing an
    accidental repeat."""
    seen = set()
    deduped = []
    for c in claims:
        key = (c.detector, c.kind, c.subjects, c.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


# ── Cross-detector agreement / contradiction ────────────────────────────


def _contradiction_for_causal_claim(causal_claim: Claim, all_claims: list) -> Optional[str]:
    """The one specific "check this" pattern this module knows how to spot:
    a causal ATT estimate whose outcome column is one side of a relationship
    Confounder Check flagged (paradox/attenuated) against some third
    variable, where that flagged confounder was never included among the
    causal estimate's covariates. Deliberately checked against *every*
    confounder claim in the whole run, not just ones sharing the exact
    (treatment, outcome) pair — in practice a causal treatment column is
    categorical and a confounder pair is numeric/numeric, so they can never
    be literally identical, but "the estimate's own outcome variable has an
    unaddressed confound" is exactly the situation worth a second look.
    Surfaced as a flag, not a hard error — the causal estimate may still be
    directionally right."""
    covariates = causal_claim.meta.get("covariates") or set()
    outcome = causal_claim.meta.get("outcome")
    if not outcome:
        return None
    for fc in all_claims:
        if fc.detector != "confounder" or outcome not in fc.subjects:
            continue
        confounder_col = fc.meta.get("confounder")
        if not confounder_col or confounder_col in covariates or confounder_col in causal_claim.subjects:
            continue
        other = next(iter(fc.subjects - {outcome}), outcome)
        verb = "reverses" if fc.kind.endswith("paradox") else "weakens"
        return (
            f"Check this: the causal estimate for '{outcome}' doesn't adjust for "
            f"'{confounder_col}', which Confounder Check found {verb} the relationship "
            f"between '{outcome}' and '{other}'."
        )
    return None


def _detect_contradiction(claims: list, all_claims: list) -> Optional[str]:
    for c in claims:
        if c.detector == "causal_att":
            found = _contradiction_for_causal_claim(c, all_claims)
            if found:
                return found
    return None


def _build_headline(claims_sorted: list, detectors: list, agreement: bool, contradiction: Optional[str]) -> str:
    if contradiction:
        return contradiction
    primary = claims_sorted[0].message
    if agreement:
        others = [d for d in detectors]
        return f"{primary} (confirmed independently by {len(others)} detectors: {', '.join(others)})."
    return primary


def _build_group(subjects: frozenset, claims: list, all_claims: list) -> ClaimGroup:
    claims_sorted = sorted(claims, key=lambda c: -_SEVERITY_WEIGHT.get(c.severity, 0))
    detectors = sorted({c.detector for c in claims_sorted})
    top_severity = claims_sorted[0].severity
    contradiction = _detect_contradiction(claims_sorted, all_claims)
    agreement = len(detectors) >= 2

    score = float(_SEVERITY_WEIGHT.get(top_severity, 0))
    if agreement:
        score += (len(detectors) - 1) * _AGREEMENT_BONUS_PER_EXTRA_DETECTOR
    if contradiction:
        score += _CONTRADICTION_BONUS

    headline = _build_headline(claims_sorted, detectors, agreement, contradiction)
    return ClaimGroup(
        subjects=subjects,
        claims=claims_sorted,
        severity=top_severity,
        score=score,
        detectors=detectors,
        agreement=agreement,
        contradiction=contradiction,
        headline=headline,
    )


def group_claims(claims: list) -> list:
    """Group claims that share the same subject column(s) into one topic —
    this is the de-duplication step: two detectors independently flagging
    the same variable pair become one ClaimGroup instead of two disconnected
    entries. Claims with no subjects (dataset-wide findings, e.g. duplicate
    rows) never merge with each other since they aren't actually about the
    same thing."""
    buckets: dict = {}
    singleton_i = 0
    for c in claims:
        if c.subjects:
            key = c.subjects
        else:
            singleton_i += 1
            key = frozenset({f"__singleton_{singleton_i}__"})
        buckets.setdefault(key, []).append(c)

    groups = [_build_group(subjects, group_claims_, claims) for subjects, group_claims_ in buckets.items()]
    groups.sort(key=lambda g: (-g.score, -_SEVERITY_WEIGHT.get(g.severity, 0)))
    return groups


# ── Entry point ──────────────────────────────────────────────────────────


def orchestrate_insights(findings_by_detector: dict) -> OrchestrationResult:
    """Synthesize already-computed detector findings into a ranked
    "what matters most" list.

    `findings_by_detector` keys are detector names ("auto_insights",
    "confounder", "causal_att", "causal_cate", "anomaly", "drift") mapped
    to that detector's own raw, already-computed output — nothing in this
    function re-runs detection. Missing/None/empty values for a detector
    are fine; unknown keys are ignored.

    Stays silent (returns silent=True, top=[]) when fewer than
    MIN_DETECTORS_FOR_OUTPUT distinct detectors contributed any findings
    at all — with only one detector in play there is nothing to cross-check,
    so producing a "top list" would just be that detector's own list
    relabeled, manufacturing noise rather than synthesis.
    """
    claims = _dedupe_exact(normalize_findings(findings_by_detector))
    n_detectors_fired = len({c.detector for c in claims})
    n_total_claims = len(claims)

    if n_detectors_fired < MIN_DETECTORS_FOR_OUTPUT or n_total_claims == 0:
        return OrchestrationResult(
            groups=[], top=[], contradictions=[],
            n_detectors_fired=n_detectors_fired, n_total_claims=n_total_claims, silent=True,
        )

    groups = group_claims(claims)
    contradictions = [g for g in groups if g.contradiction]
    top = groups[:MAX_TOP]
    return OrchestrationResult(
        groups=groups, top=top, contradictions=contradictions,
        n_detectors_fired=n_detectors_fired, n_total_claims=n_total_claims, silent=False,
    )


# ── Narration + caching support ─────────────────────────────────────────


def format_top_text(top: list) -> str:
    """Render the top-N ClaimGroups as a compact text block for Gemini
    narration input."""
    if not top:
        return "No cross-checked findings."
    lines = []
    for i, g in enumerate(top, 1):
        tag = "CHECK THIS" if g.contradiction else ("AGREEMENT" if g.agreement else g.severity.upper())
        lines.append(f"{i}. [{tag}] {g.headline}")
    return "\n".join(lines)


def fingerprint_result(result: Optional[OrchestrationResult]) -> str:
    """A short, stable hash of an orchestrate_insights() result's top list —
    used to cache the AI narration below (same convention as modules.anomaly's
    fingerprint_flagged()) so re-rendering the same top list across Streamlit
    reruns doesn't re-spend a Gemini call; only a genuinely different top
    list invalidates the cache."""
    if result is None or result.silent or not result.top:
        return "empty"
    parts = [f"{g.severity}|{'|'.join(g.detectors)}|{g.headline}" for g in result.top]
    key = "||".join(parts)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


_NARRATION_PROMPT = (
    "You are a senior data analyst producing one short executive-summary paragraph that "
    "synthesizes findings from several independent automated checks (distribution/outlier "
    "scans, confounder checks, causal effect estimates, anomaly detection, dataset drift) "
    "into a single coherent picture. Below is the ranked 'what matters most' list this "
    "synthesis already produced, including where multiple independent checks agree on the "
    "same issue (higher confidence) and any 'check this' items (a potential inconsistency "
    "between two checks worth a second look, not a hard error). Write 3-5 sentences for a "
    "non-technical stakeholder. Do not just restate every line — synthesize, and lead with "
    "the single most important item.\n\nRanked findings:\n{findings_text}"
)


def narrate_orchestration(model, result: Optional[OrchestrationResult]) -> tuple:
    """Ask Gemini to turn the ranked top list into a stakeholder paragraph.

    Returns (narration, error). Falls back gracefully if Gemini is
    unavailable or there's nothing yet to narrate — never raises. Callers
    should cache the result (e.g. keyed by fingerprint_result()) rather
    than re-calling this on every rerun, same convention as every other
    narrate_* helper in the app.
    """
    if model is None:
        return "", "No Gemini model available for narration."
    if result is None or result.silent or not result.top:
        return "Not enough independent findings yet to synthesize a top-line summary.", None

    from modules.ai_analyst import call_gemini

    findings_text = format_top_text(result.top)
    prompt = _NARRATION_PROMPT.format(findings_text=findings_text)
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


# ═══════════════════════════════════════════════════════════════════════
# NARRATION FACT-CHECK — same "plausible but wrong number" safety net
# insight_verifier applies to Auto Analyst's findings, extended here to
# narrate_orchestration()'s executive-summary prose. Each ClaimGroup's
# `headline` is already deterministic, non-LLM text (built straight from
# the contributing detectors' own computed stats), so the reference set
# is simply every number appearing in the ranked top-list headlines
# narrate_orchestration() was given to synthesize — same reasoning as
# auto_insights.insights_reference_numbers().
# ═══════════════════════════════════════════════════════════════════════
def orchestration_reference_numbers(result: Optional[OrchestrationResult]) -> set[float]:
    """Ground-truth numbers for narrate_orchestration()'s prose: every
    number quoted in the ranked top-list headlines. Never raises.
    """
    from modules import insight_verifier

    numbers: set[float] = set()
    if result is None or result.silent:
        return numbers
    try:
        for group in result.top or []:
            numbers.update(insight_verifier.extract_numbers(group.headline))
    except (TypeError, AttributeError):
        pass
    return numbers


def verify_narration(narration: str, result: Optional[OrchestrationResult]) -> dict:
    """Fact-check narrate_orchestration()'s prose against the ranked
    top-list's own numbers. Reuses insight_verifier.verify_finding() —
    same {"status": "confirmed" | "flagged" | "unverifiable", ...}
    contract as every other verified surface in the app. Never raises.
    """
    from modules import insight_verifier

    try:
        reference_numbers = orchestration_reference_numbers(result)
    except Exception:
        reference_numbers = set()
    return insight_verifier.verify_finding(narration or "", reference_numbers)


def proactive_alert_text(result: Optional[OrchestrationResult], last_alerted_fingerprint: Optional[str]) -> Optional[dict]:
    """JARVIS-copilot slice: decide whether Atlas should proactively speak up
    about a *newly changed* orchestration result, with no button click or
    tab visit required — the counterpart to modules.atlas.raise_alert() for
    single-detector Auto-Insight findings, but for the orchestrator's own
    unique signal instead.

    Deliberately narrow, by design:

    - Only the #1 ranked group is considered, and only when it's something
      no single detector's own panel already shows: cross-detector
      agreement or a contradiction flag. A lone severity claim (even
      "high") is left to whichever detector's panel already surfaces it —
      interrupting for that would just duplicate the existing per-detector
      alerting (e.g. auto_insights' own high-severity count already drives
      atlas.raise_alert() on upload).
    - Silent below `MIN_DETECTORS_FOR_OUTPUT + 1` detectors fired. The
      first two detectors to fire on every upload are always auto_insights
      and confounder_scan (see app.py's set_active_dataset()), so a result
      built from exactly `MIN_DETECTORS_FOR_OUTPUT` detectors is the same
      baseline the ambient upload announcement already covers — only a
      *third* detector firing (Causal Effect Estimator, Anomaly Detection,
      Drift, or Auto Analyst's verifier) produces genuinely new synthesis.
    - Fires at most once per distinct top-1 conclusion: the caller passes
      in whatever fingerprint it last alerted on (persisted in
      st.session_state across reruns), and gets back None again once that
      exact result has already been announced — so a plain Streamlit
      rerun of an unchanged result doesn't re-speak it every time.

    Returns None if nothing should be announced, else a dict with a short
    spoken `text` (safe to pass straight to atlas.say_only()) and the new
    `fingerprint` the caller should persist so this doesn't refire on the
    same result.
    """
    if result is None or result.silent or not result.top:
        return None
    if result.n_detectors_fired < MIN_DETECTORS_FOR_OUTPUT + 1:
        return None

    top = result.top[0]
    if not (top.agreement or top.contradiction):
        return None

    fingerprint = fingerprint_result(result)
    if fingerprint == last_alerted_fingerprint:
        return None

    subj = ", ".join(sorted(top.subjects)) if top.subjects else "the dataset"
    if top.contradiction:
        text = f"Heads up — two of my checks disagree on {subj}. Worth a look in the Agent Summary panel."
    else:
        text = (
            f"Quick flag — {len(top.detectors)} independent checks now agree on {subj}. "
            "See the Agent Summary panel for details."
        )
    return {"text": text, "fingerprint": fingerprint}


# Detectors that already actively surface their own findings the instant
# they're computed, so a lone claim from them would just duplicate what the
# user has already seen: auto_insights drives its own ambient alert via
# atlas.raise_alert() on upload; every other listed detector only produces
# output because the user just ran it on its own tab and is looking straight
# at the result. confounder_detection is deliberately absent from this set —
# it runs silently in the background on every upload (same as auto_insights)
# but, unlike auto_insights, has no proactive announcement of its own today.
_TIER2_ALREADY_SURFACED_DETECTORS = frozenset({
    "auto_insights", "causal_att", "causal_cate", "anomaly", "drift", "hypothesis_sweep", "verifier",
})


def proactive_alert_text_tier2(result: Optional[OrchestrationResult], last_alerted_fingerprint: Optional[str]) -> Optional[dict]:
    """JARVIS-copilot slice, tier 2: a narrower companion to
    proactive_alert_text() (tier 1) for a different gap. Tier 1 only speaks
    up for genuine cross-detector agreement/contradiction, and only after a
    third detector fires (the two-detector baseline is already covered by
    the ambient upload announcement). But that ambient announcement is
    itself only driven by auto_insights' own high-severity count —
    confounder_detection runs on every upload too, silently, with no
    proactive surfacing of its own. A freshly detected Simpson's-paradox-
    style confounder is exactly the kind of finding a data scientist would
    want flagged, so this tier fires for it even at the plain two-detector
    baseline.

    Deliberately narrow, same discipline as tier 1:

    - Only the #1 ranked group, and only when it's a lone claim from a
      single detector (agreement/contradiction stays tier 1's job).
    - Only "high" severity — a medium/low lone claim isn't worth
      interrupting for.
    - Only detectors not already in `_TIER2_ALREADY_SURFACED_DETECTORS` —
      today that means confounder_detection specifically; if a future
      detector is added that also runs silently with no alert of its own,
      it's a candidate for exclusion from that set, not this function.
    - Fires at most once per distinct fingerprint, same convention as tier 1
      (callers should track tier 1 and tier 2 fingerprints separately —
      they can legitimately differ on the same OrchestrationResult).

    Returns None if nothing should be announced, else a dict with a spoken
    `text` (safe to pass straight to atlas.say_only()) and the new
    `fingerprint` the caller should persist so this doesn't refire on the
    same result.
    """
    if result is None or result.silent or not result.top:
        return None

    top = result.top[0]
    if top.agreement or top.contradiction:
        return None
    if top.severity != "high":
        return None
    if len(top.detectors) != 1 or top.detectors[0] in _TIER2_ALREADY_SURFACED_DETECTORS:
        return None

    fingerprint = fingerprint_result(result)
    if fingerprint == last_alerted_fingerprint:
        return None

    text = f"Heads up — {top.claims[0].message}"
    return {"text": text, "fingerprint": fingerprint}


def severity_icon(severity: str) -> str:
    """Emoji icon for UI display — mirrors modules.auto_insights.severity_icon."""
    return {"high": "\U0001F534", "medium": "\U0001F7E1", "low": "\U0001F535"}.get(severity, "⚪")
