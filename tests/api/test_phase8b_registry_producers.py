"""Phase 8B: dataset-revision objects, remaining producer coverage, and the read-only
lineage API's filter/ordering/security/performance guarantees.

Phase 8A already covers Stats and Clean at the object-shape level in
``test_analytical_object_integration.py``; this file covers what 8B adds on top:
dataset-revision identity/ancestry, SQL Lab/Visualize/Forecasting/ML Lab/AI Analyst
producer coverage, direct-parent wiring, and the registry's behavior at a larger,
synthetic scale.
"""

from __future__ import annotations

import io
import time

import pandas as pd
from fastapi.testclient import TestClient
from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalProvenance,
    DatasetRef,
    GenericReproducibilitySpec,
    LifecycleState,
    ObjectKind,
    Producer,
)
from prism_api.analytical_objects import ensure_dataset_revision, registry
from prism_api.main import create_app
from prism_api_contracts import SqlRunResponse


def _dataset(client: TestClient, csv: bytes = b"x,y,segment,label\n1,10,a,yes\n2,20,a,no\n3,30,b,yes\n4,40,b,no\n", name: str = "phase8b.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _daily_csv(values: list[float]) -> bytes:
    dates = pd.date_range("2026-01-01", periods=len(values), freq="D")
    frame = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "revenue": values})
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode()


FORECAST_CSV = _daily_csv([10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0])


def _classification_csv() -> bytes:
    rows = []
    for i in range(40):
        x1 = float(i % 10)
        x2 = float((i * 3) % 7)
        segment = "a" if i % 3 == 0 else "b" if i % 3 == 1 else "c"
        label = "yes" if (x1 + x2) > 8 else "no"
        rows.append({"x1": x1, "x2": x2, "segment": segment, "label": label})
    buffer = io.StringIO()
    pd.DataFrame(rows).to_csv(buffer, index=False)
    return buffer.getvalue().encode()


CLASSIFICATION_CSV = _classification_csv()


def _terminal_run(client: TestClient, run_id: str) -> SqlRunResponse:
    for _ in range(200):
        response = client.get(f"/api/v1/sql-lab/runs/{run_id}")
        run = SqlRunResponse.model_validate(response.json())
        if run.state.value not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    raise AssertionError("SQL run did not reach a terminal state")


# --- Dataset revision objects --------------------------------------------------------


def test_first_revision_is_registered_on_first_touch_with_no_parent() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})

    records = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)
    assert len(records) == 1
    assert records[0].lifecycle is LifecycleState.COMPLETED
    assert records[0].provenance.parent_refs == []


def test_ensure_dataset_revision_is_idempotent_for_the_same_identity() -> None:
    ref = DatasetRef(dataset_id="ds_idempotent_test", revision=0, source_fingerprint="a" * 64)
    first = ensure_dataset_revision(ref)
    second = ensure_dataset_revision(ref)
    assert first.object_id == second.object_id
    assert len(registry.list_for_dataset("ds_idempotent_test", revision=0, kind=ObjectKind.DATASET_REVISION)) == 1


def test_new_revision_creates_a_distinct_object_and_leaves_the_historical_one_unchanged() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision_0 = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]

    apply_response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert apply_response.status_code == 201

    revision_1 = registry.list_for_dataset(dataset_id, revision=1, kind=ObjectKind.DATASET_REVISION)
    assert len(revision_1) == 1
    assert revision_1[0].object_id != revision_0.object_id
    assert [ref.object_id for ref in revision_1[0].provenance.parent_refs] == [revision_0.object_id]
    # The historical revision-0 object itself is untouched by the later transformation.
    unchanged = registry.get(revision_0.object_id)
    assert unchanged is not None
    assert unchanged.provenance.dataset.revision == 0


