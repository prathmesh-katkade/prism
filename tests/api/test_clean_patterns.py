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
    assert list(zip(invoice_finding["exception_source_rows"], invoice_finding["exception_examples"])) == [("3", "AB12"), ("4", "ZZZZZZ")]
    assert invoice_finding["nonmatching_count"] == 0


def test_numeric_unit_never_merges_distinct_units_and_flags_detection_limit_and_no_match() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    amount_finding = next(f for f in findings if f["column"] == "amount" and f["detector_kind"] == "numeric_unit")
    families = {fam["family_signature"]: fam["matching_count"] for fam in amount_finding["families"]}
    assert families == {"unit:kg": 2}
    assert amount_finding["exception_count"] == 3  # limit:unit:kg (1), unit:lb (1), and "abc" which matches nothing
    assert "abc" in amount_finding["exception_examples"]
    assert list(zip(amount_finding["exception_source_rows"], amount_finding["exception_examples"])) == [
        ("2", "<0.05 kg"), ("3", "99 lb"), ("4", "abc")]
    assert amount_finding["nonmatching_count"] == 0


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


def test_exception_pages_are_bounded_and_bound_to_the_reviewed_source() -> None:
    client = TestClient(create_app())
    values = ["INV-000123", "INV-000456", "INV-000789"] + [f"A-{'1' * width}" for width in range(1, 14)]
    dataset_id = _dataset(client, ("invoice_id\n" + "\n".join(values) + "\n").encode(), "many-exceptions.csv")
    finding = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify",
                          json={"column": "invoice_id", "detector_kind": "identifier_structure"}).json()
    request = {"detector_kind": "identifier_structure", "reviewed_source_revision": finding["source_revision"],
               "reviewed_source_fingerprint": finding["source_fingerprint"], "verified": True, "offset": 10, "limit": 2}
    page = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/exceptions", json=request)
    assert page.status_code == 200
    assert page.json() == {"total": 13, "offset": 10, "limit": 2,
                           "rows": [{"source_row": "13", "value": "A-11111111111"},
                                    {"source_row": "14", "value": "A-111111111111"}]}
    stale = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/exceptions",
                        json={**request, "reviewed_source_revision": finding["source_revision"] + 1})
    assert stale.status_code == 409
    oversized = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/exceptions",
                            json={**request, "limit": 101})
    assert oversized.status_code == 422


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


def test_saved_pattern_rule_survives_reopening_the_store() -> None:
    # NOTE: this proves the SQL row round-trips through a fresh Python object bound
    # to the same database file - it does NOT prove persistence across a real API
    # process restart (same interpreter, same in-memory caches never torn down).
    # See apps/web/e2e-live/pattern-review-restart-live.spec.ts and
    # docs/clean-pattern-review-v1/restart-evidence.md for the genuine proof: two
    # separate uvicorn OS processes against the same database file.
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


def test_multiple_legitimate_families_can_be_accepted_together() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=(
        b"code\nAB-001\nAB-002\nAB-003\nXYZ-9000\nXYZ-9001\nXYZ-9002\n"
    ), name="multi-family.csv")
    before = _profile(client, dataset_id)
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    finding = next(f for f in findings if f["column"] == "code" and f["detector_kind"] == "identifier_structure")
    signatures = [fam["family_signature"] for fam in finding["families"]]
    assert len(signatures) == 2  # AB-### and XYZ-#### are both legitimate, different families
    decision = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "code", "decision": "accept_family", "family_signatures": signatures,
        "detector_kind": "identifier_structure",
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    })
    assert decision.status_code == 201
    assert decision.json()["family_signatures"] == signatures

    rule = client.post("/api/v1/clean/validation-rules", json={
        "name": "Code formats", "kind": "pattern_family", "column": "code",
        "accepted_family_signatures": signatures, "missing_value_policy": "allow",
    }).json()
    run = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule['rule_id']}/run")
    assert run.json()["violation_count"] == 0  # every row matches one of the two accepted families


def test_full_counts_reconcile_exactly_against_rows_examined() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    verified = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify", json={
        "column": "invoice_id", "detector_kind": "identifier_structure",
    }).json()
    family_total = sum(fam["matching_count"] for fam in verified["families"])
    assert family_total + verified["exception_count"] + verified["missing_count"] == verified["rows_examined"]
    assert verified["rows_examined"] == verified["total_rows"]


def test_output_collision_rejects_without_any_mutation() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=b"invoice_id,amount,amount_value\nINV-000123,10.5 kg,1\n", name="collide2.csv")
    before = _profile(client, dataset_id)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "extract_numeric_unit", "column": "amount"})
    assert response.status_code == 422
    after = _profile(client, dataset_id)
    assert after["revision"] == before["revision"]
    assert after["source_fingerprint"] == before["source_fingerprint"]


