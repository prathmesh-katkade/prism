from __future__ import annotations

import unittest.mock

from fastapi.testclient import TestClient as PlainTestClient
from prism_api.main import create_app
from reviewing_client import ReviewingTestClient as TestClient

CSV = (
    b"segment,revenue,label\n"
    b"a,10,X\n"
    b"a,10,X\n"  # exact duplicate of row 1
    b"b,,y \n"  # missing revenue, needs trim/case normalization
    b"c,30,Z\n"
    b",40,W\n"  # missing segment
)


def _dataset(client: TestClient) -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": ("sales.csv", CSV, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_state_detects_duplicate_rows_and_missing_values_deterministically() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    first = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    second = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()

    kinds = {issue["kind"] for issue in first["issues"]}
    assert "duplicate_rows" in kinds
    assert "missing_values" in kinds
    assert first == second  # deterministic: same input, same issues, no side effects from reading state


def test_preview_never_mutates_the_dataset() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()

    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "drop_duplicates"})
    assert preview.status_code == 200
    assert preview.json()["affected_rows"] == 1

    after = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert after == before
    assert after["dataset"]["revision"] == 0


def test_apply_creates_a_new_revision_and_is_visible_to_overview_and_sql_lab() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert applied.status_code == 201
    body = applied.json()
    assert body["dataset"]["revision"] == 1
    assert body["dataset"]["row_count"] == 4  # one duplicate row removed
    assert body["transformation"]["source_revision"] == 0
    assert body["transformation"]["resulting_revision"] == 1
    assert body["transformation"]["affected_rows"] == 1

    # Overview now reflects the cleaned revision under the same dataset_id.
    profile = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()
    assert profile["dataset"]["revision"] == 1
    assert profile["quality"]["n_rows"] == 4

    # SQL Lab queries the same connection against the cleaned data, not the original.
    schema = client.get(f"/api/v1/sql-lab/connections/local:{dataset_id}/schema")
    assert schema.status_code == 200
    run = client.post("/api/v1/sql-lab/runs", json={"connection_id": f"local:{dataset_id}", "sql": "SELECT COUNT(*) AS n FROM data"})
    assert run.status_code == 201
    import time

    run_id = run.json()["run_id"]
    for _ in range(100):
        polled = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if polled["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    page = client.get(f"/api/v1/sql-lab/runs/{run_id}/results").json()
    assert page["rows"][0]["n"] == 4


def test_apply_rejects_an_unknown_column_rather_than_guessing() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_column", "column": "does_not_exist"})
    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


def test_fill_missing_reports_affected_rows_and_preserves_row_count() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(
        f"/api/v1/clean/datasets/{dataset_id}/apply",
        json={"operation": "fill_missing", "column": "revenue", "fill_strategy": "median"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["transformation"]["affected_rows"] == 1
    assert body["dataset"]["row_count"] == 5


def test_undo_restores_the_prior_revision_and_drops_the_history_entry() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    state = client.post(f"/api/v1/clean/datasets/{dataset_id}/undo", json={"to_revision": 0}).json()
    assert state["dataset"]["revision"] == 0
    assert state["dataset"]["row_count"] == 5
    assert state["history"] == []

    # A fresh transformation after undo starts a clean new revision 1, not a collision.
    reapplied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert reapplied.json()["dataset"]["revision"] == 1
    assert len(reapplied.json()["transformation"]["transformation_id"]) > 0


def test_transformation_history_accumulates_with_provenance() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "trim_whitespace", "column": "label"})

    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert [item["resulting_revision"] for item in state["history"]] == [1, 2]
    assert all(item["source_fingerprint"] != item["resulting_fingerprint"] for item in state["history"])


def test_transformation_history_is_reconstructed_from_durable_storage_not_a_process_cache() -> None:
    """Clean's history used to live only in a process-local dict, lost on
    every API restart even though the underlying revisions were already
    durable. Prove the fix by reading history through brand-new store/
    registry connections to the same database file -- exactly what a real
    restart leaves behind -- rather than through the running app's
    warmed-up singletons."""
    import prism_api.clean as clean_module
    from prism_api.durable_dataset_store import DurableDatasetStore
    from prism_api.durable_registry import DurableAnalyticalObjectRegistry, history_database_url

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "trim_whitespace", "column": "label"})
    before_restart = clean_module._durable_history(dataset_id)  # noqa: SLF001
    assert [item.resulting_revision for item in before_restart] == [1, 2]

    url = history_database_url()
    fresh_overview_store = DurableDatasetStore(url)
    fresh_registry = DurableAnalyticalObjectRegistry(url)
    with (
        unittest.mock.patch.object(clean_module, "overview_store", fresh_overview_store),
        unittest.mock.patch.object(clean_module, "registry", fresh_registry),
    ):
        after_restart = clean_module._durable_history(dataset_id)  # noqa: SLF001

    assert [item.resulting_revision for item in after_restart] == [1, 2]
    assert [item.transformation_id for item in after_restart] == [item.transformation_id for item in before_restart]
    assert [item.operation for item in after_restart] == [item.operation for item in before_restart]
    assert [item.source_fingerprint for item in after_restart] == [item.source_fingerprint for item in before_restart]
    assert [item.resulting_fingerprint for item in after_restart] == [item.resulting_fingerprint for item in before_restart]