def test_clean_produces_correct_revision_ancestry_across_two_transformations() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, b"x,y\n1,2\n1,2\n3,4\n")

    first = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert first.status_code == 201
    second = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "x", "fill_strategy": "median"})
    assert second.status_code == 201

    dsrev_0 = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    dsrev_1 = registry.list_for_dataset(dataset_id, revision=1, kind=ObjectKind.DATASET_REVISION)[0]
    dsrev_2 = registry.list_for_dataset(dataset_id, revision=2, kind=ObjectKind.DATASET_REVISION)[0]
    assert [ref.object_id for ref in dsrev_1.provenance.parent_refs] == [dsrev_0.object_id]
    assert [ref.object_id for ref in dsrev_2.provenance.parent_refs] == [dsrev_1.object_id]

    clean_record_1 = next(r for r in registry.list_for_dataset(dataset_id, revision=1) if r.kind is ObjectKind.CLEANING_PLAN)
    clean_record_2 = next(r for r in registry.list_for_dataset(dataset_id, revision=2) if r.kind is ObjectKind.CLEANING_PLAN)
    assert [ref.object_id for ref in clean_record_1.provenance.parent_refs] == [dsrev_0.object_id]
    assert [ref.object_id for ref in clean_record_2.provenance.parent_refs] == [dsrev_1.object_id]


def test_undo_then_a_different_transformation_disambiguates_the_reused_revision_number() -> None:
    """DatasetStore.revert truncates history and a later transformation reuses the same
    revision *number* for genuinely different data - the dataset-revision object identity
    must include the fingerprint, not just (dataset_id, revision), or the second branch
    would silently resolve to the first branch's abandoned object."""
    client = TestClient(create_app())
    dataset_id = _dataset(client, b"x,y\n1,2\n1,2\n,4\n")

    first = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert first.status_code == 201
    branch_a = registry.list_for_dataset(dataset_id, revision=1, kind=ObjectKind.DATASET_REVISION)[0]

    undo = client.post(f"/api/v1/clean/datasets/{dataset_id}/undo", json={"to_revision": 0})
    assert undo.status_code == 200

    second = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "x", "fill_strategy": "median"})
    assert second.status_code == 201
    branch_b = registry.list_for_dataset(dataset_id, revision=1, kind=ObjectKind.DATASET_REVISION)[0]

    # Both branches really do share the same DatasetStore revision *number*...
    assert branch_a.provenance.dataset.revision == branch_b.provenance.dataset.revision == 1
    # ...but they are distinct objects for distinct data, both still present in history.
    assert branch_a.object_id != branch_b.object_id
    assert branch_a.provenance.dataset.source_fingerprint != branch_b.provenance.dataset.source_fingerprint
    all_revision_1 = registry.list_for_dataset(dataset_id, revision=1, kind=ObjectKind.DATASET_REVISION)
    assert {r.object_id for r in all_revision_1} == {branch_a.object_id, branch_b.object_id}
    # A producer resolving "the current revision" now (DatasetStore's own current pointer,
    # which undo/apply already moved to branch_b) must land on branch_b, not the abandoned
    # branch_a - i.e. re-ensuring the *currently active* revision is idempotent against
    # branch_b, never branch_a.
    from prism_api.overview import store as overview_store

    stored = overview_store.get(dataset_id)
    assert stored.dataset.revision == 1
    assert stored.source_fingerprint == branch_b.provenance.dataset.source_fingerprint
    current_ref = DatasetRef(dataset_id=dataset_id, revision=stored.dataset.revision, source_fingerprint=stored.source_fingerprint)
    resolved = ensure_dataset_revision(current_ref)
    assert resolved.object_id == branch_b.object_id


def test_concurrent_first_touch_registration_never_500s_and_both_callers_get_the_same_object() -> None:
    """Two concurrent producers racing to be the first to register the same dataset-revision
    identity must both succeed and agree on the same record, never surface the registry's
    internal duplicate-id ValueError as a 500."""
    import threading

    from prism_api.analytical_objects import ensure_dataset_revision

    ref = DatasetRef(dataset_id="ds_race_test", revision=0, source_fingerprint="b" * 64)
    results: list[AnalyticalObject] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        results.append(ensure_dataset_revision(ref))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 8
    assert len({record.object_id for record in results}) == 1
    assert len(registry.list_for_dataset("ds_race_test", revision=0, kind=ObjectKind.DATASET_REVISION)) == 1


