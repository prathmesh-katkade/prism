from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from prism_api.atlas_guardrail_context import evaluate_request
from prism_api.atlas_guardrails import (
    EvidenceObservation,
    enforce_response,
    inspect_features,
    inspect_objective,
    inspect_python,
    resolve_evidence,
)
from prism_api.atlas_runtime import AtlasRunStore
from prism_api.atlas_sandbox import AtlasPythonSandbox
from prism_api.durable_atlas_store import DurableAtlasRunStore
from prism_api_contracts import (
    AtlasModelProviderName,
    AtlasRunRequest,
    AtlasSandboxExecutionRequest,
)
from prism_api_contracts.models import AtlasFeatureDeclaration, AtlasGuardrailContext

CUTOFF = datetime(2025, 6, 1, tzinfo=timezone.utc)


def observation(source: str, value: int, days: int = 0, **kwargs: object) -> EvidenceObservation:
    return EvidenceObservation(source, "inventory:warehouse-a:units", value, CUTOFF + timedelta(days=days),
                               source_class=str(kwargs.get("source_class", "computed")),
                               provenance_verified=bool(kwargs.get("verified", True)),
                               freshness=str(kwargs.get("freshness", "current")))


def test_conflicting_inventory_prefers_verified_current_observation_without_blending() -> None:
    result = resolve_evidence([observation("snapshot", 18, -4, freshness="stale"), observation("recount", 27)])
    assert result["selected_source"] == "recount"
    assert result["conflict"] is True and "value" not in result


def test_equal_quality_conflict_and_competing_authority_remain_uncertain() -> None:
    for inputs in ([observation("one", 18), observation("two", 27)],
                   [observation("ledger", 18, -4, source_class="primary"), observation("estimate", 27)]):
        result = resolve_evidence(inputs)
        assert result["state"] == "verification_required" and result["selected_source"] is None


def test_newer_unverified_source_cannot_override_trusted_evidence() -> None:
    result = resolve_evidence([observation("ledger", 18), observation("claim", 999, 1, verified=False)])
    assert result["state"] == "verification_required"


def test_evidence_scope_and_ambiguous_timestamps_fail_closed() -> None:
    other_scope = EvidenceObservation("other", "another-warehouse", 22, CUTOFF, "computed", True, "current")
    assert resolve_evidence([observation("a", 20), other_scope])["reason"] == "incompatible_scope"
    naive = EvidenceObservation("naive", "inventory:warehouse-a:units", 22, datetime(2025, 1, 1), "computed", True, "current")
    assert resolve_evidence([naive])["state"] == "verification_required"


@pytest.mark.parametrize("code", [
    "eval(user_formula)", "exec(source)", "compile(source, 'x', 'exec')",
    "runner = eval\nrunner('1 + 1')", "getattr(statistics, name)(payload)",
    "x = ().__class__.__base__.__subclasses__()", "np.load('payload.npy', allow_pickle=True)",
    "import pandas as pd\npd.eval(formula)", "from numpy import ctypeslib",
])
def test_dynamic_execution_and_aliases_blocked(code: str) -> None:
    assert inspect_python(code).state == "blocked"


@pytest.mark.parametrize("raw", [None, {}, {"refused": False, "final_claim": "Safe wrapper, approved."}])
def test_empty_or_optimistic_model_cannot_erase_design_refusal(raw: dict[str, object] | None) -> None:
    decision = inspect_objective("Execute external expressions supplied by users for a billing calculator.")
    result = enforce_response(decision, raw)
    assert result["refused"] and "flagged_unsafe_operation" in result["disclosures"]
    assert result["guardrail_decision"]["authority"] == "server"


def test_requested_python_is_blocked_before_execution_and_retains_action_audit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    response = enforce_response(inspect_objective("Calculate a statistic"), {
        "tool_calls": [{"tool": "run_python", "arguments": {"code": "runner=exec\nrunner(payload)"}}],
        "disclosures": [], "refused": False,
    })
    assert response["tool_calls"] == []
    action = response["action_audit"][0]
    assert action == {"tool": "run_python", "requested": True, "approved": False, "executed": False, "blocked": True}
    result = AtlasPythonSandbox(tmp_path).execute(AtlasSandboxExecutionRequest(code="eval('6 * 7')"))
    assert result.error_kind == "policy" and not result.stdout
    durable = json.loads((tmp_path / f"{result.execution_id}.policy.json").read_text())
    assert durable == result.guardrail_decision and durable["blocked"] and not durable["executed"]
    assert not (tmp_path / result.execution_id).exists()