def test_apply_reverts_the_revision_it_just_created_if_provenance_registration_fails() -> None:
    """A failure between committing the new revision and registering its
    provenance must not leave the mutation live behind a failed response --
    a client retry would otherwise apply on top of already-mutated data."""
    import prism_api.clean as clean_module

    client = TestClient(create_app())
    dataset_id = _dataset(client)

    with unittest.mock.patch.object(clean_module, "register_clean_transformation", side_effect=RuntimeError("history database unavailable")):
        response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert response.status_code == 500

    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert state["dataset"]["revision"] == 0
    assert state["dataset"]["row_count"] == 5
    assert state["history"] == []

    # The dataset is usable again on the next attempt, not stuck mid-failure.
    retried = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert retried.status_code == 201
    assert retried.json()["dataset"]["revision"] == 1


def test_recipe_apply_runs_enabled_steps_in_order_and_skips_disabled_ones() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    created = client.post("/api/v1/clean/recipes", json={
        "name": "Standard cleanup",
        "steps": [
            {"request": {"operation": "drop_duplicates"}, "enabled": True},
            {"request": {"operation": "trim_whitespace", "column": "label"}, "enabled": False},
            {"request": {"operation": "fill_missing", "column": "revenue", "fill_strategy": "median"}, "enabled": True},
        ],
    })
    assert created.status_code == 201
    recipe = created.json()
    assert recipe["version"] == 1
    assert len(recipe["steps"]) == 3

    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/recipes/{recipe['recipe_id']}/apply")
    assert applied.status_code == 200
    body = applied.json()
    assert [step["operation"] for step in body["applied_steps"]] == ["drop_duplicates", "fill_missing"]  # the disabled trim step is skipped
    assert body["dataset"]["row_count"] == 4  # one exact-duplicate row dropped; fill_missing changes values, not row count

    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert [item["operation"] for item in state["history"]] == ["drop_duplicates", "fill_missing"]


def test_recipe_apply_is_all_or_nothing_when_a_step_no_longer_matches_the_schema() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    created = client.post("/api/v1/clean/recipes", json={
        "name": "Drops a column that may not exist later",
        "steps": [
            {"request": {"operation": "drop_duplicates"}, "enabled": True},
            {"request": {"operation": "drop_column", "column": "label"}, "enabled": True},
            {"request": {"operation": "drop_column", "column": "label"}, "enabled": True},  # label is already gone by this point
        ],
    })
    recipe = created.json()

    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/recipes/{recipe['recipe_id']}/apply")
    assert response.status_code == 409
    assert "Recipe step 3" in response.json()["detail"]
    assert "label" in response.json()["detail"]

    # All-or-nothing: no revision was committed, not even for the two valid steps before the mismatch.
    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert state["dataset"]["revision"] == 0
    assert state["history"] == []


