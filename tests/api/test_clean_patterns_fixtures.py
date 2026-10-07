"""Acceptance tests against the documented business/scientific fixtures. Every
assertion here corresponds to a declared fact in
docs/clean-pattern-review-v1/fixtures/README.md - verified before being written
down, not tuned afterward to match whatever the code happened to produce.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from prism_api.main import create_app

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "clean-pattern-review-v1" / "fixtures"


def _upload(client: TestClient, filename: str) -> str:
    content = (FIXTURES / filename).read_bytes()
    response = client.post("/api/v1/overview/datasets", files={"file": (filename, content, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_business_fixture_shape() -> None:
    client = TestClient(create_app())
    dataset_id = _upload(client, "business-invoices.csv")
    profile = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]
    assert profile["row_count"] == 9
    assert profile["column_count"] == 5


def test_business_fixture_invoice_id_two_legitimate_families_and_one_exception() -> None:
    client = TestClient(create_app())
    dataset_id = _upload(client, "business-invoices.csv")
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    finding = next(f for f in findings if f["column"] == "invoice_id" and f["detector_kind"] == "identifier_structure")
    families = {fam["family_signature"]: fam["matching_count"] for fam in finding["families"]}
    assert families == {"L3-N6": 5, "L2-N4-N3": 2}
    assert finding["exception_count"] == 1
    assert finding["exception_examples"] == ["AB12"]
    assert finding["missing_count"] == 1


def test_business_fixture_order_date_ambiguity_includes_the_easy_to_miss_case() -> None:
    client = TestClient(create_app())
    dataset_id = _upload(client, "business-invoices.csv")
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    finding = next(f for f in findings if f["column"] == "order_date" and f["detector_kind"] == "date_ambiguity")
    examples = set(finding["families"][0]["example_values"])
    assert examples == {"01/01/2026", "01/02/2026", "02/02/2026", "05/12/2026"}
    assert "05/12/2026" in examples  # 12 <= 12: ambiguous too, not just values with both components < 10


def test_business_fixture_group_scoped_discovery_isolates_the_DE_convention() -> None:
    client = TestClient(create_app())
    dataset_id = _upload(client, "business-invoices.csv")
    scoped = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/invoice_id/scan", json={
        "column": "invoice_id", "detector_kind": "identifier_structure", "group_by_column": "country", "group_value": "DE",
    }).json()
    assert len(scoped) == 1
    assert scoped[0]["families"] == [{"family_signature": "L2-N4-N3", "label": "2 letters, '-', 4 digits, '-', 3 digits", "matching_count": 2, "example_values": ["RE-2024-001", "RE-2024-002"]}]


def test_business_fixture_supplier_name_produces_no_findings() -> None:
    """Similar names, different entities: no v1 detector attempts entity resolution."""
    client = TestClient(create_app())
    dataset_id = _upload(client, "business-invoices.csv")
    scanned = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/columns/supplier_name/scan", json={"column": "supplier_name"}).json()
    assert scanned == []


def test_scientific_fixture_shape() -> None:
    client = TestClient(create_app())
    dataset_id = _upload(client, "scientific-measurements.csv")
    profile = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]
    assert profile["row_count"] == 8
    assert profile["column_count"] == 3


def test_scientific_fixture_units_never_merge_and_detection_limit_is_distinct() -> None:
    client = TestClient(create_app())
    dataset_id = _upload(client, "scientific-measurements.csv")
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    finding = next(f for f in findings if f["column"] == "measurement" and f["detector_kind"] == "numeric_unit")
    assert finding["families"] == [{"family_signature": "unit:kg", "label": "a plain value with unit 'kg'", "matching_count": 4, "example_values": ["10.5 kg", "20 kg", "15.2 kg", "18.0 kg"]}]
    assert set(finding["exception_examples"]) == {"<0.05 kg", "99 lb", "invalid", "2.1 mg"}
    assert finding["exception_source_rows"] == ["2", "3", "4", "7"]


def test_scientific_fixture_invalid_text_reaches_exceptions_instead_of_vanishing() -> None:
    client = TestClient(create_app())
    dataset_id = _upload(client, "scientific-measurements.csv")
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    finding = next(f for f in findings if f["column"] == "measurement" and f["detector_kind"] == "numeric_unit")
    assert "invalid" in finding["exception_examples"]


def test_scientific_fixture_impossible_date_is_a_documented_boundary_not_a_crash() -> None:
    """31/02/2026 (day 31 in February) is not calendar-valid, but date_ambiguity only
    checks day/month-order plausibility (both components <= 12), not calendar
    validity - see docs/clean-pattern-review-v1/fixtures/README.md. This test
    documents the real, current boundary so a future change to that scope is a
    deliberate decision, not an accidental regression discovered in production."""
    client = TestClient(create_app())
    dataset_id = _upload(client, "scientific-measurements.csv")
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    finding = next((f for f in findings if f["column"] == "observed_at" and f["detector_kind"] == "date_ambiguity"), None)
    assert finding is not None
    assert "31/02/2026" not in finding["families"][0]["example_values"]
    assert finding["families"][0]["example_values"] == ["03/04/2026"]


def test_scientific_fixture_consistent_rare_format_is_one_legitimate_family_not_an_error() -> None:
    client = TestClient(create_app())
    dataset_id = _upload(client, "scientific-measurements.csv")
    findings = client.post(f"/api/v1/clean/datasets/{dataset_id}/patterns/discover").json()
    finding = next(f for f in findings if f["column"] == "sample_id" and f["detector_kind"] == "identifier_structure")
    assert finding["families"] == [{"family_signature": "L1-N3", "label": "1 letter, '-', 3 digits", "matching_count": 8, "example_values": ["S-001", "S-002", "S-003", "S-004", "S-005"]}]
    assert finding["exception_count"] == 0