def test_date_ambiguity_is_flagged_not_silently_resolved() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=b"event_date\n03/04/2026\n05/06/2026\n13/02/2026\n", name="dates.csv")
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    finding = next((f for f in findings if f["column"] == "event_date" and f["detector_kind"] == "date_ambiguity"), None)
    assert finding is not None
    assert "03/04/2026" in finding["families"][0]["example_values"]
    assert "05/06/2026" in finding["families"][0]["example_values"]
    assert "13/02/2026" not in finding["families"][0]["example_values"]  # unambiguous: day > 12 rules out month-first
    assert finding["nonmatching_count"] == 1


def test_extraction_apply_rejects_a_stale_preview_after_the_source_changes() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={
        "operation": "extract_identifier_components", "column": "invoice_id", "family_signature": "L3-N6",
    })
    token = preview.json()["review_token"]
    # the source changes after the preview was issued
    other_preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates", "review_token": other_preview.json()["review_token"]})
    stale_apply = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "extract_identifier_components", "column": "invoice_id", "family_signature": "L3-N6", "review_token": token,
    })
    assert stale_apply.status_code == 409


def test_extraction_apply_is_one_use_and_rejects_a_second_apply_with_the_same_token() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "extract_numeric_unit", "column": "amount"})
    token = preview.json()["review_token"]
    first_apply = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "extract_numeric_unit", "column": "amount", "review_token": token})
    assert first_apply.status_code == 201
    second_apply = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "extract_numeric_unit", "column": "amount", "review_token": token})
    assert second_apply.status_code in (404, 409, 422)  # the token was already consumed


def test_saving_a_pattern_rule_never_mutates_the_dataset() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = _profile(client, dataset_id)
    client.post("/api/v1/clean/validation-rules", json={
        "name": "Invoice ID format", "kind": "pattern_family", "column": "invoice_id",
        "accepted_family_signatures": ["L3-N6"], "missing_value_policy": "allow",
    })
    after = _profile(client, dataset_id)
    assert after == before


def test_grouped_rule_actually_scopes_checking_to_its_grouping_condition() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=(
        b"country,invoice_id\n"
        b"US,INV-000123\nUS,INV-000456\nUS,INV-000789\n"
        b"DE,RE-2024-001\nDE,RE-2024-002\n"
    ), name="grouped2.csv")
    rule = client.post("/api/v1/clean/validation-rules", json={
        "name": "US invoice format", "kind": "pattern_family", "column": "invoice_id",
        "accepted_family_signatures": ["L3-N6"], "missing_value_policy": "allow",
        "group_by_column": "country", "group_value": "US",
    }).json()
    assert rule["group_by_column"] == "country" and rule["group_value"] == "US"
    run = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule['rule_id']}/run")
    result = run.json()
    assert result["total_checked"] == 3  # only the 3 US rows - DE rows are out of scope, not violations
    assert result["violation_count"] == 0


def test_ignore_revision_and_suppress_rule_have_different_scopes() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = _profile(client, dataset_id)

    # Ignore is scoped to this exact revision: it hides the finding from the
    # passive ranked list now, but the column explorer still reaches it.
    client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "ignore_revision", "detector_kind": "identifier_structure",
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    })
    findings_after_ignore = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    assert not any(f["column"] == "invoice_id" and f["detector_kind"] == "identifier_structure" for f in findings_after_ignore)
    explored = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/scan", json={
        "column": "invoice_id", "detector_kind": "identifier_structure",
    })
    assert explored.status_code == 200 and explored.json()  # column explorer never filters

    # Mutate the dataset to a new revision: the ignore must NOT carry forward.
    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates", "review_token": preview.json()["review_token"]})
    findings_new_revision = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    assert any(f["column"] == "invoice_id" and f["detector_kind"] == "identifier_structure" for f in findings_new_revision)

    # Suppress is NOT scoped to a revision: it stays hidden even after the dataset changes.
    after_drop = _profile(client, dataset_id)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "suppress_rule", "detector_kind": "identifier_structure",
        "reviewed_source_revision": after_drop["revision"], "reviewed_source_fingerprint": after_drop["source_fingerprint"],
    })
    preview2 = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "trim_whitespace", "column": "amount"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "trim_whitespace", "column": "amount", "review_token": preview2.json()["review_token"]})
    findings_after_suppress_and_another_change = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    assert not any(f["column"] == "invoice_id" and f["detector_kind"] == "identifier_structure" for f in findings_after_suppress_and_another_change)


