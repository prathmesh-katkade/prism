from __future__ import annotations

from time import perf_counter

from fastapi.testclient import TestClient
from prism_api.main import create_app


def test_deterministic_ai_analyst_compact_context_baseline() -> None:
    client = TestClient(create_app())
    uploaded = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("sales.csv", b"segment,revenue\na,10\nb,12\n", "text/csv")},
    )
    started = perf_counter()
    response = client.post(
        "/api/v1/ai-analyst/analyze",
        json={"dataset_id": uploaded.json()["dataset_id"], "question": "What is known?"},
    )
    elapsed_ms = (perf_counter() - started) * 1_000

    assert response.status_code == 200
    assert elapsed_ms < 1_500