def test_recipe_later_publication_failure_rolls_back_data_and_provenance_then_retry_succeeds() -> None:
    import prism_api.clean as clean_module
    from prism_analytical_schemas import ObjectKind

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    recipe = client.post("/api/v1/clean/recipes", json={"name": "Two steps", "steps": [
        {"request": {"operation": "drop_duplicates"}, "enabled": True},
        {"request": {"operation": "trim_whitespace", "column": "label"}, "enabled": True},
    ]}).json()
    original = clean_module.registry.register_with_connection
    clean_records = 0

    def fail_second_clean(connection, record, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal clean_records
        if record.kind is ObjectKind.CLEANING_PLAN:
            clean_records += 1
            if clean_records == 2:
                raise RuntimeError("injected later-step storage failure")
        return original(connection, record, **kwargs)

    with unittest.mock.patch.object(clean_module.registry, "register_with_connection", side_effect=fail_second_clean):
        failed = client.post(f"/api/v1/clean/datasets/{dataset_id}/recipes/{recipe['recipe_id']}/apply")
    assert failed.status_code == 500
    assert "no steps were applied" in failed.json()["detail"]
    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert state["dataset"]["revision"] == 0
    assert state["history"] == []
    assert clean_module.registry.list_for_dataset(dataset_id, kind=ObjectKind.CLEANING_PLAN) == []

    retried = client.post(f"/api/v1/clean/datasets/{dataset_id}/recipes/{recipe['recipe_id']}/apply")
    assert retried.status_code == 200
    assert retried.json()["dataset"]["revision"] == 2
    assert len(retried.json()["applied_steps"]) == 2


def test_preview_ticket_rejects_changed_parameters_stale_revision_and_duplicate_submission() -> None:
    client = PlainTestClient(create_app())
    dataset_id = _dataset(client)
    url = f"/api/v1/clean/datasets/{dataset_id}"
    request = {"operation": "trim_whitespace", "column": "label"}
    first = client.post(f"{url}/preview", json=request).json()
    assert first["source_revision"] == 0
    assert first["source_fingerprint"]
    assert client.post(f"{url}/apply", json=request).status_code == 409
    changed = client.post(f"{url}/apply", json={"operation": "normalize_case", "column": "label", "case": "upper", "review_token": first["review_token"]})
    assert changed.status_code == 409
    second = client.post(f"{url}/preview", json=request).json()
    applied = client.post(f"{url}/apply", json={**request, "review_token": first["review_token"]})
    assert applied.status_code == 201
    assert client.post(f"{url}/apply", json={**request, "review_token": first["review_token"]}).status_code == 409
    stale = client.post(f"{url}/apply", json={**request, "review_token": second["review_token"]})
    assert stale.status_code == 409
    assert client.get(f"{url}/state").json()["dataset"]["revision"] == 1


def test_recipe_preview_ticket_rejects_changed_recipe_version_and_intervening_edit() -> None:
    client = PlainTestClient(create_app())
    dataset_id = _dataset(client)
    recipe = client.post("/api/v1/clean/recipes", json={"name": "Review me", "steps": [
        {"request": {"operation": "drop_duplicates"}, "enabled": True},
    ]}).json()
    url = f"/api/v1/clean/datasets/{dataset_id}/recipes/{recipe['recipe_id']}"
    first = client.post(f"{url}/preview").json()
    assert len(first["step_impacts"]) == 1
    changed = client.put(f"/api/v1/clean/recipes/{recipe['recipe_id']}/steps", json={"steps": [
        {"step_id": recipe["steps"][0]["step_id"], "request": {"operation": "trim_whitespace", "column": "label"}, "enabled": True},
    ]})
    assert changed.status_code == 200
    assert client.post(f"{url}/apply", json={"review_token": first["review_token"]}).status_code == 409
    second = client.post(f"{url}/preview").json()
    edit = {"operation": "drop_duplicates"}
    edit_preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json=edit).json()
    assert client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={**edit, "review_token": edit_preview["review_token"]}).status_code == 201
    assert client.post(f"{url}/apply", json={"review_token": second["review_token"]}).status_code == 409


def test_recipe_editing_steps_creates_a_new_version_without_losing_history() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v1/clean/recipes", json={"name": "Evolving recipe", "steps": [{"request": {"operation": "drop_duplicates"}, "enabled": True}]})
    recipe_id = created.json()["recipe_id"]

    updated = client.put(f"/api/v1/clean/recipes/{recipe_id}/steps", json={"steps": [
        {"step_id": "s1", "request": {"operation": "drop_duplicates"}, "enabled": False},
        {"step_id": "s2", "request": {"operation": "trim_whitespace", "column": "label"}, "enabled": True},
    ]})
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    versions = client.get(f"/api/v1/clean/recipes/{recipe_id}/versions").json()
    assert [item["version"] for item in versions] == [1, 2]
    assert versions[0]["steps"][0]["enabled"] is True  # version 1 is untouched by the version-2 edit

    latest = client.get(f"/api/v1/clean/recipes/{recipe_id}").json()
    assert latest["version"] == 2


def test_recipe_apply_rejects_an_unknown_recipe_and_an_all_disabled_recipe() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    missing = client.post(f"/api/v1/clean/datasets/{dataset_id}/recipes/recipe_does_not_exist/apply")
    assert missing.status_code == 404

    created = client.post("/api/v1/clean/recipes", json={"name": "Nothing enabled", "steps": [{"request": {"operation": "drop_duplicates"}, "enabled": False}]})
    recipe_id = created.json()["recipe_id"]
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/recipes/{recipe_id}/apply")
    assert response.status_code == 422


