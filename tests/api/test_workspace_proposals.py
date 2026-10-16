from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_api.workspace_proposals import _choose_installed_model, propose
from prism_api_contracts import WorkspaceProposalRequest
from pytest import MonkeyPatch


def _source(client: TestClient) -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": ("proposal.csv", b"segment,revenue\nNorth,10\nSouth,20\n", "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def _model_response(candidate: object) -> httpx.Response:
    return httpx.Response(200, json={"response": json.dumps(candidate)}, request=httpx.Request("POST", "http://127.0.0.1:11434/api/generate"))


def _mock_ollama(monkeypatch: MonkeyPatch, respond) -> None:  # type: ignore[no-untyped-def]
    """propose() calls httpx.AsyncClient().post(...), not the module-level
    httpx.post, so it can race the request against client disconnection -
    patch the instance method actually used. `respond` is a plain sync
    callable (url, json=...) -> httpx.Response; wrapped here so test bodies
    stay simple."""
    async def fake_post(_self: httpx.AsyncClient, url: str, json: dict[str, object], **_kwargs: object) -> httpx.Response:
        return respond(url, json=json)
    monkeypatch.setenv("PRISM_OLLAMA_MODEL", "test-local-model")
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def test_local_model_selection_uses_installed_models_only() -> None:
    assert _choose_installed_model(["qwen3:8b", "qwen2.5:3b"]) == "qwen2.5:3b"
    assert _choose_installed_model(["custom:latest"]) == "custom:latest"
    assert _choose_installed_model([]) is None


def test_model_autodiscovery_uses_real_tag_names_without_configured_model(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.delenv("PRISM_OLLAMA_MODEL", raising=False)
    selected: list[str] = []

    async def fake_get(_self: httpx.AsyncClient, url: str, **_kwargs: object) -> httpx.Response:
        assert url.endswith("/api/tags")
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]}, request=httpx.Request("GET", url))

    async def fake_post(_self: httpx.AsyncClient, url: str, json: dict[str, object], **_kwargs: object) -> httpx.Response:
        selected.append(str(json["model"]))
        return _model_response({"explanation": "Keep the source and review the change.", "clean_operation": {"operation": "drop_duplicates"}})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = TestClient(create_app())
    result = client.post("/api/v1/workspace-proposals", json={"kind": "clean", "dataset_id": _source(client), "intent": "Inspect duplicates"})
    assert result.status_code == 200
    assert result.json()["provider"] == "ollama"
    assert selected == ["qwen2.5:3b"]