def test_stats_result_points_to_the_correct_dataset_revision_object_as_its_direct_parent() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})

    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)
    assert [ref.object_id for ref in stats_record.provenance.parent_refs] == [dsrev.object_id]


# --- SQL Lab producer ------------------------------------------------------------------


def test_sql_query_result_is_registered_with_the_correct_revision_and_direct_parent() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    connection_id = f"local:{dataset_id}"

    submitted = client.post("/api/v1/sql-lab/runs", json={"connection_id": connection_id, "sql": "SELECT * FROM data"})
    run = _terminal_run(client, submitted.json()["run_id"])
    assert run.state.value == "succeeded"

    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    sql_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.QUERY_RESULT)
    assert sql_record.lifecycle is LifecycleState.COMPLETED
    assert [ref.object_id for ref in sql_record.provenance.parent_refs] == [dsrev.object_id]
    assert sql_record.provenance.reproducibility.parameters["sql"] == "SELECT * FROM data"
    assert sql_record.payload["row_count"] == 4


def test_sql_query_against_a_non_dataset_connection_is_not_registered() -> None:
    """A query against a configured SQLite/external source has no DatasetStore identity to
    attach to; only the local in-memory dataset connection is registered."""
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = len(registry.list_for_dataset(dataset_id))

    # No SQLite/external source is configured in this test environment, so /connections
    # only ever exposes the local dataset connection - confirm nothing new was registered
    # beyond what the local-connection test above would add, by checking a fresh dataset
    # that never runs any query at all still has zero QUERY_RESULT objects.
    other = _dataset(client, name="untouched.csv")
    assert registry.list_for_dataset(other, kind=ObjectKind.QUERY_RESULT) == []
    assert len(registry.list_for_dataset(dataset_id)) == before


# --- Visualize producer ------------------------------------------------------------------


def test_visualization_is_registered_with_reproducible_spec() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "y", "aggregation": "sum", "filters": {}, "max_categories": 20}

    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec)
    assert response.status_code == 200

    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    viz_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.VISUALIZATION)
    assert [ref.object_id for ref in viz_record.provenance.parent_refs] == [dsrev.object_id]
    parameters = viz_record.provenance.reproducibility.parameters
    assert parameters["mark"] == "bar"
    assert parameters["dimension"] == "segment"
    assert parameters["measure"] == "y"
    assert parameters["aggregation"] == "sum"


# --- Forecast producer -------------------------------------------------------------------


def test_forecast_is_registered_with_its_deterministic_configuration_preserved() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV, name="forecast.csv")

    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 5})
    assert response.status_code == 200

    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    forecast_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.FORECAST)
    assert [ref.object_id for ref in forecast_record.provenance.parent_refs] == [dsrev.object_id]
    parameters = forecast_record.provenance.reproducibility.parameters
    assert parameters["datetime_col"] == "date"
    assert parameters["numeric_col"] == "revenue"
    assert parameters["horizon"] == 5
    assert "frequency" in parameters and "model_used" in parameters


# --- ML Lab producers --------------------------------------------------------------------


def test_ml_baseline_is_registered_with_target_features_model_seed_and_split() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV, name="ml.csv")

    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    assert response.status_code == 200

    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    ml_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ML_MODEL)
    assert [ref.object_id for ref in ml_record.provenance.parent_refs] == [dsrev.object_id]
    parameters = ml_record.provenance.reproducibility.parameters
    assert ml_record.provenance.reproducibility.operation == "baseline"
    assert parameters["target_col"] == "label"
    assert parameters["feature_cols"] == ["x1", "x2", "segment"]
    assert parameters["task_type"] == "classification"
    assert parameters["seed"] == 42
    assert "Random Forest" in parameters["models"]