def test_recipes_persist_across_a_fresh_store_connection_not_just_in_process_memory() -> None:
    """Same durability contract as dataset revisions and transformation history:
    survives a fresh connection to the same database file, not a process-local cache."""
    from prism_api.durable_recipe_store import DurableRecipeStore
    from prism_api.durable_registry import history_database_url

    client = TestClient(create_app())
    created = client.post("/api/v1/clean/recipes", json={"name": "Durable recipe", "steps": [{"request": {"operation": "drop_duplicates"}, "enabled": True}]})
    recipe_id = created.json()["recipe_id"]

    fresh_store = DurableRecipeStore(history_database_url())
    recovered = fresh_store.latest(recipe_id)
    assert recovered.recipe_id == recipe_id
    assert recovered.name == "Durable recipe"
    assert recovered.version == 1


def test_category_mapping_renames_grouped_values_and_reports_unresolved_ones() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    # segment values present: a(x2), b(x1), c(x1); "c" is deliberately left out of the mapping.
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "category_mapping", "column": "segment",
        "category_mapping": {"a": "Alpha", "b": "Beta"},
    })
    assert response.status_code == 201
    body = response.json()
    assert body["transformation"]["affected_rows"] == 3  # 2 'a' rows + 1 'b' row

    profile = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()
    segment_column = next(c for c in profile["columns"] if c["name"] == "segment")
    labels = {bucket["label"] for bucket in segment_column["distribution"]}
    assert "Alpha" in labels and "Beta" in labels and "a" not in labels and "b" not in labels
    assert "c" in labels  # unresolved values are preserved, never silently dropped


def test_category_mapping_preview_reports_unresolved_values_explicitly() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={
        "operation": "category_mapping", "column": "segment",
        "category_mapping": {"a": "Alpha"},
    })
    assert preview.status_code == 200
    body = preview.json()
    assert body["unresolved_values"] == ["b", "c"] or sorted(body["unresolved_values"]) == ["b", "c"]
    assert any("not covered" in warning for warning in body["warnings"])


def test_category_mapping_case_insensitive_and_unmatched_values_can_be_cleared() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "category_mapping", "column": "segment",
        "category_mapping": {"A": "Alpha"}, "case_sensitive": False, "preserve_unmatched": False,
    })
    assert response.status_code == 201
    # 2 'a' rows renamed (case-insensitive match) + 'b' and 'c' cleared to missing (preserve_unmatched=False) = 4
    assert response.json()["transformation"]["affected_rows"] == 4


def test_category_mapping_requires_a_mapping() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "category_mapping", "column": "segment"})
    assert response.status_code == 422


def test_get_column_values_returns_distinct_values_with_counts() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.get(f"/api/v1/clean/datasets/{dataset_id}/columns/segment/values")
    assert response.status_code == 200
    body = response.json()
    assert body["column"] == "segment"
    assert body["truncated"] is False
    counts = {item["value"]: item["count"] for item in body["values"]}
    assert counts == {"a": 2, "b": 1, "c": 1}  # the missing segment row is excluded, not counted as a phantom value


def test_get_column_values_rejects_an_unknown_column() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.get(f"/api/v1/clean/datasets/{dataset_id}/columns/not_real/values")
    assert response.status_code == 422


DUP_CSV = (
    b"customer_id,region,revenue\n"
    b"c1,north,100\n"
    b"c1,north,\n"
    b"c2,south,50\n"
)


def test_duplicate_survivorship_most_complete_rule_keeps_the_row_with_fewer_missing_values() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/overview/datasets", files={"file": ("dup.csv", DUP_CSV, "text/csv")})
    dataset_id = response.json()["dataset_id"]

    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "deduplicate_survivorship", "group_by_columns": ["customer_id", "region"], "survivorship_rule": "most_complete",
    })
    assert applied.status_code == 201
    body = applied.json()
    assert body["dataset"]["row_count"] == 2  # the c1/north duplicate group collapses to 1 row
    assert body["transformation"]["affected_rows"] == 1

    rows_response = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows")
    rows = rows_response.json()["rows"]
    c1_row = next(r for r in rows if r["customer_id"] == "c1")
    assert c1_row["revenue"] == 100  # the complete row survived, not the one with a missing revenue


def test_duplicate_survivorship_max_by_column_rule_keeps_the_highest_value() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/overview/datasets", files={"file": ("dup.csv", DUP_CSV, "text/csv")})
    dataset_id = response.json()["dataset_id"]

    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "deduplicate_survivorship", "group_by_columns": ["customer_id", "region"],
        "survivorship_rule": "max_by_column", "survivorship_tiebreak_column": "revenue",
    })
    assert applied.status_code == 201
    rows = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows").json()["rows"]
    c1_row = next(r for r in rows if r["customer_id"] == "c1")
    assert c1_row["revenue"] == 100


