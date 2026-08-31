"""Phase 8G: Atlas lineage awareness - deterministic explanations over Phase 8A-8F's
own recorded provenance/freshness/reproducibility data.

Atlas here, as everywhere else in PRISM (see stats.py/visualize.py/forecasting.py's own
``/atlas`` routes), is a rule-based explainer over already-computed deterministic
results - not an LLM call. "No invented dependencies/versions/stale reasons/evidence/
parameters" is therefore structural, not a prompting concern: every fact in an
``AtlasLineageResponse`` traces back to one registry/freshness_service call, never to
free-text generation. There is no chain-of-thought to leak, because none exists.
"""

from __future__ import annotations

from typing import List, Optional

from prism_analytical_schemas import AnalyticalObject, AnalyticalObjectRegistry
from prism_api_contracts import AtlasEvidence, AtlasLineageAction, AtlasLineageResponse

from . import freshness_service
from .overview import DatasetStore

_UNCERTAINTY = (
    "This explanation is generated deterministically from PRISM's own recorded lineage, "
    "freshness, and reproducibility data - never inferred, and never produced by a model."
)


def _method_of(record: AnalyticalObject) -> str:
    spec = record.provenance.reproducibility
    return str(getattr(spec, "operation", None) or getattr(spec, "test", None) or "unknown")


def _diff_parameters(a: AnalyticalObject, b: AnalyticalObject) -> List[str]:
    params_a = getattr(a.provenance.reproducibility, "parameters", {}) or {}
    params_b = getattr(b.provenance.reproducibility, "parameters", {}) or {}
    keys = set(params_a) | set(params_b)
    return sorted(key for key in keys if params_a.get(key) != params_b.get(key))


def _explain_provenance(record: AnalyticalObject) -> AtlasLineageResponse:
    method = _method_of(record)
    summary = (
        f"This {record.kind.value.replace('_', ' ')} was produced by "
        f"{record.provenance.reproducibility.producer.service} v{record.provenance.reproducibility.producer.version} "
        f"using {method}, from dataset {record.provenance.dataset.dataset_id} revision {record.provenance.dataset.revision}."
    )
    evidence = [
        AtlasEvidence(label="Producer", value=f"{record.provenance.reproducibility.producer.service} v{record.provenance.reproducibility.producer.version}"),
        AtlasEvidence(label="Method", value=method),
        AtlasEvidence(label="Dataset revision", value=f"{record.provenance.dataset.dataset_id} rev {record.provenance.dataset.revision}"),
        AtlasEvidence(label="Created", value=record.provenance.created_at.isoformat()),
    ]
    return AtlasLineageResponse(action=AtlasLineageAction.EXPLAIN_PROVENANCE, summary=summary, uncertainty=_UNCERTAINTY, evidence=evidence)


def _explain_staleness(registry: AnalyticalObjectRegistry, overview_store: DatasetStore, record: AnalyticalObject) -> AtlasLineageResponse:
    freshness = freshness_service.assess_object(registry, overview_store, record.object_id)
    if freshness is None:  # pragma: no cover - record was just fetched from this registry
        return AtlasLineageResponse(
            action=AtlasLineageAction.EXPLAIN_STALENESS, summary="Freshness could not be assessed.",
            uncertainty=_UNCERTAINTY, evidence=[], limitation="This object could not be re-fetched to assess freshness.",
        )
    summary = f"This object is {freshness.state.value}: {freshness.reason}"
    evidence = [
        AtlasEvidence(label="State", value=freshness.state.value),
        AtlasEvidence(label="Recorded revision", value=str(freshness.object_revision)),
        AtlasEvidence(label="Active revision", value=str(freshness.active_revision) if freshness.active_revision is not None else "unknown"),
    ]
    limitation = None if freshness.freshness_known else (
        "This process's DatasetStore no longer has this dataset's history (for example, after a "
        "restart) - freshness cannot be determined, and is not guessed as current or stale."
    )
    return AtlasLineageResponse(action=AtlasLineageAction.EXPLAIN_STALENESS, summary=summary, uncertainty=_UNCERTAINTY, evidence=evidence, limitation=limitation)


def _explain_lineage(registry: AnalyticalObjectRegistry, record: AnalyticalObject) -> AtlasLineageResponse:
    parents = registry.get_parents(record.object_id) or []
    children = registry.get_children(record.object_id) or []
    ancestors = registry.ancestors(record.object_id)
    descendants = registry.descendants(record.object_id)
    upstream_phrase = f"depends directly on {len(parents)} object(s)" if parents else "has no recorded upstream dependency (a root object)"
    downstream_phrase = f"{len(children)} object(s) depend on it directly" if children else "nothing recorded depends on it yet"
    summary = f"This object {upstream_phrase}, and {downstream_phrase}."
    evidence = [
        AtlasEvidence(label="Direct parents", value=str(len(parents))),
        AtlasEvidence(label="Direct children", value=str(len(children))),
        AtlasEvidence(label="Total ancestors", value=str(len(ancestors.nodes) if ancestors is not None else 0)),
        AtlasEvidence(label="Total descendants", value=str(len(descendants.nodes) if descendants is not None else 0)),
    ]
    return AtlasLineageResponse(action=AtlasLineageAction.EXPLAIN_LINEAGE, summary=summary, uncertainty=_UNCERTAINTY, evidence=evidence)


