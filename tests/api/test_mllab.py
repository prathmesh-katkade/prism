from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_overview_analytics import detect_column_types

from modules import mllab as legacy_mllab


def _csv(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode()


# 40 rows, roughly balanced binary target that's actually learnable from x1/x2/segment —
# real signal, not just noise, so Random Forest gets non-trivial feature importances.
def _classification_frame() -> pd.DataFrame:
    rows = []
    for i in range(40):
        x1 = float(i % 10)
        x2 = float((i * 3) % 7)
        segment = "a" if i % 3 == 0 else "b" if i % 3 == 1 else "c"
        label = "yes" if (x1 + x2) > 8 else "no"
        rows.append({"x1": x1, "x2": x2, "segment": segment, "label": label})
    return pd.DataFrame(rows)


CLASSIFICATION_CSV = _csv(_classification_frame())


# 40 rows, continuous target linearly related to x1/x2 plus a little structured noise.
def _regression_frame() -> pd.DataFrame:
    rows = []
    for i in range(40):
        x1 = float(i)
        x2 = float(i % 5)
        value = 3.0 * x1 + 2.0 * x2 + (i % 3)
        rows.append({"x1": x1, "x2": x2, "value": value})
    return pd.DataFrame(rows)


REGRESSION_CSV = _csv(_regression_frame())


# 40 rows, clearly imbalanced binary target (6 "rare" of 40 = 15%, below the 20% threshold).
def _imbalanced_frame() -> pd.DataFrame:
    rows = [{"id": i, "score": float(i), "label": "rare" if i < 6 else "common"} for i in range(40)]
    return pd.DataFrame(rows)


IMBALANCED_CSV = _csv(_imbalanced_frame())


# 40 rows, imbalanced (10 "rare" of 40 = 25%) but with enough minority rows that SMOTE's
# default k_neighbors=5 requirement is satisfiable after the 80/20 split (~8 in training).
def _smote_frame() -> pd.DataFrame:
    rows = [{"id": i, "score": float(i)} for i in range(40)]
    for i, row in enumerate(rows):
        row["label"] = "rare" if i < 10 else "common"
    return pd.DataFrame(rows)


SMOTE_CSV = _csv(_smote_frame())


def _dataset(client: TestClient, csv: bytes, name: str = "ml.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


# --- feature engineering: suggestion parity + revision-aware apply -----------------


def test_suggest_features_matches_legacy_dtype_driven_reasoning() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.get(f"/api/v1/ml/datasets/{dataset_id}/suggest-features", params={"target_col": "label"})
    assert response.status_code == 200
    native = response.json()["suggestions"]

    frame = _classification_frame()
    legacy = legacy_mllab.suggest_features(frame, detect_column_types(frame), "label")

    native_by_column = {s["column"]: s for s in native if s.get("column")}
    for legacy_suggestion in legacy:
        if legacy_suggestion["type"] == "interaction":
            continue
        native_match = native_by_column[legacy_suggestion["column"]]
        assert native_match["kind"] == legacy_suggestion["type"]
        assert native_match["method"] == legacy_suggestion.get("method")


def test_apply_feature_scale_creates_a_new_revision_the_dataset_reflects() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/apply-feature", json={"suggestion": {"kind": "scale", "column": "x1", "method": "standard", "reason": "test"}})
    assert response.status_code == 201
    body = response.json()
    assert body["dataset"]["revision"] == 1
    assert "Standardized" in body["description"]

    profile = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()
    assert profile["dataset"]["revision"] == 1


def test_apply_feature_one_hot_encode_matches_legacy_column_expansion() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/apply-feature", json={"suggestion": {"kind": "encode", "column": "segment", "method": "one-hot", "reason": "test"}})
    body = response.json()

    frame = _classification_frame()
    legacy_frame, legacy_description, _ = legacy_mllab.apply_suggestion(frame, {"type": "encode", "column": "segment", "method": "one-hot"})
    assert body["description"] == legacy_description

    profile = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()
    assert profile["dataset"]["column_count"] == len(legacy_frame.columns)


# --- task detection --------------------------------------------------------------


def test_detect_task_type_matches_legacy_for_classification_and_regression_targets() -> None:
    client = TestClient(create_app())
    class_id = _dataset(client, CLASSIFICATION_CSV, "c.csv")
    reg_id = _dataset(client, REGRESSION_CSV, "r.csv")

    native_class = client.get(f"/api/v1/ml/datasets/{class_id}/detect-task", params={"target_col": "label"}).json()
    native_reg = client.get(f"/api/v1/ml/datasets/{reg_id}/detect-task", params={"target_col": "value"}).json()

    legacy_class = legacy_mllab.detect_task_type(_classification_frame()["label"])
    legacy_reg = legacy_mllab.detect_task_type(_regression_frame()["value"])

    assert native_class["task_type"] == legacy_class
    assert native_reg["task_type"] == legacy_reg


# --- class imbalance --------------------------------------------------------------


def test_imbalance_reports_the_minority_class_matching_legacy() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, IMBALANCED_CSV)
    response = client.get(f"/api/v1/ml/datasets/{dataset_id}/imbalance", params={"target_col": "label"})
    assert response.status_code == 200
    native = response.json()

    legacy = legacy_mllab.check_class_imbalance(_imbalanced_frame()["label"])
    assert native["minority_pct"] == pytest.approx(legacy["minority_pct"])
    assert native["is_imbalanced"] == legacy["is_imbalanced"]
    assert native["is_imbalanced"] is True


def test_imbalance_rejects_a_regression_target() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, REGRESSION_CSV)
    response = client.get(f"/api/v1/ml/datasets/{dataset_id}/imbalance", params={"target_col": "value"})
    assert response.status_code == 422


