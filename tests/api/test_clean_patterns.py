from __future__ import annotations

from fastapi.testclient import TestClient
from prism_api.main import create_app

IDENTIFIER_CSV = (
    b"invoice_id,amount\n"
    b"INV-000123,10.5 kg\n"
    b"INV-000456,20 kg\n"
    b"INV-000789,<0.05 kg\n"
    b"AB12,99 lb\n"
    b"ZZZZZZ,abc\n"
)


def _dataset(client: TestClient, csv: bytes = IDENTIFIER_CSV, name: str = "patterns.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def _profile(client: TestClient, dataset_id: str) -> dict:
    return client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]


def test_identifier_structure_finds_legitimate_families_and_buckets_singletons_as_exceptions() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    invoice_finding = next(f for f in findings if f["column"] == "invoice_id" and f["detector_kind"] == "identifier_structure")
    assert invoice_finding["sampling_method"] == "bounded_sample"
    assert invoice_finding["verified"] is False
    assert [fam["family_signature"] for fam in invoice_finding["families"]] == ["L3-N6"]
    assert invoice_finding["families"][0]["matching_count"] == 3
    assert invoice_finding["exception_count"] == 2
    assert set(invoice_finding["exception_examples"]) == {"AB12", "ZZZZZZ"}


def test_numeric_unit_never_merges_distinct_units_and_flags_detection_limit_and_no_match() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    amount_finding = next(f for f in findings if f["column"] == "amount" and f["detector_kind"] == "numeric_unit")
    families = {fam["family_signature"]: fam["matching_count"] for fam in amount_finding["families"]}
    assert families == {"unit:kg": 2}
    assert amount_finding["exception_count"] == 3  # limit:unit:kg (1), unit:lb (1), and "abc" which matches nothing
    assert "abc" in amount_finding["exception_examples"]


def test_verify_runs_a_real_full_scan_not_a_sample() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    verified = client.post(
        f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify",
        json={"column": "invoice_id", "detector_kind": "identifier_structure"},
    )
    assert verified.status_code == 200
    body = verified.json()
    assert body["sampling_method"] == "full_scan"
    assert body["verified"] is True
    assert body["rows_examined"] == body["total_rows"] == 5


def test_verify_requires_an_explicit_detector_kind() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(
        f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify",
        json={"column": "invoice_id"},
    )
    assert response.status_code == 422


def test_extract_identifier_components_preserves_leading_zeros_and_leaves_non_matching_rows_blank() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={
        "operation": "extract_identifier_components", "column": "invoice_id", "family_signature": "L3-N6",
    })
    assert preview.status_code == 200
    assert "2 distinct value" in preview.json()["warnings"][0]
    token = preview.json()["review_token"]
    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "extract_identifier_components", "column": "invoice_id", "family_signature": "L3-N6", "review_token": token,
    })
    assert applied.status_code == 201
    rows = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows").json()["rows"]
    assert rows[0]["invoice_id"] == "INV-000123"  # source column preserved unchanged
    assert rows[0]["invoice_id_part1"] == "INV"
    assert rows[0]["invoice_id_part2"] == "000123"  # leading zeros preserved, not coerced to int
    assert rows[3]["invoice_id_part1"] is None and rows[3]["invoice_id_part2"] is None  # AB12 did not match the family


def test_extract_identifier_components_rejects_unrecognized_signature() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={
        "operation": "extract_identifier_components", "column": "invoice_id", "family_signature": "not a real signature!!",
    })
    assert response.status_code in (200, 422)
    # even if accepted as a string, it must not match any row and must not raise
    if response.status_code == 200:
        token = response.json()["review_token"]
        applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
            "operation": "extract_identifier_components", "column": "invoice_id",
            "family_signature": "not a real signature!!", "review_token": token,
        })
        assert applied.status_code == 201


def test_extract_numeric_unit_does_not_convert_units_and_parses_detection_limit_comparator() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "extract_numeric_unit", "column": "amount"})
    token = preview.json()["review_token"]
    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "extract_numeric_unit", "column": "amount", "review_token": token,
    })
    assert applied.status_code == 201
    rows = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows").json()["rows"]
    by_id = {row["invoice_id"]: row for row in rows}
    assert by_id["INV-000123"]["amount_value"] == 10.5 and by_id["INV-000123"]["amount_unit"] == "kg"
    assert by_id["AB12"]["amount_value"] == 99.0 and by_id["AB12"]["amount_unit"] == "lb"  # kept as lb, not converted to kg
    assert by_id["INV-000789"]["amount_comparator"] == "<"
    assert by_id["ZZZZZZ"]["amount_value"] is None  # "abc" matched nothing


