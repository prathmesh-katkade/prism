from fastapi.testclient import TestClient
from prism_api import atlas_command_center as summary
from prism_api.main import create_app


def test_empty_summary_is_explicit_and_does_not_scan_training(monkeypatch):
    def forbidden():
        raise AssertionError("dashboard must not compute training eligibility")
    monkeypatch.setattr(summary.foundry, "combined_training_source_summary", forbidden)
    response = TestClient(create_app()).get("/api/v1/atlas/command-center")
    assert response.status_code == 200
    body = response.json()
    assert body["remote_sharing_enabled"] is False
    assert body["sections"]["project"]["state"] == "unavailable"
    assert body["sections"]["training_eligibility"]["state"] == "unavailable"
    assert body["status"]["operational_cert_min_pass_rate"] == 0.9


def test_summary_isolates_failed_section(monkeypatch):
    def unavailable():
        raise RuntimeError("private database connection secret")
    monkeypatch.setattr(summary.foundry, "current_production_trust_status", unavailable)
    response = TestClient(create_app()).get("/api/v1/atlas/command-center")
    body = response.json()
    assert body["sections"]["trust"]["state"] == "error"
    assert body["status"] is None
    assert body["sections"]["runs"]["state"] == "available"
    assert "private database" not in response.text


def test_recent_summary_query_count_is_constant(tmp_path):
    from prism_api.durable_atlas_store import DurableAtlasRunStore
    from sqlalchemy import event
    store = DurableAtlasRunStore(f"sqlite:///{tmp_path / 'summary.db'}")
    statements = []
    event.listen(store.engine, "before_cursor_execute", lambda conn, cursor, statement, parameters, context, executemany: statements.append(statement))
    assert store.recent_summaries(limit=8) == []
    assert len(statements) == 1
    assert "LIMIT" in statements[0]
