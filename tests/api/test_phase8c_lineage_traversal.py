"""Phase 8C: deterministic dependency-graph traversal over the direct `parent_refs`
links Phase 8A/8B already record.

Covers the reverse child index, direct parent/child lookup, transitive
ancestor/descendant BFS (depth, ordering, max_depth, duplicate/cycle safety),
the compact graph endpoint, shortest path, fingerprint-aware revision identity
under traversal, immutability, security, the HTTP surface, and performance at
synthetic scale. Phase 8A/8B's own test files remain the source of truth for
producer-coverage correctness; this file assumes that coverage and builds
traversal scenarios on top of it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalProvenance,
    DatasetRef,
    GenericReproducibilitySpec,
    LifecycleState,
    ObjectKind,
    ParentRef,
    Producer,
)
from prism_api.analytical_objects import ensure_dataset_revision, registry
from prism_api.main import create_app


def _dataset(client: TestClient, csv: bytes = b"x,y,segment,label\n1,10,a,yes\n2,20,a,no\n3,30,b,yes\n4,40,b,no\n", name: str = "phase8c.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _dsrev(dataset_id: str, revision: int) -> AnalyticalObject:
    return registry.list_for_dataset(dataset_id, revision=revision, kind=ObjectKind.DATASET_REVISION)[0]


def _stub_object(object_id: str, dataset_id: str, revision: int, parent_ids: list[str], fingerprint: str = "a" * 64) -> AnalyticalObject:
    """A minimal, directly-registered object for tests that only need graph shape,
    not a real producer flow (diamond convergence, synthetic cycles, performance)."""
    return AnalyticalObject(
        object_id=object_id,
        kind=ObjectKind.DATASET_REVISION,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=DatasetRef(dataset_id=dataset_id, revision=revision, source_fingerprint=fingerprint),
            parent_refs=[ParentRef(object_id=parent_id, relation="derived_from") for parent_id in parent_ids],
            reproducibility=GenericReproducibilitySpec(producer=Producer(service="test", version="1"), operation="test"),
            created_at=datetime.now(timezone.utc),
        ),
        payload={},
    )


# --- Direct parents ---------------------------------------------------------------------


def test_get_parents_returns_the_one_direct_parent_of_an_analysis_object() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    dsrev = _dsrev(dataset_id, 0)
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    response = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/parents")
    assert response.status_code == 200
    parents = response.json()
    assert [item["object_id"] for item in parents] == [dsrev.object_id]


def test_get_parents_of_a_root_object_is_an_empty_list() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    dsrev = _dsrev(dataset_id, 0)

    response = client.get(f"/api/v1/lineage/objects/{dsrev.object_id}/parents")
    assert response.status_code == 200
    assert response.json() == []


def test_get_parents_of_an_unknown_object_is_404() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/lineage/objects/does-not-exist/parents")
    assert response.status_code == 404


# --- Direct children ---------------------------------------------------------------------


def test_get_children_of_a_revision_returns_every_analysis_that_ran_against_it() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    client.post(
        f"/api/v1/visualize/datasets/{dataset_id}/render",
        json={"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "y", "aggregation": "sum", "filters": {}, "max_categories": 20},
    )
    dsrev = _dsrev(dataset_id, 0)
    expected_ids = {
        r.object_id for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind in (ObjectKind.ANALYSIS, ObjectKind.VISUALIZATION)
    }

    response = client.get(f"/api/v1/lineage/objects/{dsrev.object_id}/children")
    assert response.status_code == 200
    child_ids = {item["object_id"] for item in response.json()}
    assert child_ids == expected_ids


def test_get_children_of_a_leaf_object_is_an_empty_list() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    response = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/children")
    assert response.status_code == 200
    assert response.json() == []


def test_get_children_of_an_unknown_object_is_404() -> None:
    client = TestClient(create_app())
    assert client.get("/api/v1/lineage/objects/does-not-exist/children").status_code == 404


# --- Ancestors: exact chain, depth, ordering --------------------------------------------


def test_ancestors_of_an_analysis_walk_the_full_revision_chain_with_correct_depth() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "x", "fill_strategy": "median"})
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})

    revision0, revision1, revision2 = _dsrev(dataset_id, 0), _dsrev(dataset_id, 1), _dsrev(dataset_id, 2)
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=2) if r.kind is ObjectKind.ANALYSIS)

    response = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/ancestors")
    assert response.status_code == 200
    body = response.json()
    assert body["root_object_id"] == stats_record.object_id
    assert body["direction"] == "upstream"
    assert body["truncated"] is False
    by_id = {node["object"]["object_id"]: node["depth"] for node in body["nodes"]}
    assert by_id == {revision2.object_id: 1, revision1.object_id: 2, revision0.object_id: 3}
    # Deterministic ordering: depth ASC, object_id ASC.
    depths = [node["depth"] for node in body["nodes"]]
    assert depths == sorted(depths)


def test_ancestors_are_stable_across_repeated_identical_calls() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=1) if r.kind is ObjectKind.ANALYSIS)

    first = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/ancestors").json()
    second = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/ancestors").json()
    assert first == second


# --- Descendants: fan-out and branch traversal ------------------------------------------


def test_descendants_of_a_revision_include_its_analyses_and_the_next_revision_and_its_analyses() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})

    revision0, revision1 = _dsrev(dataset_id, 0), _dsrev(dataset_id, 1)
    stats_r0 = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)
    clean_r1 = next(r for r in registry.list_for_dataset(dataset_id, revision=1) if r.kind is ObjectKind.CLEANING_PLAN)
    stats_r1 = next(r for r in registry.list_for_dataset(dataset_id, revision=1) if r.kind is ObjectKind.ANALYSIS)

    response = client.get(f"/api/v1/lineage/objects/{revision0.object_id}/descendants")
    assert response.status_code == 200
    body = response.json()
    assert body["direction"] == "downstream"
    by_id = {node["object"]["object_id"]: node["depth"] for node in body["nodes"]}
    assert by_id[stats_r0.object_id] == 1
    assert by_id[revision1.object_id] == 1
    assert by_id[clean_r1.object_id] == 1  # the clean transformation itself also points at revision0
    assert by_id[stats_r1.object_id] == 2  # reached only via revision1 - one hop further


def test_descendant_branching_from_a_shared_revision_never_duplicates_a_node() -> None:
    """Two Clean applies from the SAME revision-1 (an undo back to 1, then a different
    apply) each create a distinct child revision - descendants(revision1) must list both
    branches, each exactly once, never collapsed or duplicated. Both branches must
    genuinely change different data (not both be no-ops) so they land on distinct
    fingerprints, exactly like the Phase 8B revert/redo scenario this mirrors."""
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=b"x,y,segment,label\n1,10,a,yes\n1,10,a,yes\n,30,b,yes\n4,,b,no\n")
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    branch_a = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "x", "fill_strategy": "median"})
    assert branch_a.status_code == 201
    client.post(f"/api/v1/clean/datasets/{dataset_id}/undo", json={"to_revision": 1})
    branch_b = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "y", "fill_strategy": "median"})
    assert branch_b.status_code == 201

    revision1 = _dsrev(dataset_id, 1)
    revision2_records = registry.list_for_dataset(dataset_id, revision=2, kind=ObjectKind.DATASET_REVISION)
    assert len(revision2_records) == 2  # two distinct fingerprint-disambiguated branches share revision number 2

    response = client.get(f"/api/v1/lineage/objects/{revision1.object_id}/descendants")
    body = response.json()
    node_ids = [node["object"]["object_id"] for node in body["nodes"]]
    assert len(node_ids) == len(set(node_ids))  # no duplicates
    assert {r.object_id for r in revision2_records}.issubset(set(node_ids))


# --- Max depth ------------------------------------------------------------------------


def test_max_depth_bounds_ancestor_traversal_and_reports_truncation() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "x", "fill_strategy": "median"})
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision1, revision2 = _dsrev(dataset_id, 1), _dsrev(dataset_id, 2)
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=2) if r.kind is ObjectKind.ANALYSIS)

    depth_1 = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/ancestors", params={"max_depth": 1}).json()
    assert [node["object"]["object_id"] for node in depth_1["nodes"]] == [revision2.object_id]
    assert depth_1["truncated"] is True

    depth_2 = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/ancestors", params={"max_depth": 2}).json()
    assert {node["object"]["object_id"] for node in depth_2["nodes"]} == {revision2.object_id, revision1.object_id}
    assert depth_2["truncated"] is True

    full = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/ancestors", params={"max_depth": 100}).json()
    assert len(full["nodes"]) == 3
    assert full["truncated"] is False


def test_invalid_max_depth_is_a_validation_error() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    assert client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/ancestors", params={"max_depth": 0}).status_code == 422
    assert client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/ancestors", params={"max_depth": 101}).status_code == 422
    assert client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/descendants", params={"max_depth": -1}).status_code == 422


# --- Duplicate and cycle safety (direct registry construction) -------------------------


def test_diamond_convergence_never_duplicates_the_shared_ancestor() -> None:
    local_registry = registry.__class__()
    local_registry.register(_stub_object("A", "ds_diamond", 0, []))
    local_registry.register(_stub_object("B", "ds_diamond", 1, ["A"]))
    local_registry.register(_stub_object("C", "ds_diamond", 1, ["A"]))
    local_registry.register(_stub_object("D", "ds_diamond", 2, ["B", "C"]))

    result = local_registry.ancestors("D")
    assert result is not None
    ids = [obj.object_id for obj, _depth in result.nodes]
    assert sorted(ids) == ["A", "B", "C"]
    assert len(ids) == len(set(ids))  # A reached via both B and C, but emitted once
    depth_by_id = {obj.object_id: depth for obj, depth in result.nodes}
    assert depth_by_id == {"B": 1, "C": 1, "A": 2}
    # Both edges into the shared ancestor are still recorded.
    assert ("A", "B") in result.edges
    assert ("A", "C") in result.edges


def test_a_malformed_cycle_in_registry_state_does_not_hang_traversal() -> None:
    """The registry's own write path (`register`) cannot create a cycle - this directly
    corrupts internal state to prove the *traversal* itself is cycle-safe regardless,
    per the Phase 8C requirement that malformed state must never hang."""
    local_registry = registry.__class__()
    local_registry.register(_stub_object("X", "ds_cycle", 0, []))
    local_registry.register(_stub_object("Y", "ds_cycle", 1, ["X"]))
    local_registry.register(_stub_object("Z", "ds_cycle", 2, ["Y"]))
    # Corrupt X to point back at Z, forming X -> Y -> Z -> X.
    local_registry._records["X"]["provenance"]["parent_refs"] = [{"object_id": "Z", "relation": "derived_from"}]
    local_registry._child_index.setdefault("Z", []).append("X")

    started = time.perf_counter()
    ancestors_result = local_registry.ancestors("X")
    descendants_result = local_registry.descendants("X")
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0  # terminates - does not hang
    assert ancestors_result is not None and descendants_result is not None
    ancestor_ids = [obj.object_id for obj, _ in ancestors_result.nodes]
    descendant_ids = [obj.object_id for obj, _ in descendants_result.nodes]
    assert len(ancestor_ids) == len(set(ancestor_ids))
    assert len(descendant_ids) == len(set(descendant_ids))
    assert set(ancestor_ids) == {"Z", "Y"}  # X's (corrupted) parent chain, visited once each
    assert set(descendant_ids) == {"Y", "Z"}  # X -> Y -> Z, then Z -> X is already visited


# --- Fingerprint-aware revision identity under traversal --------------------------------


def test_ancestors_never_cross_into_a_different_fingerprint_sharing_the_same_revision_number() -> None:
    branch_a = ensure_dataset_revision(DatasetRef(dataset_id="ds_fp_test", revision=1, source_fingerprint="a" * 64))
    branch_b = ensure_dataset_revision(DatasetRef(dataset_id="ds_fp_test", revision=1, source_fingerprint="b" * 64))
    assert branch_a.object_id != branch_b.object_id

    child = registry.register(_stub_object("fp_child", "ds_fp_test", 2, [branch_a.object_id], fingerprint="a" * 64))

    ancestors = registry.ancestors(child.object_id)
    assert ancestors is not None
    ancestor_ids = {obj.object_id for obj, _ in ancestors.nodes}
    assert branch_a.object_id in ancestor_ids
    assert branch_b.object_id not in ancestor_ids  # same revision number, different fingerprint - never conflated


# --- Immutable snapshots -----------------------------------------------------------------


def test_mutating_a_returned_traversal_payload_never_mutates_registry_state() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    dsrev = _dsrev(dataset_id, 0)

    result = registry.descendants(dsrev.object_id)
    assert result is not None
    first_object, _ = result.nodes[0]
    first_object.payload["injected"] = "should-not-persist"
    first_object.provenance.parent_refs.append(ParentRef(object_id="tampered", relation="derived_from"))

    refetched = registry.descendants(dsrev.object_id)
    assert refetched is not None
    refetched_object, _ = refetched.nodes[0]
    assert "injected" not in refetched_object.payload
    assert "tampered" not in [ref.object_id for ref in refetched_object.provenance.parent_refs]


# --- Partial graph handling ---------------------------------------------------------------


def test_a_parent_ref_pointing_at_an_unregistered_object_is_skipped_not_invented() -> None:
    """Models a process-local registry that only observed history since it started: the
    revision after the one this object is deliberately not present."""
    local_registry = registry.__class__()
    local_registry.register(_stub_object("orphan_child", "ds_partial", 1, ["never_registered_parent"]))

    parents = local_registry.get_parents("orphan_child")
    assert parents == []  # the missing parent is skipped, never fabricated
    ancestors = local_registry.ancestors("orphan_child")
    assert ancestors is not None
    assert ancestors.nodes == []


# --- Security: traversal never bypasses 8A/8B sanitization ------------------------------


def test_secrets_stay_redacted_through_the_ancestors_and_graph_endpoints() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={
            "connection_id": f"local:{dataset_id}",
            "sql": "SELECT * FROM data WHERE segment = $api_key",
            "parameters": {"api_key": "sk-should-not-leak-b"},
        },
    )
    for _ in range(200):
        run = client.get(f"/api/v1/sql-lab/runs/{submitted.json()['run_id']}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    assert run["state"] == "succeeded"

    sql_record = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.QUERY_RESULT)[0]
    dsrev = _dsrev(dataset_id, 0)

    descendants_body = client.get(f"/api/v1/lineage/objects/{dsrev.object_id}/descendants").text
    assert "sk-should-not-leak" not in descendants_body

    graph_body = client.get(f"/api/v1/lineage/objects/{sql_record.object_id}/graph", params={"direction": "both"}).text
    assert "sk-should-not-leak" not in graph_body


# --- Compact graph endpoint ---------------------------------------------------------------


def test_graph_endpoint_includes_the_root_at_depth_zero_and_both_directions() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision0, revision1 = _dsrev(dataset_id, 0), _dsrev(dataset_id, 1)
    stats_r1 = next(r for r in registry.list_for_dataset(dataset_id, revision=1) if r.kind is ObjectKind.ANALYSIS)

    response = client.get(f"/api/v1/lineage/objects/{revision1.object_id}/graph", params={"direction": "both"})
    assert response.status_code == 200
    body = response.json()
    by_id = {node["object"]["object_id"]: node["depth"] for node in body["nodes"]}
    assert by_id[revision1.object_id] == 0  # root included, unlike ancestors/descendants
    assert by_id[revision0.object_id] == 1  # upstream
    assert by_id[stats_r1.object_id] == 1  # downstream


def test_graph_endpoint_upstream_only_omits_downstream_nodes() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision0, revision1 = _dsrev(dataset_id, 0), _dsrev(dataset_id, 1)
    stats_r1 = next(r for r in registry.list_for_dataset(dataset_id, revision=1) if r.kind is ObjectKind.ANALYSIS)

    response = client.get(f"/api/v1/lineage/objects/{revision1.object_id}/graph", params={"direction": "upstream"}).json()
    node_ids = {node["object"]["object_id"] for node in response["nodes"]}
    assert revision0.object_id in node_ids
    assert stats_r1.object_id not in node_ids


def test_graph_endpoint_404s_for_an_unknown_root() -> None:
    client = TestClient(create_app())
    assert client.get("/api/v1/lineage/objects/does-not-exist/graph").status_code == 404


# --- Shortest path -------------------------------------------------------------------------


def test_shortest_path_between_an_analysis_and_its_dataset_revision() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    dsrev = _dsrev(dataset_id, 0)
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    response = client.get("/api/v1/lineage/path", params={"from_object_id": dsrev.object_id, "to_object_id": stats_record.object_id})
    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert [node["object"]["object_id"] for node in body["nodes"]] == [stats_record.object_id]
    assert body["edges"] == [{"parent_object_id": dsrev.object_id, "child_object_id": stats_record.object_id}]


def test_shortest_path_reports_no_path_between_two_disconnected_datasets() -> None:
    client = TestClient(create_app())
    dataset_a = _dataset(client, name="a.csv")
    dataset_b = _dataset(client, name="b.csv")
    client.post(f"/api/v1/stats/datasets/{dataset_a}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    client.post(f"/api/v1/stats/datasets/{dataset_b}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision_a = _dsrev(dataset_a, 0)
    revision_b = _dsrev(dataset_b, 0)

    response = client.get("/api/v1/lineage/path", params={"from_object_id": revision_a.object_id, "to_object_id": revision_b.object_id})
    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["nodes"] == []
    assert body["edges"] == []


def test_shortest_path_404s_when_either_endpoint_is_unknown() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    dsrev = _dsrev(dataset_id, 0)

    response = client.get("/api/v1/lineage/path", params={"from_object_id": dsrev.object_id, "to_object_id": "does-not-exist"})
    assert response.status_code == 404


# --- Regression: existing read-only object retrieval is unchanged -----------------------


def test_existing_object_and_dataset_object_routes_are_unaffected_by_8c() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    dsrev = _dsrev(dataset_id, 0)

    assert client.get(f"/api/v1/lineage/objects/{dsrev.object_id}").status_code == 200
    assert client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects").status_code == 200


# --- Performance sanity at synthetic scale ------------------------------------------------


def test_traversal_stays_fast_on_a_long_chain_and_a_wide_tree() -> None:
    chain_registry = registry.__class__()
    previous_id: str | None = None
    for i in range(1_000):
        object_id = f"chain_{i}"
        chain_registry.register(_stub_object(object_id, "ds_chain_perf", i, [previous_id] if previous_id else []))
        previous_id = object_id

    started = time.perf_counter()
    result = chain_registry.ancestors("chain_999")
    elapsed = time.perf_counter() - started
    assert result is not None
    assert len(result.nodes) == 999
    assert elapsed < 2.0

    wide_registry = registry.__class__()
    wide_registry.register(_stub_object("wide_root", "ds_wide_perf", 0, []))
    for i in range(5_000):
        wide_registry.register(_stub_object(f"wide_child_{i}", "ds_wide_perf", 0, ["wide_root"]))

    # Repeated child lookups stay linear per call (dict lookup + restore), not O(N^2)
    # across calls - 10 repeats of a 5,000-child lookup, not 50, to keep this a sanity
    # bound on algorithmic shape rather than a tight benchmark of pydantic's own
    # per-object restore cost.
    started = time.perf_counter()
    for _ in range(10):
        children = wide_registry.get_children("wide_root")
    elapsed = time.perf_counter() - started
    assert len(children) == 5_000
    assert elapsed < 5.0

    started = time.perf_counter()
    limited = wide_registry.descendants("wide_root", max_depth=1)
    elapsed = time.perf_counter() - started
    assert limited is not None
    assert len(limited.nodes) == 5_000
    assert limited.truncated is False
    assert elapsed < 2.0