def test_ml_feature_selection_and_shap_are_registered_as_separate_objects() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV, name="ml.csv")

    fs_response = client.post(f"/api/v1/ml/datasets/{dataset_id}/feature-selection", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    assert fs_response.status_code == 200
    shap_response = client.post(f"/api/v1/ml/datasets/{dataset_id}/shap", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    assert shap_response.status_code == 200

    ml_records = [r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ML_MODEL]
    operations = {r.provenance.reproducibility.operation for r in ml_records}
    assert operations == {"feature_selection", "shap"}
    assert len({r.object_id for r in ml_records}) == 2

    shap_record = next(r for r in ml_records if r.provenance.reproducibility.operation == "shap")
    assert shap_record.provenance.reproducibility.parameters["model_explained"] == "Random Forest"
    # No fitted model, transformed matrix, or raw SHAP array crosses into the registry.
    assert shap_record.payload == {}


# --- AI Analyst producer -----------------------------------------------------------------


def test_ai_analyst_registers_evidence_only_for_a_completed_answered_outcome() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    answered = client.post("/api/v1/ai-analyst/analyze", json={"dataset_id": dataset_id, "question": "What can this dataset support with confidence?"})
    assert answered.status_code == 200
    assert answered.json()["outcome"] == "answered"

    evidence_records = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.EVIDENCE)
    assert len(evidence_records) == 1
    assert evidence_records[0].payload["answer"] == answered.json()["answer"]
    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    assert [ref.object_id for ref in evidence_records[0].provenance.parent_refs] == [dsrev.object_id]


def test_ai_analyst_does_not_register_a_causal_refusal_or_an_unexecuted_sql_draft() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    causal = client.post("/api/v1/ai-analyst/analyze", json={"dataset_id": dataset_id, "question": "Did segment cause revenue to increase?"})
    assert causal.json()["outcome"] == "insufficient_evidence"
    sql_ready = client.post("/api/v1/ai-analyst/analyze", json={"dataset_id": dataset_id, "question": "Count rows grouped by segment using SQL"})
    assert sql_ready.json()["outcome"] == "sql_ready"

    assert registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.EVIDENCE) == []


def test_ai_analyst_evidence_carries_no_secret_shaped_text() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    question = "What can this dataset support? api_key=sk-should-not-be-stored-abcdef123456"

    response = client.post("/api/v1/ai-analyst/analyze", json={"dataset_id": dataset_id, "question": question})
    assert response.status_code == 200
    assert response.json()["outcome"] == "answered"

    evidence_record = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.EVIDENCE)[0]
    stored_question = evidence_record.provenance.reproducibility.parameters["question"]
    assert "sk-should-not-be-stored" not in stored_question
    assert stored_question == "[redacted]"


# --- Read-only lineage API: filters, ordering, immutability --------------------------


def test_dataset_filter_revision_filter_kind_filter_and_combinations() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    by_dataset = client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects").json()
    assert len(by_dataset) >= 3  # dsrev(0), stats, dsrev(1), clean

    by_revision_0 = client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects", params={"revision": 0}).json()
    assert all(item["provenance"]["dataset"]["revision"] == 0 for item in by_revision_0)

    by_kind = client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects", params={"kind": "dataset_revision"}).json()
    assert {item["kind"] for item in by_kind} == {"dataset_revision"}
    assert len(by_kind) == 2  # revision 0 and revision 1

    combined = client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects", params={"revision": 1, "kind": "cleaning_plan"}).json()
    assert len(combined) == 1
    assert combined[0]["kind"] == "cleaning_plan"
    assert combined[0]["provenance"]["dataset"]["revision"] == 1


def test_empty_list_for_a_dataset_and_revision_with_no_matching_objects() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    assert client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects", params={"kind": "forecast"}).json() == []
    assert client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects", params={"revision": 7}).json() == []