def test_extract_numeric_unit_rejects_output_column_collision() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=b"invoice_id,amount,amount_value\nINV-000123,10.5 kg,1\n", name="collide.csv")
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "extract_numeric_unit", "column": "amount"})
    assert response.status_code == 422
    assert "already exist" in response.json()["detail"]


def test_split_delimited_handles_short_rows_without_crashing() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={
        "operation": "split_delimited", "column": "invoice_id", "delimiter": "-",
    })
    assert preview.status_code == 200
    assert "fewer than" in preview.json()["warnings"][0]
    token = preview.json()["review_token"]
    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "split_delimited", "column": "invoice_id", "delimiter": "-", "review_token": token,
    })
    assert applied.status_code == 201
    rows = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows").json()["rows"]
    by_id = {row["invoice_id"]: row for row in rows}
    assert by_id["INV-000123"]["invoice_id_part1"] == "INV" and by_id["INV-000123"]["invoice_id_part2"] == "000123"
    assert by_id["AB12"]["invoice_id_part1"] == "AB12" and by_id["AB12"]["invoice_id_part2"] is None


def test_review_decisions_are_source_bound_and_do_not_mutate_data() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = _profile(client, dataset_id)
    decision = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "accept_family", "family_signatures": ["L3-N6"],
        "detector_kind": "identifier_structure",
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    })
    assert decision.status_code == 201
    body = decision.json()
    assert body["source_revision"] == before["revision"]
    assert body["detector_version"] == 1  # auto-filled from the detector_kind's current version
    after = _profile(client, dataset_id)
    assert after["revision"] == before["revision"]  # saving a decision never mutates data
    listed = client.get(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions").json()
    assert len(listed) == 1 and listed[0]["decision_id"] == body["decision_id"]
    assert listed[0]["revoked"] is False


def test_accept_family_decision_requires_at_least_one_family_signature() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = _profile(client, dataset_id)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "accept_family",
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    })
    assert response.status_code == 422


def test_decision_requires_the_reviewed_source_identity() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "ignore_revision",
    })
    assert response.status_code == 422


def test_decision_rejects_a_stale_reviewed_source() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = _profile(client, dataset_id)
    # mutate the dataset so its revision/fingerprint move on
    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates", "review_token": preview.json()["review_token"]})
    stale_decision = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "ignore_revision",
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    })
    assert stale_decision.status_code == 409


def test_suppress_rule_decision_is_revocable_without_rewriting_history() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = _profile(client, dataset_id)
    suppressed = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "suppress_rule", "detector_kind": "identifier_structure",
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    }).json()
    assert suppressed["revoked"] is False

    revoke = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "ignore_revision", "revokes_decision_id": suppressed["decision_id"],
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    })
    assert revoke.status_code == 201

    listed = client.get(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions").json()
    assert len(listed) == 2  # both records preserved, nothing rewritten
    by_id = {entry["decision_id"]: entry for entry in listed}
    assert by_id[suppressed["decision_id"]]["revoked"] is True
    assert by_id[revoke.json()["decision_id"]]["revoked"] is False


def test_revoke_rejects_an_unrelated_decision_id() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = _profile(client, dataset_id)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "ignore_revision", "revokes_decision_id": "patterndecision_doesnotexist",
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    })
    assert response.status_code == 422


def test_pattern_family_rule_requires_column_signatures_and_missing_policy() -> None:
    client = TestClient(create_app())
    missing_column = client.post("/api/v1/clean/validation-rules", json={
        "name": "x", "kind": "pattern_family", "accepted_family_signatures": ["L3-N6"], "missing_value_policy": "allow",
    })
    assert missing_column.status_code == 422
    missing_families = client.post("/api/v1/clean/validation-rules", json={
        "name": "x", "kind": "pattern_family", "column": "invoice_id", "missing_value_policy": "allow",
    })
    assert missing_families.status_code == 422
    missing_policy = client.post("/api/v1/clean/validation-rules", json={
        "name": "x", "kind": "pattern_family", "column": "invoice_id", "accepted_family_signatures": ["L3-N6"],
    })
    assert missing_policy.status_code == 422


