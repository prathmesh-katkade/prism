from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from prism_api.atlas_bench_live import AtlasBenchSubjectUnavailable, AtlasProviderBenchSubject
from prism_api.atlas_promotion_decisions import DurableAtlasPromotionDecisionStore
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasModelProviderName,
    AtlasPromotionDecision,
    AtlasPromotionVerdict,
)


def _decision(decision_id: str = "decision_test_1") -> AtlasPromotionDecision:
    return AtlasPromotionDecision(
        decision_id=decision_id,
        candidate_id="candidate_test_1",
        production_run_id="benchrun_prod",
        candidate_run_id="benchrun_candidate",
        verdict=AtlasPromotionVerdict.HOLD,
        overall_production_pass_rate=0.8,
        overall_candidate_pass_rate=0.8,
        critical_regressions=[],
        decided_at=datetime.now(timezone.utc),
    )


def test_promotion_decisions_are_durable_append_only_records(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasPromotionDecisionStore(database_url=f"sqlite:///{tmp_path / 'promotion-decisions.db'}")
    first = _decision()
    store.save(first)
    store.save(first)  # idempotent same decision_id, never a second mutable copy

    fetched = store.get(first.decision_id)
    assert fetched is not None
    assert fetched.decision_id == first.decision_id
    assert fetched.verdict is AtlasPromotionVerdict.HOLD
    assert fetched.overall_candidate_pass_rate == 0.8

    listed = store.list_for_candidate(first.candidate_id)
    assert [item.decision_id for item in listed] == [first.decision_id]


def test_live_bench_refuses_configured_but_unreachable_ollama(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRISM_ATLAS_OLLAMA_MODEL", "missing-test-model")

    def unavailable(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", "http://127.0.0.1:11434/api/tags")
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr("prism_api.atlas_bench_live.httpx.get", unavailable)

    with pytest.raises(AtlasBenchSubjectUnavailable, match="no AtlasBench baseline was recorded"):
        AtlasProviderBenchSubject(AtlasModelProviderName.OLLAMA)


def test_decision_route_rejects_unknown_candidate_before_evaluation() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/atlas/promotion/decisions",
        params={
            "candidate_id": "candidate_missing",
            "production_run_id": "benchrun_prod",
            "candidate_run_id": "benchrun_candidate",
            "verdict": "promote_eligible",
            "critical_regression_tolerance": 1.0,
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate artifact was not found."


def test_promote_route_requires_a_real_stored_server_decision() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/atlas/promotion/promote",
        params={
            "decision_id": "decision_missing",
            "reason": "client cannot manufacture eligibility",
            "verdict": "promote_eligible",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Promotion decision was not found."