def test_duplicate_survivorship_requires_a_tiebreak_column_for_max_by_column_rule() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/overview/datasets", files={"file": ("dup.csv", DUP_CSV, "text/csv")})
    dataset_id = response.json()["dataset_id"]
    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "deduplicate_survivorship", "group_by_columns": ["customer_id", "region"], "survivorship_rule": "max_by_column",
    })
    assert applied.status_code == 422


def test_duplicate_survivorship_requires_at_least_one_grouping_column() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "deduplicate_survivorship"})
    assert response.status_code == 422


DATE_NUMBER_CSV = (
    b"id,signup,amount\n"
    b"1,03/04/2026,\"1.234,56\"\n"  # ambiguous day/month; European-formatted amount
    b"2,15/06/2026,\"2.000,00\"\n"  # unambiguous (day=15 > 12); European-formatted amount
    b"3,01/01/2026,\"500,00\"\n"
)


def test_convert_type_to_datetime_without_a_format_reports_ambiguous_values_instead_of_guessing() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/overview/datasets", files={"file": ("dates.csv", DATE_NUMBER_CSV, "text/csv")})
    dataset_id = response.json()["dataset_id"]

    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "convert_type", "column": "signup", "target_type": "datetime"})
    assert preview.status_code == 200
    body = preview.json()
    # "03/04/2026" and "01/01/2026" both have day,month <= 12; "15/06/2026" does not.
    assert sorted(body["unresolved_values"]) == ["01/01/2026", "03/04/2026"]
    assert any("ambiguous" in warning for warning in body["warnings"])


def test_convert_type_to_datetime_with_a_declared_format_resolves_ambiguity_deterministically() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/overview/datasets", files={"file": ("dates.csv", DATE_NUMBER_CSV, "text/csv")})
    dataset_id = response.json()["dataset_id"]

    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "convert_type", "column": "signup", "target_type": "datetime", "date_format": "%d/%m/%Y"})
    assert applied.status_code == 201
    assert applied.json()["transformation"]["affected_rows"] == 3  # none left unparsed under the declared day-first format

    rows = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows").json()["rows"]
    first_row = next(r for r in rows if r["id"] == 1)
    assert first_row["signup"].startswith("2026-04-03")  # day=03, month=04 under %d/%m/%Y


def test_convert_type_to_numeric_with_european_locale_parses_comma_decimals() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/overview/datasets", files={"file": ("dates.csv", DATE_NUMBER_CSV, "text/csv")})
    dataset_id = response.json()["dataset_id"]

    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "convert_type", "column": "amount", "target_type": "numeric", "number_locale": "european"})
    assert applied.status_code == 201
    assert applied.json()["transformation"]["affected_rows"] == 3

    rows = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows").json()["rows"]
    first_row = next(r for r in rows if r["id"] == 1)
    assert first_row["amount"] == 1234.56  # "1.234,56" under european locale, not misread as 1.23456


def test_convert_type_to_numeric_without_locale_fails_to_parse_european_formatted_values() -> None:
    """Proves the locale flag is load-bearing, not a no-op: the same column, parsed
    under the default (standard) locale, cannot correctly read "1.234,56"."""
    client = TestClient(create_app())
    response = client.post("/api/v1/overview/datasets", files={"file": ("dates.csv", DATE_NUMBER_CSV, "text/csv")})
    dataset_id = response.json()["dataset_id"]

    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "convert_type", "column": "amount", "target_type": "numeric"})
    assert applied.status_code == 201
    assert applied.json()["transformation"]["affected_rows"] == 3  # all three values changed in some way (whether parsed, misparsed, or made missing)

    rows = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows").json()["rows"]
    first_row = next(r for r in rows if r["id"] == 1)
    assert first_row["amount"] != 1234.56  # without the locale declared, this is not silently (mis)read as the correct value


def test_atlas_explains_an_issue_and_proposes_a_previewable_fix_without_applying_it() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    issues = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()["issues"]
    duplicate_issue = next(item for item in issues if item["kind"] == "duplicate_rows")

    explained = client.post(f"/api/v1/clean/datasets/{dataset_id}/atlas", json={"action": "explain_issue", "issue_id": duplicate_issue["issue_id"]})
    assert explained.status_code == 200
    assert explained.json()["proposed_operation"]["operation"] == "drop_duplicates"

    # Atlas never applied anything - the dataset is still at revision 0.
    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert state["dataset"]["revision"] == 0