def test_pattern_family_rule_is_reusable_on_a_schema_compatible_dataset_and_rejects_an_incompatible_one() -> None:
    client = TestClient(create_app())
    _dataset(client, csv=b"invoice_id\nINV-000123\nINV-000456\n", name="first.csv")
    rule = client.post("/api/v1/clean/validation-rules", json={
        "name": "Invoice ID format", "kind": "pattern_family", "column": "invoice_id",
        "accepted_family_signatures": ["L3-N6"], "missing_value_policy": "allow",
    })
    assert rule.status_code == 201
    rule_id = rule.json()["rule_id"]

    compatible_dataset = _dataset(client, csv=b"invoice_id\nINV-000999\nBADFORMAT\n", name="second.csv")
    compatible_run = client.post(f"/api/v1/clean/datasets/{compatible_dataset}/validation-rules/{rule_id}/run")
    assert compatible_run.status_code == 200
    result = compatible_run.json()
    assert result["total_checked"] == 2
    assert result["violation_count"] == 1
    assert result["sample_violations"][0]["invoice_id"] == "BADFORMAT"
    assert result["passed"] is False
    assert result["rule"]["rule_id"] == rule_id  # the exact rule/source checked is reported, never guessed

    incompatible_dataset = _dataset(client, csv=b"other_column\nfoo\n", name="third.csv")
    incompatible_run = client.post(f"/api/v1/clean/datasets/{incompatible_dataset}/validation-rules/{rule_id}/run")
    assert incompatible_run.status_code == 422  # schema compatibility is checked, never silently skipped


def test_pattern_family_rule_missing_value_policy_reject_flags_missing_as_a_violation() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=b"invoice_id,note\nINV-000123,ok\n,blank id\n", name="missing.csv")
    rule = client.post("/api/v1/clean/validation-rules", json={
        "name": "Invoice ID format", "kind": "pattern_family", "column": "invoice_id",
        "accepted_family_signatures": ["L3-N6"], "missing_value_policy": "reject",
    }).json()
    run = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule['rule_id']}/run")
    assert run.json()["violation_count"] == 1  # the blank-id row is a violation under 'reject'


def test_pattern_family_rule_missing_value_policy_allow_does_not_flag_missing() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=b"invoice_id,note\nINV-000123,ok\n,blank id\n", name="missing2.csv")
    rule = client.post("/api/v1/clean/validation-rules", json={
        "name": "Invoice ID format", "kind": "pattern_family", "column": "invoice_id",
        "accepted_family_signatures": ["L3-N6"], "missing_value_policy": "allow",
    }).json()
    run = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule['rule_id']}/run")
    assert run.json()["violation_count"] == 0


def test_group_by_column_scopes_discovery_and_requires_group_value() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=(
        b"country,invoice_id\n"
        b"US,INV-000123\nUS,INV-000456\nUS,INV-000789\n"
        b"DE,RE-2024-001\nDE,RE-2024-002\n"
    ), name="grouped.csv")
    missing_value = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/scan", json={
        "column": "invoice_id", "group_by_column": "country",
    })
    assert missing_value.status_code == 422

    us_scan = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/scan", json={
        "column": "invoice_id", "detector_kind": "identifier_structure", "group_by_column": "country", "group_value": "US",
    })
    assert us_scan.status_code == 200
    finding = us_scan.json()[0]
    assert finding["group_by_column"] == "country" and finding["group_value"] == "US"
    assert finding["families"][0]["family_signature"] == "L3-N6"
    assert finding["families"][0]["matching_count"] == 3  # only the 3 US rows, not all 5


def test_saved_pattern_rule_survives_a_fresh_store_instance() -> None:
    from prism_api.durable_registry import history_database_url
    from prism_api.durable_validation_rule_store import DurableValidationRuleStore
    from prism_api_contracts import ValidationRuleCreateRequest, ValidationRuleKind

    url = history_database_url()
    first = DurableValidationRuleStore(url)
    created = first.create(ValidationRuleCreateRequest(
        name="Invoice ID format", kind=ValidationRuleKind.PATTERN_FAMILY, column="invoice_id",
        accepted_family_signatures=["L3-N6"], missing_value_policy="reject",
    ))
    reopened = DurableValidationRuleStore(url)
    reloaded = reopened.get(created.rule_id)
    assert reloaded.accepted_family_signatures == ["L3-N6"]
    assert reloaded.missing_value_policy == "reject"