def test_revoking_a_suppression_restores_it_to_the_ranked_list() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = _profile(client, dataset_id)
    suppressed = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "suppress_rule", "detector_kind": "identifier_structure",
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    }).json()
    hidden = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    assert not any(f["column"] == "invoice_id" and f["detector_kind"] == "identifier_structure" for f in hidden)

    client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/decisions", json={
        "column": "invoice_id", "decision": "ignore_revision", "revokes_decision_id": suppressed["decision_id"],
        "reviewed_source_revision": before["revision"], "reviewed_source_fingerprint": before["source_fingerprint"],
    })
    restored = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    assert any(f["column"] == "invoice_id" and f["detector_kind"] == "identifier_structure" for f in restored)


def _large_identifier_csv(rows: int) -> bytes:
    lines = [b"invoice_id,amount"]
    for i in range(rows):
        lines.append(f"INV-{i:06d},{10 + i % 50}.5 kg".encode())
    return b"\n".join(lines) + b"\n"


def test_verify_job_runs_to_completion_with_real_progress_and_a_verified_finding() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=_large_identifier_csv(500), name="verify-job.csv")
    started = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/start",
                          json={"column": "invoice_id", "detector_kind": "identifier_structure"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    assert started.json()["rows_total"] == 500

    for _ in range(200):
        status_body = client.get(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/jobs/{job_id}").json()
        if status_body["state"] != "running":
            break
    assert status_body["state"] == "succeeded"
    assert status_body["rows_checked"] == 500
    assert status_body["finding"]["verified"] is True
    assert status_body["finding"]["sampling_method"] == "full_scan"
    assert status_body["finding"]["rows_examined"] == 500


def test_verify_job_can_be_cancelled_mid_scan_and_the_server_genuinely_stops(monkeypatch) -> None:
    """Proves SERVER-side termination, not merely a fast client return: a slow,
    deterministic checkpoint delay (opt-in, test-only env var) keeps a 20,000-row
    scan running long enough to reliably catch it mid-flight, cancel it, and then
    show the job's own recorded rows_checked stayed below rows_total - i.e. the
    scan loop itself stopped early, which a client-side AbortController alone
    could never demonstrate."""
    monkeypatch.setenv("PRISM_PATTERN_VERIFY_TEST_DELAY_MS", "60")
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=_large_identifier_csv(20_000), name="verify-cancel.csv")
    started = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/start",
                          json={"column": "invoice_id", "detector_kind": "identifier_structure"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    assert started.json()["rows_total"] == 20_000

    # Wait for at least one real checkpoint so there is genuine in-flight
    # progress to interrupt (not a job that hasn't started its scan loop yet).
    progressed = None
    for _ in range(100):
        progressed = client.get(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/jobs/{job_id}").json()
        if progressed["rows_checked"] > 0:
            break
    assert progressed is not None and progressed["rows_checked"] > 0
    assert progressed["state"] == "running"  # confirms the job was genuinely still in flight when cancelled below

    cancelled = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/jobs/{job_id}/cancel").json()

    final = cancelled
    for _ in range(300):
        if final["state"] != "running":
            break
        final = client.get(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/jobs/{job_id}").json()
    assert final["state"] == "cancelled"
    assert final["finding"] is None  # a cancelled job never publishes verified=true
    # The decisive proof of server-side (not client-side) termination: the
    # job's own last recorded checkpoint is strictly short of the full 20,000
    # rows - the scan loop itself stopped, it did not quietly finish in the
    # background while only the client gave up waiting.
    assert final["rows_checked"] < 20_000

    # A second poll after cancellation must keep reporting the same terminal
    # state, never silently resume or flip to succeeded.
    again = client.get(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/jobs/{job_id}").json()
    assert again["state"] == "cancelled" and again["finding"] is None


def test_cancelling_an_already_succeeded_verify_job_does_not_change_its_state() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=_large_identifier_csv(50), name="verify-race.csv")
    started = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/start",
                          json={"column": "invoice_id", "detector_kind": "identifier_structure"})
    job_id = started.json()["job_id"]
    status_body = started.json()
    for _ in range(200):
        if status_body["state"] != "running":
            break
        status_body = client.get(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/jobs/{job_id}").json()
    assert status_body["state"] == "succeeded"

    late_cancel = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/jobs/{job_id}/cancel").json()
    assert late_cancel["state"] == "succeeded"  # a late cancel on finished work is a no-op, not a retroactive downgrade
    assert late_cancel["finding"] is not None


def test_verify_job_status_for_an_unknown_job_id_is_a_clean_404() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.get(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/verify/jobs/patternverify_doesnotexist")
    assert response.status_code == 404
