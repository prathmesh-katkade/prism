from __future__ import annotations

import hashlib
import json as _json

import pandas as pd
from prism_api import atlas_runtime, atlas_sql_adapter, overview, sql_lab
from prism_api.durable_atlas_store import DurableAtlasRunStore
from prism_api_contracts import AtlasModelProviderName, AtlasRunRequest, AtlasSqlAnalysis


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"response": _json.dumps(self._payload)}


def _setup(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    frame = pd.DataFrame({"region": ["west", "east", "west"], "revenue": [10, 7, 5]})
    datasets = overview.DatasetStore()
    dataset = datasets.put(frame, "sales.csv", hashlib.sha256(b"review fixture").hexdigest())
    monkeypatch.setattr(overview, "store", datasets)
    monkeypatch.setattr(sql_lab, "overview_store", datasets)
    monkeypatch.setattr(atlas_sql_adapter, "dataset_store", datasets)
    monkeypatch.setattr(sql_lab, "store", sql_lab.SqlLabStore(tmp_path / "sql.sqlite"))
    monkeypatch.setattr(sql_lab, "register_query_result", lambda *_: None)
    database_url = f"sqlite:///{(tmp_path / 'atlas.sqlite').as_posix()}"
    run_store = atlas_runtime.AtlasRunStore(DurableAtlasRunStore(database_url))
    monkeypatch.setattr(atlas_runtime, "runs", run_store)
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setattr(atlas_runtime, "resolve_current_ollama_model", lambda _configured: "qwen-test:4b")
    monkeypatch.setattr(atlas_runtime, "probe_live_ollama_digest", lambda _model: "sha256:testdigest")
    return dataset, run_store, database_url


def _sql_request(dataset_id: str) -> AtlasRunRequest:
    return AtlasRunRequest(
        dataset_id=dataset_id, objective="Sum revenue by region using SQL",
        sql_analysis=AtlasSqlAnalysis(aggregate="sum", measure="revenue", group_by="region"),
    )


def _plan_shaped(fmt: object) -> bool:
    return not (isinstance(fmt, dict) and "claims" in fmt.get("properties", {}))  # type: ignore[union-attr]


def test_specialist_review_persists_distinct_grounded_contributions_and_challenges_unsupported_claim(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dataset, run_store, database_url = _setup(tmp_path, monkeypatch)

    def _fake_post(_url, *, json, timeout):  # type: ignore[no-untyped-def]
        if _plan_shaped(json.get("format")):
            return _FakeResponse({"steps": []})
        body = _json.loads(json["prompt"])
        role = body["specialist_role"]
        evidence_ids = body["declared_evidence_ids"]
        if role == "query":
            return _FakeResponse({
                "claims": [{
                    "text": "Revenue is highest in the west region, driven by stronger regional demand.",
                    "evidence_ids": evidence_ids[:1],
                }],
                "objections": [], "limitations": ["Descriptive aggregate only."], "next_checks": [],
            })
        if role == "auditor":
            return _FakeResponse({
                "claims": [],
                "objections": [{
                    "text": "The Query claim about 'stronger regional demand' is not supported by the declared "
                            "evidence, which only records summed totals per region.",
                    "evidence_ids": evidence_ids[:1],
                }],
                "limitations": [], "next_checks": [],
            })
        return _FakeResponse({"claims": [], "objections": [], "limitations": [], "next_checks": []})

    monkeypatch.setattr(atlas_runtime.httpx, "post", _fake_post)
    run = run_store.create(_sql_request(dataset.dataset_id), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)
    assert completed.plan.state.value == "completed"

    model_messages = [message for message in completed.messages if message.origin == "model"]
    specialists = {message.specialist.value for message in model_messages}
    assert specialists == {"query", "auditor"}  # Atlas synthesis review returned nothing grounded -> no model message.

    query_claim = next(message for message in model_messages if message.specialist.value == "query")
    auditor_objection = next(message for message in model_messages if message.specialist.value == "auditor")
    assert query_claim.kind == "proposal"
    assert auditor_objection.kind == "objection"

    known_ids = {item.evidence_id for item in completed.evidence}
    assert query_claim.input_refs and set(query_claim.input_refs) <= known_ids
    assert auditor_objection.input_refs and set(auditor_objection.input_refs) <= known_ids
    assert query_claim.model_binding == "qwen-test:4b@sha256:testdigest"
    assert auditor_objection.model_binding == "qwen-test:4b@sha256:testdigest"

    auditor_deterministic = next(
        message for message in completed.messages
        if message.specialist.value == "auditor" and message.origin == "deterministic_service"
    )
    assert auditor_objection.reply_to == auditor_deterministic.message_id
    assert "not supported by the declared evidence" in auditor_objection.content

    atlas_unavailable = next(
        message for message in completed.messages
        if message.specialist.value == "atlas" and message.kind == "review_unavailable"
    )
    assert atlas_unavailable.origin == "deterministic_service"

    # The unresolved model-raised objection survives into final synthesis rather
    # than being silently dropped, even though nothing in this run resolves it.
    assert auditor_objection.content in (completed.uncertainty or "")

    recovered = atlas_runtime.AtlasRunStore(DurableAtlasRunStore(database_url)).get(run.run_id)
    recovered_model_messages = {
        (message.specialist.value, message.kind, message.model_binding) for message in recovered.messages
        if message.origin == "model"
    }
    assert ("query", "proposal", "qwen-test:4b@sha256:testdigest") in recovered_model_messages
    assert ("auditor", "objection", "qwen-test:4b@sha256:testdigest") in recovered_model_messages
    assert recovered.uncertainty == completed.uncertainty


def test_specialist_review_timeout_is_recorded_as_unavailable_not_fabricated(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dataset, run_store, _url = _setup(tmp_path, monkeypatch)

    def _raise_timeout(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise atlas_runtime.httpx.TimeoutException("simulated review timeout")

    monkeypatch.setattr(atlas_runtime.httpx, "post", _raise_timeout)
    run = run_store.create(_sql_request(dataset.dataset_id), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)
    assert completed.plan.state.value == "completed"

    assert not [message for message in completed.messages if message.origin == "model"]
    query_unavailable = next(
        message for message in completed.messages
        if message.specialist.value == "query" and message.kind == "review_unavailable"
    )
    assert "timed_out" in query_unavailable.content
    review_events = [event.payload["specialist_review"] for event in completed.events
                     if isinstance(event.payload.get("specialist_review"), dict)]
    assert any(item["status"] == "timed_out" for item in review_events)
    # The deterministic SQL result itself is untouched by the failed review.
    assert "Recorded SQL result" in (completed.answer or "")


def test_specialist_review_malformed_response_is_recorded_as_invalid_not_fabricated(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dataset, run_store, _url = _setup(tmp_path, monkeypatch)

    def _fake_post(_url, *, json, timeout):  # type: ignore[no-untyped-def]
        if _plan_shaped(json.get("format")):
            return _FakeResponse({"steps": []})
        return _FakeResponse({"claims": "not-a-list", "objections": [], "limitations": [], "next_checks": []})

    monkeypatch.setattr(atlas_runtime.httpx, "post", _fake_post)
    run = run_store.create(_sql_request(dataset.dataset_id), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)

    assert not [message for message in completed.messages if message.origin == "model"]
    review_events = [event.payload["specialist_review"] for event in completed.events
                     if isinstance(event.payload.get("specialist_review"), dict)]
    assert any(item["status"] == "invalid" for item in review_events)


def test_specialist_review_grounds_claims_and_drops_hallucinated_evidence_references(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dataset, run_store, _url = _setup(tmp_path, monkeypatch)

    def _fake_post(_url, *, json, timeout):  # type: ignore[no-untyped-def]
        if _plan_shaped(json.get("format")):
            return _FakeResponse({"steps": []})
        body = _json.loads(json["prompt"])
        if body["specialist_role"] == "query":
            return _FakeResponse({
                "claims": [{"text": "Fabricated claim citing an evidence id that was never declared.",
                            "evidence_ids": ["sql:nonexistent-run-id"]}],
                "objections": [], "limitations": [], "next_checks": [],
            })
        return _FakeResponse({"claims": [], "objections": [], "limitations": [], "next_checks": []})

    monkeypatch.setattr(atlas_runtime.httpx, "post", _fake_post)
    run = run_store.create(_sql_request(dataset.dataset_id), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)

    assert not [message for message in completed.messages if message.origin == "model"]
    query_unavailable = next(
        message for message in completed.messages
        if message.specialist.value == "query" and message.kind == "review_unavailable"
    )
    assert "ungrounded" in query_unavailable.content or "discarded" in query_unavailable.content


def test_specialist_review_is_not_attempted_when_the_production_binding_cannot_be_live_verified(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dataset, run_store, _url = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(atlas_runtime, "probe_live_ollama_digest", lambda _model: None)
    calls: list[object] = []

    def _fake_post(_url, *, json, timeout):  # type: ignore[no-untyped-def]
        calls.append(json)
        return _FakeResponse({"steps": []})

    monkeypatch.setattr(atlas_runtime.httpx, "post", _fake_post)
    run = run_store.create(_sql_request(dataset.dataset_id), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)

    assert not [message for message in completed.messages if message.origin == "model"]
    query_unavailable = next(
        message for message in completed.messages
        if message.specialist.value == "query" and message.kind == "review_unavailable"
    )
    assert "could not be live-verified" in query_unavailable.content
    # No review call was ever placed -- only the (plan-shaped) propose_plan call happened.
    assert all(_plan_shaped(item.get("format")) for item in calls)