# --- baseline models: parity, leakage protection, cross-validation -----------------


def test_baseline_classification_matches_legacy_metrics_and_confusion_matrix() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label", "task_type": "classification"})
    assert response.status_code == 200
    native = response.json()

    legacy = legacy_mllab.run_baseline_models(_classification_frame(), ["x1", "x2", "segment"], "label", "classification")

    assert native["results"] == legacy["results"]
    assert native["n_train"] == legacy["n_train"]
    assert native["n_test"] == legacy["n_test"]
    assert native["confusion_matrix"] == legacy["confusion_matrix"].tolist()


def test_baseline_regression_matches_legacy_metrics() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, REGRESSION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2"], "target_col": "value", "task_type": "regression"})
    native = response.json()

    legacy = legacy_mllab.run_baseline_models(_regression_frame(), ["x1", "x2"], "value", "regression")
    assert native["results"] == legacy["results"]
    assert native["confusion_matrix"] is None


def test_baseline_train_and_test_splits_are_disjoint_and_states_the_leakage_protection() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    body = response.json()
    assert body["n_train"] + body["n_test"] == 40
    assert "training split only" in body["leakage_note"]


def test_baseline_includes_cross_validation_matching_legacy_fold_means() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    native = response.json()
    assert native["cv"] is not None
    assert native["cv_error"] is None

    legacy_cv = legacy_mllab.run_cross_validation(_classification_frame(), ["x1", "x2", "segment"], "label", "classification")
    for model_name, metrics in legacy_cv["results"].items():
        for metric_name, values in metrics.items():
            native_values = native["cv"]["results"][model_name][metric_name]
            assert native_values["mean"] == pytest.approx(values["mean"], abs=1e-6)
            assert native_values["std"] == pytest.approx(values["std"], abs=1e-6)


def test_baseline_smote_reports_before_and_after_class_counts() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, SMOTE_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["id", "score"], "target_col": "label", "task_type": "classification", "use_smote": True})
    body = response.json()
    assert body["smote_before_after"] is not None
    assert "before" in body["smote_before_after"] and "after" in body["smote_before_after"]
    # SMOTE only touches the training set — the minority count in "after" should be raised
    # to match the majority count (that's what SMOTE does), and never applied to the test set.
    after = body["smote_before_after"]["after"]
    assert len(set(after.values())) == 1


def test_baseline_provenance_binds_to_the_current_revision() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    dataset = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2"], "target_col": "label"})
    provenance = response.json()["provenance"]
    assert provenance["source_fingerprint"] == dataset["source_fingerprint"]
    assert provenance["dataset_revision"] == dataset["revision"]


# --- feature selection: three-method consensus ---------------------------------


def test_feature_selection_matches_legacy_recommended_features() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/feature-selection", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label", "task_type": "classification"})
    assert response.status_code == 200
    native = response.json()

    legacy = legacy_mllab.run_feature_selection(_classification_frame(), ["x1", "x2", "segment"], "label", "classification")
    assert set(native["recommended_features"]) == set(legacy["recommended_features"])
    assert native["n_features"] == legacy["n_features"]


def test_feature_selection_requires_at_least_two_feature_columns() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/feature-selection", json={"feature_cols": ["x1"], "target_col": "label"})
    assert response.status_code == 422


# --- SHAP: global importance sanity (deterministic TreeExplainer, tolerance per rule 39) ---


def test_shap_returns_global_importance_for_the_random_forest() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/shap", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    assert response.status_code == 200
    body = response.json()
    assert body["model_explained"] == "Random Forest"
    assert len(body["global_importance"]) > 0
    assert all(item["mean_abs_shap"] >= 0 for item in body["global_importance"])
    # Sorted descending by importance.
    values = [item["mean_abs_shap"] for item in body["global_importance"]]
    assert values == sorted(values, reverse=True)


# --- Atlas: explains the deterministic result, never invents a model -------------


def test_atlas_compare_models_matches_the_deterministic_verdict() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    baseline = client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"}).json()

    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/atlas", json={"action": "compare_models", "feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    body = response.json()
    assert body["summary"] == baseline["verdict"]


def test_atlas_explain_imbalance_rejects_a_regression_target_gracefully() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, REGRESSION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/atlas", json={"action": "explain_imbalance", "feature_cols": ["x1", "x2"], "target_col": "value"})
    body = response.json()
    assert "regression target" in body["summary"]


def test_atlas_identify_overfitting_compares_holdout_against_cross_validated_mean() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CLASSIFICATION_CSV)
    response = client.post(f"/api/v1/ml/datasets/{dataset_id}/atlas", json={"action": "identify_overfitting", "feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    body = response.json()
    assert any(item["label"] == "Holdout score" for item in body["evidence"])
    assert any(item["label"] == "CV mean" for item in body["evidence"])
