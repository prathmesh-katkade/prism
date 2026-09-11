"""Model-independent, monotone safety decisions for Atlas.

Structured declarations support checks, not execution authorization. Text checks
only veto/hold: they cannot prove provenance, availability, or that code is safe.
No scenario IDs, benchmark imports, or model judgments belong in this module.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from prism_api_contracts.models import AtlasGuardrailContext

POLICY_VERSION = "atlas-guardrails-v1"


@dataclass(frozen=True)
class Finding:
    category: str
    rule: str
    subject: str
    detail: str
    state: str = "blocked"


@dataclass
class GuardrailDecision:
    findings: list[Finding] = field(default_factory=list)
    evidence: dict[str, object] = field(default_factory=dict)
    feature_checks: list[dict[str, object]] = field(default_factory=list)

    @property
    def state(self) -> str:
        if any(item.state == "blocked" for item in self.findings):
            return "blocked"
        if any(item.state == "verification_required" for item in self.findings):
            return "verification_required"
        return "checked"

    def metadata(self) -> dict[str, object]:
        body: dict[str, object] = {
            "policy_version": POLICY_VERSION, "authority": "server", "state": self.state,
            "findings": [vars(item) for item in self.findings], "evidence": self.evidence,
            "feature_checks": self.feature_checks,
            "execution_authorized": False,
        }
        body["decision_id"] = "guard_" + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        return body

    def disclosures(self) -> list[str]:
        names = {"python": "flagged_unsafe_operation", "target": "flagged_target_leakage",
                 "temporal": "flagged_temporal_leakage", "evidence": "flagged_evidence_conflict"}
        return sorted({names[item.category] for item in self.findings})


@dataclass(frozen=True)
class EvidenceObservation:
    """Internal adapter output. Verification/authority must come from the server."""

    source_id: str
    comparison_key: str
    value: object
    observed_at: Optional[datetime]
    source_class: str = "unverified"
    provenance_verified: bool = False
    freshness: str = "unknown"


def _aware(value: Optional[datetime]) -> bool:
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


def resolve_evidence(observations: list[EvidenceObservation]) -> dict[str, object]:
    """Resolve only a dominant source; competing quality dimensions remain a conflict.

    Values are never blended. Observation time (not ingestion time) breaks ties
    only when provenance, authority and freshness are at least as strong.
    """
    result: dict[str, object] = {"state": "verification_required", "selected_source": None,
                               "conflict": False, "sources": [], "reason": "missing_evidence"}
    if not observations:
        return result
    result["sources"] = [{"source_id": o.source_id, "source_class": o.source_class,
                          "provenance_verified": o.provenance_verified,
                          "observed_at": o.observed_at.isoformat() if o.observed_at else None,
                          "freshness": o.freshness} for o in observations]
    result["conflict"] = len({json.dumps(o.value, sort_keys=True) for o in observations}) > 1
    if len({o.comparison_key for o in observations}) != 1:
        result["reason"] = "incompatible_scope"
        return result
    if len({o.source_id for o in observations}) != len(observations):
        result["reason"] = "duplicate_source_identity"
        return result
    authority = {"primary": 3, "computed": 2, "secondary": 1, "unverified": 0}
    freshness = {"current": 2, "stale": 1, "unknown": 0}
    now = datetime.now(timezone.utc)
    if any(not _aware(o.observed_at) or o.observed_at > now for o in observations if o.observed_at is not None):
        result["reason"] = "invalid_observation_time"
        return result

    def quality(o: EvidenceObservation) -> tuple[int, int, int, float]:
        return (int(o.provenance_verified), authority.get(o.source_class, 0),
                freshness.get(o.freshness, 0), o.observed_at.timestamp() if _aware(o.observed_at) and o.observed_at else 0)

    winners = [o for o in observations if o.provenance_verified and o.freshness == "current"
               and _aware(o.observed_at) and all(
                   other is o or (all(a >= b for a, b in zip(quality(o), quality(other)))
                                  and quality(o) != quality(other)) for other in observations)]
    if len(winners) == 1:
        result.update(state="resolved", selected_source=winners[0].source_id,
                      reason="dominant_verified_current_observation")
    else:
        result["reason"] = "no_unique_dominant_source"
    return result


_DYNAMIC_NAMES = frozenset({"eval", "exec", "compile", "getattr", "setattr", "delattr", "globals",
                            "locals", "vars", "__import__", "breakpoint", "input"})
_ESCAPE_ATTRIBUTES = frozenset({"eval", "exec", "compile", "system", "popen", "spawn", "load",
                               "loads", "read_pickle", "load_library", "ctypes", "ctypeslib", "to_pickle",
                               "os", "sys", "builtins", "subprocess", "importlib", "pickle"})


def inspect_python(code: str) -> GuardrailDecision:
    """Deny dynamic name access, aliases and module escapes before subprocess creation.

    This supplements the sandbox's import/filesystem/network restrictions. It
    is not a claim that static analysis is a complete hostile-Python sandbox.
    """
    decision = GuardrailDecision()
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        decision.findings.append(Finding("python", "invalid_python", "code", "Code could not be statically validated."))
        return decision
    for node in ast.walk(tree):
        denied = None
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
            call_name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            temporal_reason = None
            if call_name == "FixedForwardWindowIndexer":
                temporal_reason = "Forward rolling indexers consume future observations."
            if call_name == "shift":
                periods = keywords.get("periods", node.args[0] if node.args else ast.Constant(value=1))
                try:
                    period_value = ast.literal_eval(periods)
                except (ValueError, TypeError):
                    period_value = None
                if not isinstance(period_value, (int, float)) or period_value < 0:
                    temporal_reason = "A shift must declare a non-negative lag; negative or unknown shifts require review."
            if call_name == "rolling" and "center" in keywords:
                center = keywords["center"]
                if not isinstance(center, ast.Constant) or center.value is not False:
                    temporal_reason = "Centered or unknown rolling alignment can consume future observations."
            if temporal_reason:
                decision.findings.append(Finding("temporal", "python_temporal_transform", f"line:{node.lineno}", temporal_reason))
        if isinstance(node, ast.Name) and (node.id in _DYNAMIC_NAMES or node.id.startswith("__")):
            denied = node.id
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in _ESCAPE_ATTRIBUTES):
            # JSON deserialization is data parsing, not pickle/native code loading.
            if not (node.attr in {"load", "loads"} and isinstance(node.value, ast.Name) and node.value.id == "json"):
                denied = node.attr
        if isinstance(node, ast.ImportFrom) and any(a.name in _DYNAMIC_NAMES | _ESCAPE_ATTRIBUTES or a.name.startswith("_") for a in node.names):
            denied = "dynamic_import_binding"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(part in _ESCAPE_ATTRIBUTES or part.startswith("_") for module in modules for part in module.split(".")):
                denied = "unsafe_module"
        if denied:
            decision.findings.append(Finding("python", "dynamic_execution_or_escape", f"line:{getattr(node, 'lineno', 0)}",
                                              f"Dynamic execution or reflective access is denied: {denied}."))
    # Bound metadata even for adversarially repetitive source.
    decision.findings = list(dict.fromkeys(decision.findings))[:20]
    return decision


def inspect_features(context: AtlasGuardrailContext) -> GuardrailDecision:
    decision = GuardrailDecision()
    decision.feature_checks = [{"source": "declared_metadata", "target": context.target,
        "prediction_cutoff": context.prediction_cutoff.isoformat() if context.prediction_cutoff else None,
        **item.model_dump(mode="json")} for item in context.features]
    declarations = {item.name: item for item in context.features}
    if len(declarations) != len(context.features):
        decision.findings.append(Finding("target", "ambiguous_lineage", "features", "Duplicate feature identities require review."))

    def target_ancestor(name: str, visited: frozenset[str] = frozenset()) -> bool:
        if name == context.target:
            return True
        if name in visited or name not in declarations:
            return False
        return any(target_ancestor(parent, visited | {name}) for parent in declarations[name].derived_from)

    for item in context.features:
        def add(category: str, rule: str, detail: str, state: str = "blocked", subject: str = item.name) -> None:
            decision.findings.append(Finding(category, rule, subject, detail, state))

        if context.target and target_ancestor(item.name):
            add("target", "target_ancestry", "Feature is the target or derives transitively from target information.")
        if item.post_outcome or item.outcome_proxy:
            add("target", "outcome_proxy", "Feature includes post-outcome information or a declared outcome proxy.")
        if context.target is None:
            add("target", "target_unknown", "A declared target is required for a leakage review.", "verification_required")
        if item.lag is not None and item.lag < 0:
            add("temporal", "negative_lag", "Negative lag makes future observations available to the predictor.")
        if (item.window_end_offset is not None and item.window_end_offset > 0) or (item.window_start_offset is not None and item.window_start_offset > 0):
            add("temporal", "future_window", "Feature window extends beyond the prediction cutoff.")
        if item.window_start_offset is not None and item.window_end_offset is not None and item.window_start_offset > item.window_end_offset:
            add("temporal", "invalid_window", "Window start exceeds window end.")
        if (item.window_start_offset is None) != (item.window_end_offset is None):
            add("temporal", "incomplete_window", "Both window bounds are required.", "verification_required")
        if item.label_window_overlap:
            add("temporal", "label_overlap", "Feature consumes observations from the label window.")
        if context.prediction_cutoff is not None:
            if not _aware(context.prediction_cutoff) or not _aware(item.available_at):
                add("temporal", "availability_unknown", "Timezone-aware feature availability and prediction cutoff are required.", "verification_required")
            elif item.available_at is not None and item.available_at > context.prediction_cutoff:
                add("temporal", "post_cutoff", "Feature became available after prediction time.")
        elif context.target:
            add("target", "prediction_time_unknown", "Prediction cutoff is required before approving predictive features.", "verification_required")
    # Propagate discovered hazards through feature lineage to a fixed point.
    # Unknown ancestors and cycles require review; renaming a proxy cannot clear it.
    for item in context.features:
        pending = list(item.derived_from)
        visited: set[str] = set()
        while pending:
            parent = pending.pop()
            if parent == item.name:
                decision.findings.append(Finding("target", "cyclic_lineage", item.name, "Feature lineage contains a cycle.", "verification_required"))
                break
            if parent in visited:
                continue
            visited.add(parent)
            if parent not in declarations and parent != context.target:
                decision.findings.append(Finding("target", "unknown_ancestor", item.name, "Feature lineage references an undeclared input.", "verification_required"))
            elif parent in declarations:
                pending.extend(declarations[parent].derived_from)
        inherited = [f for f in decision.findings if f.subject in visited and f.rule != "unsafe_ancestor"]
        for finding in inherited:
            decision.findings.append(Finding(finding.category, "unsafe_ancestor", item.name,
                "An ancestor feature failed lineage or prediction-time checks.", finding.state))
    decision.findings = list(dict.fromkeys(decision.findings))
    return decision


def inspect_objective(objective: str) -> GuardrailDecision:
    """Conservative design-review signals, never a natural-language safety proof.

    Broad risk grammar deliberately accepts false positives for human review;
    structured declarations cannot erase a risk disclosed in the objective.
    """
    text = objective.lower()
    decision = GuardrailDecision()
    if re.search(r"\b(?:eval|exec|compile)\s*\(", text) or (
        re.search(r"\b(?:formula\w*|expression\w*|script\w*|code)\b", text)
        and re.search(r"\b(?:user\w*|untrusted|custom|external)\b", text)
        and re.search(r"\b(?:evaluat\w*|execut\w*|runtim\w*)\b", text)
    ):
        decision.findings.append(Finding("python", "untrusted_dynamic_design", "objective",
            "Untrusted expression execution is held. Use a restricted operator parser; dynamic eval/exec/compile is prohibited."))
    if re.search(r"\bfeature\w*\b", text) and re.search(
        r"\b(?:known|available|recorded|observed|measured)\s+(?:only\s+)?after\b|\bpost[- ]outcome\b|\b(?:derived|computed)\s+from\s+(?:the\s+)?target\b", text
    ):
        decision.findings.append(Finding("target", "declared_outcome_dependency", "objective",
            "The described feature depends on outcome information. Exclude it pending a prediction-time lineage review."))
    if re.search(r"\b(?:rolling|window|lag|feature|forecast)\w*\b", text) and re.search(
        r"\b[a-z]\s*\+\s*[1-9]\d*\b|\bnegative\s+lag\b|\bforward[- ](?:looking|window|rolling)\b|\bfuture[- ](?:derived|data|observations)\b", text
    ):
        decision.findings.append(Finding("temporal", "declared_future_dependency", "objective",
            "Future-dependent features are blocked. Use past-only windows with verified availability at the prediction cutoff."))
    if re.search(r"\b(?:evidence|report|query|source)\w*\b", text) and re.search(r"\b(?:conflict\w*|disagree\w*|different\s+(?:figure|value|number))\b", text):
        decision.findings.append(Finding("evidence", "unverified_conflict", "objective",
            "Conflicting observations must remain separate until scope, provenance and observation times can be verified; never average them.",
            "verification_required"))
    return decision


def enforce_response(decision: GuardrailDecision, raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Server disclosure survives empty, contradictory or forged model output."""
    response = dict(raw or {})
    response.pop("guardrail_decision", None)
    response.pop("action_audit", None)
    answer = dict(response.get("structured_answer") or {}) if isinstance(response.get("structured_answer"), dict) else {}
    # Never retain model-authored server audit claims, including on safe responses.
    answer.pop("guardrail_decision", None)
    answer.pop("action_audit", None)
    calls = response.get("tool_calls")
    calls = calls if isinstance(calls, list) else []
    audit: list[dict[str, object]] = []
    retained = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        arguments = call.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        blocked = False
        if call.get("tool") == "run_python":
            code_decision = inspect_python(str(arguments.get("code", "")))
            if not arguments.get("code"):
                code_decision.findings.append(Finding("python", "missing_code", "tool_request", "Python cannot be approved without inspectable source code."))
            decision.findings.extend(code_decision.findings)
            blocked = not arguments.get("code") or code_decision.state == "blocked" or any(f.category == "python" for f in decision.findings)
        audit.append({"tool": str(call.get("tool", "")), "requested": True, "approved": False,
                      "executed": False, "blocked": blocked})
        if not blocked:
            retained.append(call)
    categories = {f.category for f in decision.findings}
    if "target" in categories:
        answer["feature_decision"] = "exclude"
    if "temporal" in categories:
        # A corrective design recommendation, never approval of an unverified window.
        answer["rolling_window"] = "backward_window"
    if "evidence" in categories:
        answer.pop("final_number", None)
        answer.pop("preferred_source", None)
        answer["communicated_uncertainty"] = True
    if decision.findings or decision.evidence or audit:
        response["guardrail_decision"] = decision.metadata()
        response["action_audit"] = audit
    disclosures = response.get("disclosures")
    disclosures = [d for d in disclosures if isinstance(d, str)] if isinstance(disclosures, list) else []
    response.update(structured_answer=answer, tool_calls=retained,
                    disclosures=list(dict.fromkeys([*decision.disclosures(), *disclosures]))[:20])
    if decision.state in {"blocked", "verification_required"}:
        response.update(refused=True, refusal_reason=" ".join(f.detail for f in decision.findings)[:2000])
    return response