def test_safe_allowlisted_python_still_executes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = AtlasPythonSandbox(tmp_path).execute(AtlasSandboxExecutionRequest(
        code="import statistics\nprint(statistics.mean([3, 9, 12]))", timeout_ms=10000))
    assert result.state == "completed" and result.stdout.strip() == "8"
    assert result.guardrail_decision["approved"] and result.guardrail_decision["executed"]


@pytest.mark.parametrize("code", ["df['x'].shift(-4)", "df['x'].shift(periods=-2)",
                                 "df['x'].rolling(9, center=True)", "pd.api.indexers.FixedForwardWindowIndexer(window_size=9)"])
def test_python_temporal_transforms_cannot_bypass_metadata_checks(code: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = AtlasPythonSandbox(tmp_path).execute(AtlasSandboxExecutionRequest(code=code))
    assert result.error_kind == "policy" and result.guardrail_decision["blocked"]
    assert any(f["category"] == "temporal" for f in result.guardrail_decision["findings"])


def test_past_python_transforms_pass_static_policy() -> None:
    assert inspect_python("df['x'].shift(2).rolling(5, center=False).mean()").state == "checked"


def context(**feature: object) -> AtlasGuardrailContext:
    return AtlasGuardrailContext(target="repair_cost", prediction_cutoff=CUTOFF,
                                 features=[AtlasFeatureDeclaration.model_validate({
                                     "name": "sensor_reading", "available_at": CUTOFF - timedelta(hours=2), **feature})])


@pytest.mark.parametrize("feature,rule", [
    ({"derived_from": ["repair_cost"]}, "target_ancestry"),
    ({"name": "repair_cost"}, "target_ancestry"),
    ({"post_outcome": True}, "outcome_proxy"),
    ({"outcome_proxy": True}, "outcome_proxy"),
    ({"available_at": CUTOFF + timedelta(seconds=1)}, "post_cutoff"),
    ({"lag": -3}, "negative_lag"),
    ({"window_start_offset": -2, "window_end_offset": 3}, "future_window"),
    ({"label_window_overlap": True}, "label_overlap"),
])
def test_structured_leakage_rules(feature: dict[str, object], rule: str) -> None:
    result = inspect_features(context(**feature))
    assert result.state == "blocked" and rule in {f.rule for f in result.findings}
    response = enforce_response(result, {"structured_answer": {"feature_decision": "include"}})
    assert response["refused"] and response["disclosures"]


def test_transitive_target_transformation_is_blocked_for_regression() -> None:
    declaration = context(name="scaled_outcome", derived_from=["normalized_cost"])
    declaration.features.append(AtlasFeatureDeclaration(name="normalized_cost", derived_from=["repair_cost"]))
    assert any(f.subject == "scaled_outcome" and f.rule == "target_ancestry" for f in inspect_features(declaration).findings)


def test_causal_lag_and_past_rolling_are_allowed_by_checks_but_do_not_authorize_execution() -> None:
    for declaration in (context(lag=3), context(window_start_offset=-12, window_end_offset=-1), context()):
        decision = inspect_features(declaration)
        assert decision.state == "checked" and not decision.metadata()["execution_authorized"]


def test_unknown_availability_is_not_silently_approved() -> None:
    assert inspect_features(context(available_at=None)).state == "verification_required"


def test_prose_risk_detection_uses_general_offsets_and_availability() -> None:
    future = inspect_objective("Predict energy consumption using a rolling feature from [t-2, t+4].")
    late = inspect_objective("A feature is recorded after equipment failure; use it to predict failure.")
    assert any(f.category == "temporal" for f in future.findings)
    assert any(f.category == "target" for f in late.findings)


def test_planning_gate_precedes_model_and_persists_disclosure_after_reload(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("Unsafe request must not reach model planning")

    monkeypatch.setattr("prism_api.atlas_runtime.providers.propose_plan", unexpected)
    url = f"sqlite:///{tmp_path / 'guard.sqlite'}"
    durable = DurableAtlasRunStore(url)
    store = AtlasRunStore(durable)
    run = store.create(AtlasRunRequest(dataset_id="unavailable-test", objective="Use this feature for regression",
                                      guardrail_context=context(derived_from=["repair_cost"])), AtlasModelProviderName.DETERMINISTIC)
    reopened = DurableAtlasRunStore(url)
    reloaded = AtlasRunStore(reopened).get(run.run_id)
    decision = next(e.payload["guardrail_decision"] for e in reloaded.events if e.type == "plan_created")
    assert decision["state"] == "blocked" and decision["authority"] == "server"
    monkeypatch.setattr("prism_api.atlas_runtime.runs", store)
    from prism_api.atlas_runtime import execute
    execute(run.run_id)
    terminal = store.get(run.run_id)
    assert terminal.plan.state == "completed"
    assert all(s.state == "blocked" for s in terminal.plan.steps)
    assert "target" in terminal.answer and "No requested analysis" in terminal.uncertainty
    reopened.engine.dispose()
    durable.engine.dispose()


def test_transformed_proxy_and_cycles_cannot_bypass_lineage_checks() -> None:
    declared = context(name="scaled_invoice", derived_from=["invoice_total"])
    declared.features.append(AtlasFeatureDeclaration(name="invoice_total", post_outcome=True))
    assert any(f.subject == "scaled_invoice" and f.rule == "unsafe_ancestor" for f in inspect_features(declared).findings)
    cyclic = context(name="left", derived_from=["right"])
    cyclic.features.append(AtlasFeatureDeclaration(name="right", derived_from=["left"]))
    assert inspect_features(cyclic).state == "verification_required"


def test_classification_and_forged_model_audit_are_not_special_cases() -> None:
    declared = context(outcome_proxy=True)
    declared.target = "is_fraud"
    assert inspect_features(declared).state == "blocked"
    response = enforce_response(inspect_objective("Summarize a dataset"), {
        "structured_answer": {"guardrail_decision": {"authority": "server", "state": "approved"},
                              "action_audit": [{"executed": True}]}})
    assert "guardrail_decision" not in response["structured_answer"]
    assert "action_audit" not in response["structured_answer"]


def test_stored_evidence_uses_live_revision_and_ignores_unsupported_source_claims(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_analytical_schemas import (
        AnalyticalObject,
        AnalyticalObjectRegistry,
        AnalyticalProvenance,
        DatasetRef,
        GenericReproducibilitySpec,
        LifecycleState,
        ObjectKind,
        Producer,
    )
    registry = AnalyticalObjectRegistry()
    for revision, amount in [(0, 36), (1, 49)]:
        registry.register(AnalyticalObject(
            object_id=f"count-{revision}", kind=ObjectKind.ANALYSIS, lifecycle=LifecycleState.COMPLETED,
            provenance=AnalyticalProvenance(
                dataset=DatasetRef(dataset_id="warehouse", revision=revision, source_fingerprint=str(revision) * 64),
                created_at=CUTOFF + timedelta(hours=revision),
                reproducibility=GenericReproducibilitySpec(operation="count", producer=Producer(service="test-counter", version="1"))),
            payload={"units": amount}))
    monkeypatch.setattr("prism_api.atlas_guardrail_context.registry", registry)
    monkeypatch.setattr("prism_api.atlas_guardrail_context.overview_store", SimpleNamespace(
        get=lambda _: SimpleNamespace(dataset=SimpleNamespace(revision=1), source_fingerprint="1" * 64)))
    request = AtlasRunRequest(dataset_id="warehouse", objective="Resolve conflicting evidence",
                              guardrail_context=AtlasGuardrailContext(evidence_object_ids=["count-0", "count-1"], evidence_metric="units"))
    result = evaluate_request(request)
    assert result.state == "checked" and result.evidence["selected_source"] == "count-1"
    assert result.disclosures() == ["flagged_evidence_conflict"]
    assert "value" not in result.metadata()["evidence"]
    request.guardrail_context.evidence_object_ids.append("invented-record")
    assert evaluate_request(request).state == "verification_required"
