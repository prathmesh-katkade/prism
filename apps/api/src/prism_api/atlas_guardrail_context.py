"""Resolve guardrail inputs from durable product records, not model assertions."""

from __future__ import annotations

import json
from datetime import timezone

from prism_api_contracts import AtlasRunRequest

from . import freshness_service
from .analytical_objects import registry
from .atlas_guardrails import (
    EvidenceObservation,
    Finding,
    GuardrailDecision,
    inspect_features,
    inspect_objective,
    resolve_evidence,
)
from .overview import store as overview_store


def evaluate_request(request: AtlasRunRequest) -> GuardrailDecision:
    decision = inspect_objective(request.objective)
    context = request.guardrail_context
    if context is None:
        return decision
    feature_decision = inspect_features(context)
    decision.findings.extend(feature_decision.findings)
    decision.feature_checks = feature_decision.feature_checks
    if not context.evidence_object_ids:
        return decision
    observations = []
    for object_id in context.evidence_object_ids:
        record = registry.get(object_id)
        if record is None or record.provenance.dataset.dataset_id != request.dataset_id or not context.evidence_metric or context.evidence_metric not in record.payload:
            decision.findings.append(Finding("evidence", "missing_scoped_evidence", object_id,
                "Evidence must be a stored result for this dataset with the requested metric.", "verification_required"))
            continue
        freshness = freshness_service.assess_object(registry, overview_store, object_id)
        # Revision may change, but method/configuration must match. Never compare
        # differently scoped analyses merely because they share a metric name.
        spec = record.provenance.reproducibility.model_dump(mode="json")
        comparison_key = json.dumps([request.dataset_id, record.kind.value, context.evidence_metric, spec], sort_keys=True)
        observed_at = record.provenance.created_at
        # Stored SQL timestamps are UTC; normalize only this server-owned source.
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        observations.append(EvidenceObservation(
            source_id=object_id, comparison_key=comparison_key,
            value=record.payload[context.evidence_metric], observed_at=observed_at,
            source_class="computed", provenance_verified=record.lifecycle.value == "completed",
            freshness=freshness.state.value if freshness is not None else "unknown",
        ))
    decision.evidence = resolve_evidence(observations)
    if decision.evidence["state"] != "resolved":
        decision.findings.append(Finding("evidence", "unresolved_evidence", "evidence",
            "No uniquely dominant verified current source supports this answer; preserve observations separately and verify.", "verification_required"))
    elif not any(f.rule == "missing_scoped_evidence" for f in decision.findings):
        decision.findings = [f for f in decision.findings if f.rule != "unverified_conflict"]
        if decision.evidence["conflict"]:
            decision.findings.append(Finding("evidence", "resolved_conflict", "evidence",
                "Sources conflict; server-selected provenance is recorded without averaging observations.", "warning"))
    return decision