def test_unavailable_model_retains_manual_path(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("PRISM_AI_PROVIDER", raising=False)
    client = TestClient(create_app())
    dataset_id = _source(client)
    result = client.post("/api/v1/workspace-proposals", json={"kind": "clean", "dataset_id": dataset_id, "intent": "Normalize North"})
    assert result.status_code == 200
    assert result.json()["provider"] == "unavailable"
    assert result.json()["clean_operation"] is None
    assert "manual" in result.json()["explanation"]


def test_model_clean_proposal_is_typed_and_previewed_without_applying(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    _mock_ollama(monkeypatch, lambda *_a, **_k: _model_response({
        "explanation": "Unify this label.",
        "clean_operation": {"operation": "category_mapping", "column": "segment", "category_mapping": {"North": "N"}},
    }))
    client = TestClient(create_app())
    dataset_id = _source(client)
    result = client.post("/api/v1/workspace-proposals", json={"kind": "clean", "dataset_id": dataset_id, "intent": "Normalize North"})
    assert result.status_code == 200
    body = result.json()
    assert body["provider"] == "ollama"
    assert body["clean_preview"]["affected_rows"] == 1
    assert body["clean_preview"]["source_revision"] == 0
    assert client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]["revision"] == 0


def test_model_can_explain_without_inventing_a_clean_mutation(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    _mock_ollama(monkeypatch, lambda *_a, **_k: _model_response({
        "explanation": "Review missing values first; no edit is ready yet.", "clean_operation": None,
    }))
    client = TestClient(create_app())
    dataset_id = _source(client)
    result = client.post("/api/v1/workspace-proposals", json={"kind": "clean", "dataset_id": dataset_id, "intent": "What should I review first?"})
    assert result.status_code == 200
    assert result.json()["provider"] == "ollama"
    assert result.json()["clean_operation"] is None
    assert result.json()["clean_preview"] is None
    assert client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]["revision"] == 0


def test_model_explanation_contradicting_missing_source_values_is_not_served(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    _mock_ollama(monkeypatch, lambda *_a, **_k: _model_response({
        "explanation": "There are no missing values to review.", "clean_operation": None,
    }))
    client = TestClient(create_app())
    upload = client.post("/api/v1/overview/datasets", files={
        "file": ("missing.csv", b"segment,revenue\nNorth,10\n,20\n", "text/csv"),
    })
    assert upload.status_code == 201
    result = client.post("/api/v1/workspace-proposals", json={
        "kind": "clean", "dataset_id": upload.json()["dataset_id"], "intent": "What should I review first?",
    })
    assert result.status_code == 200
    assert result.json()["provider"] == "unavailable"
    assert "contradicted the source profile" in result.json()["explanation"]
    assert result.json()["clean_operation"] is None


def test_model_sql_mutation_and_invalid_chart_fail_closed(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    client = TestClient(create_app())
    dataset_id = _source(client)
    _mock_ollama(monkeypatch, lambda *_a, **_k: _model_response({"explanation": "Write rows", "sql_draft": "DELETE FROM data"}))
    sql = client.post("/api/v1/workspace-proposals", json={"kind": "sql", "dataset_id": dataset_id, "intent": "Summarize revenue"}).json()
    assert sql["provider"] == "unavailable"
    assert sql["sql_draft"] is None
    _mock_ollama(monkeypatch, lambda *_a, **_k: _model_response({"explanation": "Chart unknown", "chart_spec": {
        "mark": "bar", "intent": "comparison", "dimension": "absent", "measure": "revenue", "aggregation": "sum",
    }}))
    chart = client.post("/api/v1/workspace-proposals", json={"kind": "chart", "dataset_id": dataset_id, "intent": "Revenue by segment"}).json()
    assert chart["provider"] == "unavailable"
    assert chart["chart_spec"] is None


def test_expected_revision_mismatch_is_rejected_outright(monkeypatch: MonkeyPatch) -> None:
    """A conversation bound to a revision that the dataset has since moved
    past must be refused, not silently answered against evidence that may
    no longer describe the current data - mirrors Clean's own stale-
    revision rejection at apply time, applied to the ask itself."""
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    client = TestClient(create_app())
    dataset_id = _source(client)
    result = client.post("/api/v1/workspace-proposals", json={
        "kind": "clean", "dataset_id": dataset_id, "intent": "Normalize North", "expected_revision": 5,
    })
    assert result.status_code == 409
    assert "revision" in result.json()["detail"].lower()


def test_expected_revision_matching_current_is_accepted(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    _mock_ollama(monkeypatch, lambda *_a, **_k: _model_response({
        "explanation": "Unify this label.",
        "clean_operation": {"operation": "category_mapping", "column": "segment", "category_mapping": {"North": "N"}},
    }))
    client = TestClient(create_app())
    dataset_id = _source(client)
    result = client.post("/api/v1/workspace-proposals", json={
        "kind": "clean", "dataset_id": dataset_id, "intent": "Normalize North", "expected_revision": 0,
    })
    assert result.status_code == 200
    assert result.json()["provider"] == "ollama"


def test_a_mutation_during_the_model_call_is_detected_not_silently_served(monkeypatch: MonkeyPatch) -> None:
    """The model call can take seconds; a real client could apply a change to
    the same dataset while it's in flight. The single pre-call revision check
    cannot catch this - it already passed before the model was even asked.
    Simulate the race directly: the mocked httpx.post itself mutates the
    dataset (a real apply, through the real endpoint) before returning the
    model's response, exactly where the real network wait would be."""
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    client = TestClient(create_app())
    dataset_id = _source(client)

    def mutate_then_respond(*_args: object, **_kwargs: object) -> httpx.Response:
        preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "drop_duplicates"}).json()
        applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates", "review_token": preview["review_token"]})
        assert applied.status_code == 201
        return _model_response({
            "explanation": "Unify this label.",
            "clean_operation": {"operation": "category_mapping", "column": "segment", "category_mapping": {"North": "N"}},
        })

    _mock_ollama(monkeypatch, mutate_then_respond)
    result = client.post("/api/v1/workspace-proposals", json={"kind": "clean", "dataset_id": dataset_id, "intent": "Normalize North"})
    assert result.status_code == 409
    assert "revision" in result.json()["detail"].lower()
    assert client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]["revision"] == 1  # the race's own mutation, untouched


class _DisconnectsOnceInFlight:
    """Starlette's real Request.is_disconnected() awaits the ASGI receive
    channel, which yields control to the event loop - giving a concurrently
    scheduled task (the Ollama call here) a chance to actually start running
    before this is even checked. Returning True with no yield at all would
    test cancelling a request that was never truly in flight; sleep(0) once
    first makes this a genuine mid-flight cancellation, the real scenario."""
    def __init__(self) -> None:
        self._yielded = False

    async def is_disconnected(self) -> bool:
        if not self._yielded:
            self._yielded = True
            await asyncio.sleep(0)
        return True


def test_a_client_disconnect_cancels_the_in_flight_model_call(monkeypatch: MonkeyPatch) -> None:
    """A real analyst can close the tab or navigate away while the model is
    still responding (the Ollama call alone can take up to
    PRISM_OLLAMA_TIMEOUT_SECONDS). propose() must notice and actually cancel
    its own connection to Ollama - not just stop waiting - and must not hang
    around for the model's full response once nobody is listening. Call the
    coroutine directly with a Request double that reports disconnected
    immediately: this is the one case TestClient's all-or-nothing request
    cycle cannot simulate (a client that *leaves mid-flight*)."""
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    client = TestClient(create_app())
    dataset_id = _source(client)

    cancelled = {"value": False}

    async def hang_until_cancelled(_self: httpx.AsyncClient, _url: str, json: dict[str, object], **_kwargs: object) -> httpx.Response:
        try:
            await asyncio.sleep(3600)  # would hang this test if cancellation didn't actually happen
        except asyncio.CancelledError:
            cancelled["value"] = True
            raise
        raise AssertionError("the mocked Ollama call completed instead of being cancelled")

    monkeypatch.setattr(httpx.AsyncClient, "post", hang_until_cancelled)

    request = WorkspaceProposalRequest(kind="clean", dataset_id=dataset_id, intent="Normalize North")
    result = asyncio.run(asyncio.wait_for(propose(request, _DisconnectsOnceInFlight()), timeout=5))  # type: ignore[arg-type]
    assert result.provider == "unavailable"
    assert "disconnect" in result.explanation.lower()
    assert cancelled["value"] is True, "cancelling generate_task must actually deliver CancelledError to the in-flight Ollama call, not just stop awaiting it"


def test_an_ambiguous_date_conversion_returns_a_real_bounded_clarification(monkeypatch: MonkeyPatch) -> None:
    """The one complete clarification flow this release implements: a
    convert_type to datetime with no date_format, against data the
    deterministic ambiguous-date detector (clean.py, reused not
    reimplemented) actually flags. Explicit question, explicit permitted
    choices, each a typed date_format - never a free-text follow-up, and
    nothing applied by this response alone."""
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    client = TestClient(create_app())
    # The non-date sentinel keeps the source column text-typed at ingestion;
    # otherwise pandas may infer datetime before Clean can review the
    # ambiguous 03/04 value. The day=15 value also tests the chosen format's
    # treatment of a value whose order is not itself ambiguous.
    upload = client.post("/api/v1/overview/datasets", files={"file": (
        "orders.csv", b"segment,ordered_at\nNorth,03/04/2026\nSouth,15/06/2026\nWest,not-a-date\n", "text/csv",
    )})
    assert upload.status_code == 201
    dataset_id = upload.json()["dataset_id"]
    _mock_ollama(monkeypatch, lambda *_a, **_k: _model_response({
        "explanation": "Convert ordered_at to a real date column.",
        "clean_operation": {"operation": "convert_type", "column": "ordered_at", "target_type": "datetime"},
    }))

    result = client.post("/api/v1/workspace-proposals", json={"kind": "clean", "dataset_id": dataset_id, "intent": "Make ordered_at a date"})
    assert result.status_code == 200
    body = result.json()
    clarification = body["clarification"]
    assert clarification is not None
    assert clarification["column"] == "ordered_at"
    assert "03/04/2026" in clarification["question"]
    assert len(clarification["choices"]) == 2
    labels = [choice["label"] for choice in clarification["choices"]]
    assert any("Day first" in label for label in labels)
    assert any("Month first" in label for label in labels)
    date_formats = {choice["parameters"]["date_format"] for choice in clarification["choices"]}
    assert date_formats == {"%d/%m/%Y", "%m/%d/%Y"}

    # Answering resumes the appropriate preview: applying a choice's own
    # parameters to the same operation and re-previewing must actually
    # resolve the ambiguity, not just echo a label back.
    day_first = next(choice for choice in clarification["choices"] if "Day first" in choice["label"])
    resumed = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={
        "operation": "convert_type", "column": "ordered_at", "target_type": "datetime", **day_first["parameters"],
    })
    assert resumed.status_code == 200
    assert resumed.json()["unresolved_values"] == []  # the explicit format resolved every value; no more ambiguity
    # Nothing was mutated by any of this - still revision 0.
    assert client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]["revision"] == 0


