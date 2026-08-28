from __future__ import annotations

import asyncio
import re
import time

from fastapi.testclient import TestClient
from prism_api import ai_analyst
from prism_api.main import create_app
from prism_api_contracts import AiAnalystRequest


def _dataset(client: TestClient) -> str:
    response = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("sales.csv", b"segment,revenue,private_note\na,10,do-not-send-this-value\nb,12,do-not-send-this-value\n", "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["dataset_id"]


def _terminal_run(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if run["state"] not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    raise AssertionError("SQL run did not complete")


def test_ai_analyst_is_evidence_grounded_compact_and_refuses_causality() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    answered = client.post("/api/v1/ai-analyst/analyze", json={"dataset_id": dataset_id, "question": "What can this dataset support?"})
    causal = client.post("/api/v1/ai-analyst/analyze", json={"dataset_id": dataset_id, "question": "Did segment cause revenue to increase?"})

    assert answered.status_code == 200
    assert answered.json()["outcome"] == "answered"
    assert answered.json()["context"]["raw_sample_rows"] == 0
    assert answered.json()["provenance"]["raw_dataset_sent"] is False
    assert "do-not-send-this-value" not in answered.text
    assert causal.status_code == 200
    assert causal.json()["outcome"] == "insufficient_evidence"
    assert "cannot claim" in causal.json()["answer"]
    assert "Unknown is not no effect" in causal.json()["uncertainty"]


def test_ai_sql_draft_round_trips_only_through_sql_lab_and_back_as_evidence() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    draft = client.post("/api/v1/ai-analyst/analyze", json={"dataset_id": dataset_id, "question": "Count records by segment using SQL"}).json()
    assert draft["outcome"] == "sql_ready"
    assert draft["provenance"]["sql_execution"] == "not_attempted"
    assert draft["sql_connection_id"] == f"local:{dataset_id}"
    submitted = client.post("/api/v1/sql-lab/runs", json={"connection_id": draft["sql_connection_id"], "sql": draft["sql_draft"]})
    run = _terminal_run(client, submitted.json()["run_id"])
    reused = client.post("/api/v1/ai-analyst/analyze", json={"dataset_id": dataset_id, "result_run_id": run["run_id"], "question": "What evidence is available now?"})

    assert submitted.status_code == 201
    assert run["state"] == "succeeded"
    assert reused.status_code == 200
    assert any(item["kind"] == "sql_result" and item["provenance_ref"] == run["run_id"] for item in reused.json()["evidence"])


def test_ai_stream_emits_incremental_state_token_tool_wait_and_completion() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post("/api/v1/ai-analyst/stream", json={"dataset_id": dataset_id, "question": "Create a SQL count by segment"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: atlas.state" in response.text
    assert "event: atlas.token" in response.text
    assert "event: atlas.tool_wait" in response.text
    assert '"state":"verifying"' in response.text
    assert "event: atlas.complete" in response.text


def test_unreachable_local_provider_falls_back_without_stream_corruption(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRISM_OLLAMA_BASE_URL", "http://127.0.0.1:9")
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post("/api/v1/ai-analyst/stream", json={"dataset_id": dataset_id, "question": "Summarize this safely"})

    assert response.status_code == 200
    assert '"provider":"fallback"' in response.text
    assert "event: atlas.complete" in response.text


def test_cancellation_endpoint_marks_an_active_stream_request() -> None:
    request_id = "ai_test_cancellation"
    cancelled = ai_analyst.threading.Event()
    with ai_analyst._runs_lock:  # noqa: SLF001 - verifies cancellation state seam
        ai_analyst._runs[request_id] = cancelled  # noqa: SLF001
    try:
        response = TestClient(create_app()).post(f"/api/v1/ai-analyst/runs/{request_id}/cancel")
        assert response.status_code == 200
        assert cancelled.is_set()
    finally:
        with ai_analyst._runs_lock:  # noqa: SLF001
            ai_analyst._runs.pop(request_id, None)  # noqa: SLF001


def test_ai_stream_stops_after_a_cancellation_signal() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    async def collect() -> str:
        response = await ai_analyst.stream_analysis(
            AiAnalystRequest(dataset_id=dataset_id, question="What can this dataset support?"),
            ConnectedRequest(),  # type: ignore[arg-type] - narrow request seam used only for disconnect state
        )
        events = response.body_iterator.__aiter__()
        first = await events.__anext__()
        match = re.search(r"id: (ai_[A-Za-z0-9]+)", first)
        assert match is not None
        with ai_analyst._runs_lock:  # noqa: SLF001 - cancellation is a public endpoint contract
            ai_analyst._runs[match.group(1)].set()  # noqa: SLF001
        return str(first) + "".join([str(chunk) async for chunk in events])

    events = asyncio.run(collect())
    assert "event: atlas.cancelled" in events
    assert "event: atlas.complete" not in events


def test_ai_stream_stops_when_the_client_disconnects() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    async def collect() -> str:
        response = await ai_analyst.stream_analysis(
            AiAnalystRequest(dataset_id=dataset_id, question="What can this dataset support?"),
            DisconnectedRequest(),  # type: ignore[arg-type] - narrow request seam used only for disconnect state
        )
        return "".join([str(chunk) async for chunk in response.body_iterator])

    events = asyncio.run(collect())
    assert "event: atlas.cancelled" in events
    assert "event: atlas.complete" not in events
