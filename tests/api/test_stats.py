from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from prism_api.main import create_app

from modules import stats_lab as legacy_stats_lab

# Two numeric columns, weakly correlated by construction — exercises Pearson.
NUMERIC_CSV = (
    b"x,y\n" + b"".join(f"{i},{i * 2 + (i % 3)}\n".encode() for i in range(1, 41))
)

# One numeric outcome ("score"), one 2-level categorical ("group") — exercises t-test.
TWO_GROUP_CSV = (
    b"score,group\n"
    + b"".join(f"{70 + (i % 5)},a\n".encode() for i in range(20))
    + b"".join(f"{85 + (i % 5)},b\n".encode() for i in range(20))
)

# One numeric outcome, one 3-level categorical — exercises ANOVA.
THREE_GROUP_CSV = (
    b"score,group\n"
    + b"".join(f"{50 + (i % 4)},a\n".encode() for i in range(15))
    + b"".join(f"{60 + (i % 4)},b\n".encode() for i in range(15))
    + b"".join(f"{70 + (i % 4)},c\n".encode() for i in range(15))
)

# Two categorical columns with an intentional association — exercises chi-square.
CHI2_CSV = (
    b"segment,plan\n"
    + b"".join(b"enterprise,premium\n" for _ in range(30))
    + b"".join(b"enterprise,basic\n" for _ in range(5))
    + b"".join(b"startup,basic\n" for _ in range(30))
    + b"".join(b"startup,premium\n" for _ in range(5))
)


def _dataset(client: TestClient, csv: bytes, name: str = "stats.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def _legacy_frame(csv: bytes) -> pd.DataFrame:
    import io

    return pd.read_csv(io.BytesIO(csv))


# --- suggestion engine: deterministic, dtype-driven --------------------------------


def test_suggest_test_recommends_pearson_for_two_numeric_columns() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, NUMERIC_CSV)
    response = client.get(f"/api/v1/stats/datasets/{dataset_id}/suggest", params={"column_a": "x", "column_b": "y"})
    assert response.status_code == 200
    body = response.json()
    assert body["test"] == "pearson"
    assert body["error"] is None


def test_suggest_test_recommends_ttest_for_one_numeric_one_two_level_categorical() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, TWO_GROUP_CSV)
    response = client.get(f"/api/v1/stats/datasets/{dataset_id}/suggest", params={"column_a": "score", "column_b": "group"})
    body = response.json()
    assert body["test"] == "ttest"
    assert body["numeric_col"] == "score"
    assert body["cat_col"] == "group"


def test_suggest_test_recommends_anova_for_one_numeric_one_multi_level_categorical() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, THREE_GROUP_CSV)
    response = client.get(f"/api/v1/stats/datasets/{dataset_id}/suggest", params={"column_a": "score", "column_b": "group"})
    body = response.json()
    assert body["test"] == "anova"


def test_suggest_test_recommends_chi_square_for_two_categorical_columns() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CHI2_CSV)
    response = client.get(f"/api/v1/stats/datasets/{dataset_id}/suggest", params={"column_a": "segment", "column_b": "plan"})
    body = response.json()
    assert body["test"] == "chi2"


def test_suggest_test_rejects_a_column_not_in_the_active_dataset() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, NUMERIC_CSV)
    response = client.get(f"/api/v1/stats/datasets/{dataset_id}/suggest", params={"column_a": "x", "column_b": "does_not_exist"})
    assert response.status_code == 422


# --- direct parity against modules/stats_lab.py -------------------------------------


def test_run_test_pearson_matches_legacy_stats_lab_on_a_fixture() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, NUMERIC_CSV)
    response = client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    assert response.status_code == 200
    native = response.json()

    legacy = legacy_stats_lab.run_pearson(_legacy_frame(NUMERIC_CSV), "x", "y")

    assert native["statistic"] == pytest.approx(legacy["statistic"], abs=1e-9)
    assert native["p_value"] == pytest.approx(legacy["p_value"], abs=1e-9)
    assert native["effect_size"] == pytest.approx(legacy["effect_size"], abs=1e-9)
    assert native["effect_size_label"] == legacy["effect_size_label"]
    assert native["n"] == legacy["n"]


def test_run_test_ttest_matches_legacy_stats_lab_on_a_fixture() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, TWO_GROUP_CSV)
    response = client.post(
        f"/api/v1/stats/datasets/{dataset_id}/run",
        json={"test": "ttest", "col_a": "score", "col_b": "group", "numeric_col": "score", "cat_col": "group"},
    )
    assert response.status_code == 200
    native = response.json()

    legacy = legacy_stats_lab.run_ttest(_legacy_frame(TWO_GROUP_CSV), "score", "group")

    assert native["statistic"] == pytest.approx(legacy["statistic"], abs=1e-9)
    assert native["p_value"] == pytest.approx(legacy["p_value"], abs=1e-9)
    assert native["effect_size"] == pytest.approx(legacy["effect_size"], abs=1e-9)
    assert native["groups"] == legacy["groups"]
    assert native["means"] == pytest.approx(legacy["means"], abs=1e-9)