def test_a_declared_date_format_or_unambiguous_dates_return_no_clarification(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    client = TestClient(create_app())
    upload = client.post("/api/v1/overview/datasets", files={"file": (
        "orders.csv", b"segment,ordered_at\nNorth,2026-03-04\nSouth,2026-05-06\n", "text/csv",
    )})
    dataset_id = upload.json()["dataset_id"]
    _mock_ollama(monkeypatch, lambda *_a, **_k: _model_response({
        "explanation": "Convert ordered_at to a real date column.",
        "clean_operation": {"operation": "convert_type", "column": "ordered_at", "target_type": "datetime"},
    }))
    result = client.post("/api/v1/workspace-proposals", json={"kind": "clean", "dataset_id": dataset_id, "intent": "Make ordered_at a date"})
    assert result.status_code == 200
    assert result.json()["clarification"] is None  # ISO dates are not ambiguous - nothing to ask


def test_selected_operation_column_and_history_reach_the_model_prompt(monkeypatch: MonkeyPatch) -> None:
    """The analyst's current focus and this same conversation's own prior
    turns are real context for a follow-up - verify they actually reach the
    prompt sent to the model, not just that the request accepts them."""
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    captured: dict[str, object] = {}

    def capture(_url: str, json: dict[str, object], **_kwargs: object) -> httpx.Response:
        captured.update(json)
        return _model_response({"explanation": "Follow-up answer.", "clean_operation": {"operation": "drop_duplicates"}})

    _mock_ollama(monkeypatch, capture)
    client = TestClient(create_app())
    dataset_id = _source(client)
    result = client.post("/api/v1/workspace-proposals", json={
        "kind": "clean", "dataset_id": dataset_id, "intent": "What about the rest?",
        "selected_operation": "category_mapping", "selected_column": "segment",
        "selected_parameters": {"category_mapping": {"North": "N"}, "case_sensitive": False},
        "history": [{"intent": "Normalize North", "explanation": "Unify this label."}],
    })
    assert result.status_code == 200
    prompt = str(captured["prompt"])
    assert "category_mapping" in prompt
    assert "segment" in prompt
    assert "Normalize North" in prompt
    assert "Unify this label." in prompt
    # The operation name and column alone don't say what it would actually
    # do - the real parameters (the mapping itself here) must reach the
    # prompt too, or Atlas can only describe the shape of the change, not
    # the change itself.
    assert "North" in prompt and "N" in prompt


def test_model_timeout_retains_manual_path(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")

    def timeout(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.TimeoutException("offline")

    _mock_ollama(monkeypatch, timeout)
    client = TestClient(create_app())
    dataset_id = _source(client)
    result = client.post("/api/v1/workspace-proposals", json={"kind": "sql", "dataset_id": dataset_id, "intent": "Count rows"})
    assert result.status_code == 200
    assert result.json()["provider"] == "unavailable"