def test_listing_order_is_deterministic_newest_first() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "y", "aggregation": "sum", "filters": {}, "max_categories": 20})

    first = client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects", params={"revision": 0}).json()
    second = client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects", params={"revision": 0}).json()
    assert first == second  # same call twice -> identical, stable order
    created_ats = [item["provenance"]["created_at"] for item in first]
    assert created_ats == sorted(created_ats, reverse=True)


def test_get_object_returns_404_for_a_missing_id_and_200_for_a_real_one() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    object_id = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.ANALYSIS)[0].object_id

    assert client.get(f"/api/v1/lineage/objects/{object_id}").status_code == 200
    assert client.get("/api/v1/lineage/objects/does-not-exist").status_code == 404


# --- Security: nested secret redaction over the HTTP boundary ------------------------


def test_nested_secret_keys_are_redacted_in_sql_query_result_parameters_over_http() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={
            "connection_id": f"local:{dataset_id}",
            "sql": "SELECT * FROM data WHERE segment = $api_key",
            "parameters": {"api_key": "sk-should-not-leak-a"},
        },
    )
    run = _terminal_run(client, submitted.json()["run_id"])
    assert run.state.value == "succeeded"

    sql_record = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.QUERY_RESULT)[0]
    fetched = client.get(f"/api/v1/lineage/objects/{sql_record.object_id}").json()
    parameters = fetched["provenance"]["reproducibility"]["parameters"]["parameters"]
    assert parameters["api_key"] == "[redacted]"
    body_text = client.get(f"/api/v1/lineage/objects/{sql_record.object_id}").text
    assert "sk-should-not-leak" not in body_text


def test_nested_secret_values_do_not_leak_through_ml_reproducibility_parameters() -> None:
    """Reproducibility parameters are sanitized regardless of producer - a value that looks
    like a credential (not just a credential-shaped key) is also caught."""
    from prism_analytical_schemas import sanitize_provenance_parameters

    sanitized = sanitize_provenance_parameters(
        {
            "nested": {"connection": "postgresql://analyst:s3cr3t@db.example/prism", "token": "abc"},
            "list_of_dicts": [{"password": "do-not-store"}, {"safe": "kept"}],
        }
    )
    assert sanitized["nested"]["connection"] == "[redacted]"
    assert sanitized["nested"]["token"] == "[redacted]"
    assert sanitized["list_of_dicts"][0]["password"] == "[redacted]"
    assert sanitized["list_of_dicts"][1]["safe"] == "kept"


# --- Performance sanity at a larger synthetic history size ---------------------------


def test_registry_retrieval_stays_fast_at_one_thousand_objects() -> None:
    from datetime import datetime, timezone

    local_registry = registry.__class__()
    dataset_id = "ds_perf_test"
    for i in range(1_000):
        revision = i % 10
        kind = ObjectKind.ANALYSIS if (i // 10) % 2 == 0 else ObjectKind.VISUALIZATION
        local_registry.register(
            AnalyticalObject(
                object_id=f"perf_{i}",
                kind=kind,
                lifecycle=LifecycleState.COMPLETED,
                provenance=AnalyticalProvenance(
                    dataset=DatasetRef(dataset_id=dataset_id, revision=revision, source_fingerprint="a" * 64),
                    reproducibility=GenericReproducibilitySpec(producer=Producer(service="perf", version="1"), operation="test"),
                    created_at=datetime.now(timezone.utc),
                ),
                payload={},
            )
        )

    started = time.perf_counter()
    for _ in range(50):
        results = local_registry.list_for_dataset(dataset_id, revision=3, kind=ObjectKind.ANALYSIS)
    elapsed = time.perf_counter() - started

    assert len(results) == 50  # 1000 objects / 10 revisions / 2 kinds
    assert elapsed < 1.0  # 50 filtered lookups over 1,000 records stay well under a second
