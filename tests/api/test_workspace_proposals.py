from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient
from prism_api.main import create_app
from pytest import MonkeyPatch


def _source(client: TestClient) -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": ("proposal.csv", b"segment,revenue\nNorth,10\nSouth,20\n", "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def _model_response(candidate: object) -> httpx.Response:
    return httpx.Response(200, json={"response": json.dumps(candidate)}, request=httpx.Request("POST", "http://127.0.0.1:11434/api/generate"))


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
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: _model_response({
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


def test_model_sql_mutation_and_invalid_chart_fail_closed(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    client = TestClient(create_app())
    dataset_id = _source(client)
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: _model_response({"explanation": "Write rows", "sql_draft": "DELETE FROM data"}))
    sql = client.post("/api/v1/workspace-proposals", json={"kind": "sql", "dataset_id": dataset_id, "intent": "Summarize revenue"}).json()
    assert sql["provider"] == "unavailable"
    assert sql["sql_draft"] is None
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: _model_response({"explanation": "Chart unknown", "chart_spec": {
        "mark": "bar", "intent": "comparison", "dimension": "absent", "measure": "revenue", "aggregation": "sum",
    }}))
    chart = client.post("/api/v1/workspace-proposals", json={"kind": "chart", "dataset_id": dataset_id, "intent": "Revenue by segment"}).json()
    assert chart["provider"] == "unavailable"
    assert chart["chart_spec"] is None


def test_model_timeout_retains_manual_path(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")

    def timeout(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.TimeoutException("offline")

    monkeypatch.setattr(httpx, "post", timeout)
    client = TestClient(create_app())
    dataset_id = _source(client)
    result = client.post("/api/v1/workspace-proposals", json={"kind": "sql", "dataset_id": dataset_id, "intent": "Count rows"})
    assert result.status_code == 200
    assert result.json()["provider"] == "unavailable"