def _compare_versions(registry: AnalyticalObjectRegistry, record: AnalyticalObject, compare_to_object_id: Optional[str]) -> AtlasLineageResponse:
    if not compare_to_object_id:
        return AtlasLineageResponse(
            action=AtlasLineageAction.COMPARE_VERSIONS, summary="No comparison object was specified.",
            uncertainty=_UNCERTAINTY, evidence=[], limitation="Provide compare_to_object_id to compare two analytical objects.",
        )
    other = registry.get(compare_to_object_id)
    if other is None:
        return AtlasLineageResponse(
            action=AtlasLineageAction.COMPARE_VERSIONS, summary="The comparison object was not found.",
            uncertainty=_UNCERTAINTY, evidence=[], limitation=f"{compare_to_object_id!r} is not a registered analytical object.",
        )
    same_kind = record.kind == other.kind
    same_identity = record.provenance.dataset.revision == other.provenance.dataset.revision and record.provenance.dataset.source_fingerprint == other.provenance.dataset.source_fingerprint
    changed = _diff_parameters(record, other)
    summary = (
        f"{record.object_id} and {other.object_id} are {'the same kind of object' if same_kind else 'different kinds of object'}, "
        f"{'against the same dataset identity' if same_identity else 'against different dataset identities'}."
    )
    evidence = [
        AtlasEvidence(label="A revision", value=str(record.provenance.dataset.revision)),
        AtlasEvidence(label="B revision", value=str(other.provenance.dataset.revision)),
        AtlasEvidence(label="Changed parameters", value=", ".join(changed) if changed else "none recorded"),
    ]
    return AtlasLineageResponse(action=AtlasLineageAction.COMPARE_VERSIONS, summary=summary, uncertainty=_UNCERTAINTY, evidence=evidence)


def _recommend_reruns(registry: AnalyticalObjectRegistry, overview_store: DatasetStore, record: AnalyticalObject) -> AtlasLineageResponse:
    descendants = registry.descendants(record.object_id)
    stale: List[AnalyticalObject] = []
    if descendants is not None:
        for candidate, _depth in descendants.nodes:
            assessment = freshness_service.assess_object(registry, overview_store, candidate.object_id)
            if assessment is not None and assessment.state.value == "stale":
                stale.append(candidate)
    if not stale:
        return AtlasLineageResponse(action=AtlasLineageAction.RECOMMEND_RERUNS, summary="No recorded downstream object is currently stale.", uncertainty=_UNCERTAINTY, evidence=[])
    summary = f"{len(stale)} downstream object(s) depend on data that is no longer active and may be worth rerunning on the current revision."
    evidence = [AtlasEvidence(label=candidate.kind.value, value=candidate.object_id) for candidate in stale[:10]]
    return AtlasLineageResponse(action=AtlasLineageAction.RECOMMEND_RERUNS, summary=summary, uncertainty=_UNCERTAINTY, evidence=evidence)


def _explain_evidence(record: AnalyticalObject) -> AtlasLineageResponse:
    refs = record.provenance.evidence_refs
    if not refs:
        return AtlasLineageResponse(
            action=AtlasLineageAction.EXPLAIN_EVIDENCE, summary="No recorded evidence references exist for this object.",
            uncertainty=_UNCERTAINTY, evidence=[], limitation="This object's provenance does not carry evidence_refs.",
        )
    summary = f"This object carries {len(refs)} recorded evidence reference(s)."
    evidence = [AtlasEvidence(label=ref.kind, value=(ref.summary or ref.evidence_id)) for ref in refs]
    return AtlasLineageResponse(action=AtlasLineageAction.EXPLAIN_EVIDENCE, summary=summary, uncertainty=_UNCERTAINTY, evidence=evidence)


def explain(
    registry: AnalyticalObjectRegistry,
    overview_store: DatasetStore,
    object_id: str,
    action: AtlasLineageAction,
    compare_to_object_id: Optional[str] = None,
) -> Optional[AtlasLineageResponse]:
    """``None`` means ``object_id`` itself is not registered (caller -> 404)."""
    record = registry.get(object_id)
    if record is None:
        return None
    if action is AtlasLineageAction.EXPLAIN_PROVENANCE:
        return _explain_provenance(record)
    if action is AtlasLineageAction.EXPLAIN_STALENESS:
        return _explain_staleness(registry, overview_store, record)
    if action is AtlasLineageAction.EXPLAIN_LINEAGE:
        return _explain_lineage(registry, record)
    if action is AtlasLineageAction.COMPARE_VERSIONS:
        return _compare_versions(registry, record, compare_to_object_id)
    if action is AtlasLineageAction.RECOMMEND_RERUNS:
        return _recommend_reruns(registry, overview_store, record)
    if action is AtlasLineageAction.EXPLAIN_EVIDENCE:
        return _explain_evidence(record)
    raise ValueError(f"Unhandled Atlas lineage action: {action}")  # pragma: no cover - exhaustive enum above