def test_run_test_anova_matches_legacy_stats_lab_on_a_fixture() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, THREE_GROUP_CSV)
    response = client.post(
        f"/api/v1/stats/datasets/{dataset_id}/run",
        json={"test": "anova", "col_a": "score", "col_b": "group", "numeric_col": "score", "cat_col": "group"},
    )
    assert response.status_code == 200
    native = response.json()

    legacy = legacy_stats_lab.run_anova(_legacy_frame(THREE_GROUP_CSV), "score", "group")

    assert native["statistic"] == pytest.approx(legacy["statistic"], abs=1e-9)
    assert native["p_value"] == pytest.approx(legacy["p_value"], abs=1e-9)
    assert native["effect_size"] == pytest.approx(legacy["effect_size"], abs=1e-6)


def test_run_test_chi_square_matches_legacy_stats_lab_on_a_fixture() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CHI2_CSV)
    response = client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "chi2", "col_a": "segment", "col_b": "plan"})
    assert response.status_code == 200
    native = response.json()

    legacy = legacy_stats_lab.run_chi2(_legacy_frame(CHI2_CSV), "segment", "plan")

    assert native["statistic"] == pytest.approx(legacy["statistic"], abs=1e-9)
    assert native["p_value"] == pytest.approx(legacy["p_value"], abs=1e-9)
    assert native["dof"] == legacy["dof"]
    assert native["effect_size"] == pytest.approx(legacy["effect_size"], abs=1e-9)
    assert native["low_expected_pct"] == pytest.approx(legacy["low_expected_pct"], abs=1e-9)


# --- assumption handling / normality --------------------------------------------


def test_suggest_test_flags_non_normality_and_run_test_surfaces_the_warning() -> None:
    # A clearly non-normal distribution (all mass at two extremes) for one group.
    csv = (
        b"score,group\n"
        + b"".join(b"1,a\n" for _ in range(15))
        + b"".join(b"999,a\n" for _ in range(15))
        + b"".join(f"{500 + (i % 10)},b\n".encode() for i in range(30))
    )
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv)
    response = client.post(
        f"/api/v1/stats/datasets/{dataset_id}/run",
        json={"test": "ttest", "col_a": "score", "col_b": "group", "numeric_col": "score", "cat_col": "group"},
    )
    body = response.json()
    normality = {check["subject"]: check for check in body["normality"]}
    assert normality["a"]["is_normal"] is False
    assert any("does not look normally distributed" in warning for warning in body["warnings"])


# --- insufficient-evidence semantics: never "no relationship", only "not detected" ---


def test_evidence_statement_never_claims_absence_only_insufficient_evidence() -> None:
    # Two numeric columns with no real relationship (independent random-ish sequences,
    # small enough n that a spurious correlation is unlikely to reach significance).
    csv = b"a,b\n" + b"".join(f"{i},{(i * 7919) % 13}\n".encode() for i in range(1, 21))
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv)
    response = client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "a", "col_b": "b"})
    body = response.json()
    if not body["significant"]:
        assert "does not establish that no" in body["evidence_statement"]
        assert "no correlation" not in body["evidence_statement"].lower().replace("does not establish that no correlation", "")


def test_run_test_requires_at_least_three_paired_values_for_pearson() -> None:
    csv = b"a,b\n1,2\n2,4\n"
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv)
    response = client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "a", "col_b": "b"})
    assert response.status_code == 422


def test_run_test_requires_exactly_two_categories_for_a_ttest() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, THREE_GROUP_CSV)
    response = client.post(
        f"/api/v1/stats/datasets/{dataset_id}/run",
        json={"test": "ttest", "col_a": "score", "col_b": "group", "numeric_col": "score", "cat_col": "group"},
    )
    assert response.status_code == 422


# --- provenance: binds to dataset_id / revision / source_fingerprint ---------------


def test_run_test_result_binds_provenance_to_the_current_revision() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, NUMERIC_CSV)
    dataset = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]

    response = client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    provenance = response.json()["provenance"]

    assert provenance["source_fingerprint"] == dataset["source_fingerprint"]
    assert provenance["dataset_revision"] == dataset["revision"]


# --- Atlas: explains the deterministic result, never invents a statistic -----------


def test_atlas_explain_test_reports_the_deterministic_suggestion_reason() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, NUMERIC_CSV)
    response = client.post(f"/api/v1/stats/datasets/{dataset_id}/atlas", json={"action": "explain_test", "col_a": "x", "col_b": "y"})
    assert response.status_code == 200
    body = response.json()
    assert "correlated" in body["summary"]
    assert any(item["label"] == "Selected test" and item["value"] == "pearson" for item in body["evidence"])


def test_atlas_explain_effect_size_uses_the_same_number_run_test_computed() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, NUMERIC_CSV)
    run_response = client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    expected_effect_size = run_response.json()["effect_size"]

    atlas_response = client.post(f"/api/v1/stats/datasets/{dataset_id}/atlas", json={"action": "explain_effect_size", "col_a": "x", "col_b": "y"})
    body = atlas_response.json()
    evidence_value = next(item["value"] for item in body["evidence"] if item["label"] == "Effect size")
    assert float(evidence_value) == pytest.approx(expected_effect_size, abs=1e-6)
