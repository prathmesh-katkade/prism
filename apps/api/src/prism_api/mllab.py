"""Phase 7C native ML Lab: feature engineering, baseline models, cross-validation, class
imbalance diagnostics, SHAP explainability, and feature selection, ported from
``modules/mllab.py`` onto the shared ``DatasetStore``.

This is explicitly a *baseline exploration* tool, not a model-deployment pipeline — every
result pairs a metric with framing (a verdict, an uncertainty note, a leakage-protection
statement) rather than presenting a bare number as ground truth. Task type detection is
deterministic (dtype + cardinality), never LLM-decided. Preprocessing (impute/scale/encode)
is always fit on the training split only, never on the full dataset before the split — the
one concrete leakage-prevention rule this module exists to enforce. Every model result
records its exact configuration (features, target, task type, seed, split strategy) in its
provenance, so it is reproducible from that configuration alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status
from prism_api_contracts import (
    AtlasEvidence,
    AtlasMlAction,
    AtlasMlRequest,
    AtlasMlResponse,
    MlApplyFeatureRequest,
    MlApplyFeatureResponse,
    MlBaselineRequest,
    MlBaselineResult,
    MlCvMetric,
    MlCvResult,
    MlFeatureImportance,
    MlFeatureRankingRow,
    MlFeatureSelectionRequest,
    MlFeatureSelectionResult,
    MlFeatureSuggestion,
    MlFeatureSuggestionsResponse,
    MlImbalanceInfo,
    MlShapImportance,
    MlShapRequest,
    MlShapResult,
    MlSuggestionType,
    MlTaskDetectionResponse,
    MlTaskType,
    OverviewProvenance,
)
from prism_overview_analytics import ANALYTICS_SERVICE_VERSION, detect_column_types

# Imported at module load, not lazily — the same lesson applied in Phases 7A/7B: sklearn's
# (and its dependents') first import is a heavy one-time cost that belongs at startup, not
# on some user's first ML Lab request.
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.feature_selection import RFE, mutual_info_classif, mutual_info_regression
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Lasso, LassoCV, LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, mean_squared_error, r2_score
from sklearn.metrics import confusion_matrix as sk_confusion_matrix
from sklearn.model_selection import KFold, StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .overview import StoredDataset
from .overview import store as overview_store

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])

ONE_HOT_CARDINALITY_THRESHOLD = 10
IMBALANCE_MINORITY_THRESHOLD_PCT = 20.0
SEED = 42
SHAP_MAX_DISPLAY = 15
FEATURE_SELECTION_MIN_FEATURES = 2
LEAKAGE_NOTE = "Preprocessing (imputation, scaling, one-hot encoding) is fit on the training split only, then applied unchanged to the test split — the test set never influences how features are transformed, so its score is not inflated by information the model would not have at prediction time."


def _provenance(stored: StoredDataset, method: str, parameters: dict[str, Any]) -> OverviewProvenance:
    return OverviewProvenance(
        source_fingerprint=stored.source_fingerprint, dataset_revision=stored.dataset.revision,
        parameters={"method": method, "seed": SEED, **parameters}, service_version=ANALYTICS_SERVICE_VERSION,
        computed_at=datetime.now(timezone.utc),
    )


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column not in frame.columns:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {column!r} is not in the active dataset.")


# --- Feature engineering (revision-aware, same DatasetStore Clean already extends) ------


def suggest_features(frame: pd.DataFrame, target_col: str) -> list[MlFeatureSuggestion]:
    """Direct port of modules/mllab.py::suggest_features."""
    column_types = detect_column_types(frame)
    suggestions: list[MlFeatureSuggestion] = []
    feature_cols = [c for c in frame.columns if c != target_col]
    numeric_cols: list[str] = []

    for col in feature_cols:
        ctype = column_types.get(col)
        if ctype == "categorical":
            nunique = frame[col].nunique()
            if nunique <= ONE_HOT_CARDINALITY_THRESHOLD:
                suggestions.append(MlFeatureSuggestion(kind=MlSuggestionType.ENCODE, column=col, method="one-hot", reason=f"Low cardinality ({nunique} unique values) — one-hot keeps each category independent without implying order."))
            else:
                suggestions.append(MlFeatureSuggestion(kind=MlSuggestionType.ENCODE, column=col, method="ordinal", reason=f"High cardinality ({nunique} unique values) — one-hot would create too many columns; ordinal encoding is more compact."))
        elif ctype == "numeric":
            numeric_cols.append(col)
            suggestions.append(MlFeatureSuggestion(kind=MlSuggestionType.SCALE, column=col, method="standard", reason="Numeric feature — standardizing helps distance-based and linear models treat it fairly alongside other features."))
        elif ctype == "datetime":
            suggestions.append(MlFeatureSuggestion(kind=MlSuggestionType.DATETIME_EXPAND, column=col, reason="Datetime column — expanding into year/month/day/weekday lets models use seasonality patterns directly."))

    if len(numeric_cols) >= 2:
        corr_matrix = frame[numeric_cols].corr().abs()
        pairs = []
        for i, col_a in enumerate(numeric_cols):
            for col_b in numeric_cols[i + 1:]:
                value = corr_matrix.loc[col_a, col_b]
                if pd.notna(value):
                    pairs.append((col_a, col_b, float(value)))
        pairs.sort(key=lambda p: -p[2])
        for col_a, col_b, value in pairs[:3]:
            suggestions.append(MlFeatureSuggestion(kind=MlSuggestionType.INTERACTION, columns=[col_a, col_b], method="product", reason=f"{col_a!r} and {col_b!r} are correlated ({value:.2f}) — their product may capture a combined effect a linear model would otherwise miss."))

    return suggestions


def apply_suggestion(frame: pd.DataFrame, suggestion: MlFeatureSuggestion) -> tuple[pd.DataFrame, str]:
    """Direct port of modules/mllab.py::apply_suggestion (dict-of-string-keys form ported to
    the typed MlFeatureSuggestion contract)."""
    new_df = frame.copy()
    if suggestion.kind is MlSuggestionType.ENCODE:
        col = suggestion.column
        if col is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="An encode suggestion requires a column.")
        if suggestion.method == "one-hot":
            dummies = pd.get_dummies(new_df[col], prefix=col)
            new_df = pd.concat([new_df.drop(columns=[col]), dummies], axis=1)
            return new_df, f"One-hot encoded {col!r} into {dummies.shape[1]} column(s)"
        categories = new_df[col].astype("category").cat.categories
        new_df[col] = new_df[col].astype("category").cat.codes
        return new_df, f"Ordinal-encoded {col!r} ({len(categories)} categories)"
    if suggestion.kind is MlSuggestionType.SCALE:
        col = suggestion.column
        if col is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A scale suggestion requires a column.")
        new_df[col] = StandardScaler().fit_transform(new_df[[col]])
        return new_df, f"Standardized {col!r} (mean 0, std 1)"
    if suggestion.kind is MlSuggestionType.DATETIME_EXPAND:
        col = suggestion.column
        if col is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A datetime_expand suggestion requires a column.")
        dt_series = pd.to_datetime(new_df[col], errors="coerce", format="mixed")
        new_df[f"{col}_year"] = dt_series.dt.year
        new_df[f"{col}_month"] = dt_series.dt.month
        new_df[f"{col}_day"] = dt_series.dt.day
        new_df[f"{col}_weekday"] = dt_series.dt.weekday
        return new_df, f"Expanded {col!r} into year/month/day/weekday columns"
    if suggestion.kind is MlSuggestionType.INTERACTION:
        if not suggestion.columns or len(suggestion.columns) != 2:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="An interaction suggestion requires exactly two columns.")
        col_a, col_b = suggestion.columns
        new_col = f"{col_a}_x_{col_b}"
        new_df[new_col] = new_df[col_a] * new_df[col_b]
        return new_df, f"Added interaction feature {new_col!r} ({col_a} * {col_b})"
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported suggestion type.")


def _fingerprint(frame: pd.DataFrame) -> str:
    import hashlib

    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()


@router.get("/datasets/{dataset_id}/suggest-features", response_model=MlFeatureSuggestionsResponse)
def get_feature_suggestions(dataset_id: str, target_col: str = Query(min_length=1)) -> MlFeatureSuggestionsResponse:
    stored = overview_store.get(dataset_id)
    _require_columns(stored.frame, [target_col])
    return MlFeatureSuggestionsResponse(target_col=target_col, suggestions=suggest_features(stored.frame, target_col))


@router.post("/datasets/{dataset_id}/apply-feature", response_model=MlApplyFeatureResponse, status_code=status.HTTP_201_CREATED)
def apply_feature(dataset_id: str, request: MlApplyFeatureRequest) -> MlApplyFeatureResponse:
    """Feature engineering modifies data, so — exactly like Clean — it produces a new dataset
    revision rather than mutating in place (rule 29). Overview/SQL Lab/Stats/etc. all see the
    updated columns immediately under the same dataset_id."""
    stored = overview_store.get(dataset_id)
    columns_to_check = [c for c in ([request.suggestion.column] if request.suggestion.column else (request.suggestion.columns or [])) if c]
    _require_columns(stored.frame, columns_to_check)
    updated, description = apply_suggestion(stored.frame, request.suggestion)
    fingerprint = _fingerprint(updated)
    dataset = overview_store.add_revision(dataset_id, updated, fingerprint)
    return MlApplyFeatureResponse(dataset=dataset, description=description, provenance=_provenance(StoredDataset(dataset, updated, fingerprint), "apply_feature", {"suggestion": request.suggestion.model_dump(exclude_none=True)}))


# --- Task detection + class imbalance -----------------------------------------------


def detect_task_type(series: pd.Series) -> tuple[MlTaskType, str]:
    """Direct port of modules/mllab.py::detect_task_type, with the reason made explicit."""
    if pd.api.types.is_numeric_dtype(series):
        nunique = series.nunique()
        if nunique <= 15 and nunique / max(len(series), 1) < 0.05:
            return MlTaskType.CLASSIFICATION, f"Numeric but low-cardinality relative to the row count ({nunique} distinct values, {nunique / max(len(series), 1):.1%} of rows) — looks like encoded classes, not a continuous target."
        return MlTaskType.REGRESSION, f"Numeric with {nunique} distinct values — looks like a continuous target."
    return MlTaskType.CLASSIFICATION, "Non-numeric target — classification is the only task type that applies."


@router.get("/datasets/{dataset_id}/detect-task", response_model=MlTaskDetectionResponse)
def get_task_detection(dataset_id: str, target_col: str = Query(min_length=1)) -> MlTaskDetectionResponse:
    stored = overview_store.get(dataset_id)
    _require_columns(stored.frame, [target_col])
    task_type, reason = detect_task_type(stored.frame[target_col])
    return MlTaskDetectionResponse(target_col=target_col, task_type=task_type, reason=reason)


def check_class_imbalance(y: pd.Series) -> dict[str, Any]:
    """Direct port of modules/mllab.py::check_class_imbalance."""
    counts = y.value_counts()
    proportions = (counts / counts.sum() * 100).round(1)
    minority_pct = float(proportions.min())
    return {"counts": {str(k): int(v) for k, v in counts.to_dict().items()}, "proportions_pct": {str(k): float(v) for k, v in proportions.to_dict().items()}, "minority_pct": minority_pct, "is_imbalanced": minority_pct < IMBALANCE_MINORITY_THRESHOLD_PCT}


def imbalance_explanation(info: dict[str, Any]) -> str:
    return f"The minority class is only {info['minority_pct']}% of the data — a model that always predicts the majority class would still score high on accuracy without learning anything useful. F1/recall are shown as the headline metric instead, since they penalize ignoring the minority class."


@router.get("/datasets/{dataset_id}/imbalance", response_model=MlImbalanceInfo)
def get_imbalance(dataset_id: str, target_col: str = Query(min_length=1)) -> MlImbalanceInfo:
    stored = overview_store.get(dataset_id)
    _require_columns(stored.frame, [target_col])
    task_type, _ = detect_task_type(stored.frame[target_col])
    if task_type is not MlTaskType.CLASSIFICATION:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class imbalance applies to classification targets only; this target looks like a regression target.")
    info = check_class_imbalance(stored.frame[target_col].dropna())
    return MlImbalanceInfo(target_col=target_col, counts=info["counts"], proportions_pct=info["proportions_pct"], minority_pct=info["minority_pct"], is_imbalanced=info["is_imbalanced"], explanation=imbalance_explanation(info))


# --- Preprocessing (shared by baseline models, CV, and feature selection) ---------------


def _preprocessor(feature_cols: list[str], X: pd.DataFrame) -> ColumnTransformer:
    categorical_features = [c for c in feature_cols if not pd.api.types.is_numeric_dtype(X[c])]
    numeric_features = [c for c in feature_cols if pd.api.types.is_numeric_dtype(X[c])]
    return ColumnTransformer(transformers=[
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric_features),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("encode", OneHotEncoder(handle_unknown="ignore"))]), categorical_features),
    ], remainder="drop")


def _feature_names(preprocessor: ColumnTransformer) -> list[str]:
    return [name.split("__", 1)[-1] for name in preprocessor.get_feature_names_out()]


def run_cross_validation(frame: pd.DataFrame, feature_cols: list[str], target_col: str, task_type: MlTaskType, n_splits: int = 5) -> dict[str, Any]:
    """Direct port of modules/mllab.py::run_cross_validation."""
    data = frame[[*feature_cols, target_col]].dropna(subset=[target_col])
    X, y = data[feature_cols], data[target_col]
    if len(data) < 4:
        return {"error": "Need at least 4 rows with a non-null target to run cross-validation."}

    preprocessor = _preprocessor(feature_cols, X)
    n_splits_used = min(n_splits, len(data) // 2)
    if task_type is MlTaskType.CLASSIFICATION:
        n_splits_used = min(n_splits_used, int(y.value_counts().min()))
    n_splits_used = max(2, n_splits_used)

    if task_type is MlTaskType.CLASSIFICATION:
        cv = StratifiedKFold(n_splits=n_splits_used, shuffle=True, random_state=SEED)
        scoring = {"accuracy": "accuracy", "f1": "f1_weighted"}
        models: dict[str, Any] = {"Baseline": LogisticRegression(max_iter=1000), "Random Forest": RandomForestClassifier(n_estimators=200, random_state=SEED)}
    else:
        cv = KFold(n_splits=n_splits_used, shuffle=True, random_state=SEED)
        scoring = {"rmse": "neg_root_mean_squared_error", "r2": "r2"}
        models = {"Baseline": LinearRegression(), "Random Forest": RandomForestRegressor(n_estimators=200, random_state=SEED)}

    results: dict[str, dict[str, dict[str, float]]] = {}
    for name, model in models.items():
        pipeline = Pipeline([("preprocess", preprocessor), ("model", model)])
        scores = cross_validate(pipeline, X, y, cv=cv, scoring=scoring)
        metrics: dict[str, dict[str, float]] = {}
        for metric_name in scoring:
            raw = scores[f"test_{metric_name}"]
            if metric_name == "rmse":
                raw = -raw
            metrics[metric_name] = {"mean": round(float(raw.mean()), 4), "std": round(float(raw.std()), 4)}
        results[name] = metrics
    return {"results": results, "n_splits": n_splits_used}


def run_baseline_models(frame: pd.DataFrame, feature_cols: list[str], target_col: str, task_type: MlTaskType, use_smote: bool = False) -> dict[str, Any]:
    """Direct port of modules/mllab.py::run_baseline_models, adapted to return only
    JSON-serializable data (no fitted model objects or raw transformed arrays cross the
    HTTP boundary — rule 46)."""
    data = frame[[*feature_cols, target_col]].dropna(subset=[target_col])
    X, y = data[feature_cols], data[target_col]

    preprocessor = _preprocessor(feature_cols, X)
    stratify = y if task_type is MlTaskType.CLASSIFICATION else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=SEED, stratify=stratify)

    X_train_t = preprocessor.fit_transform(X_train)
    X_test_t = preprocessor.transform(X_test)
    feature_names = _feature_names(preprocessor)

    smote_before_after: Optional[dict[str, Any]] = None
    if task_type is MlTaskType.CLASSIFICATION and use_smote:
        from imblearn.over_sampling import SMOTE

        before_counts = {str(k): int(v) for k, v in y_train.value_counts().to_dict().items()}
        try:
            X_train_t, y_train = SMOTE(random_state=SEED).fit_resample(X_train_t, y_train)
            smote_before_after = {"before": before_counts, "after": {str(k): int(v) for k, v in pd.Series(y_train).value_counts().to_dict().items()}}
        except ValueError as error:
            smote_before_after = {"error": str(error)}

    if task_type is MlTaskType.CLASSIFICATION:
        baseline_model: Any = LogisticRegression(max_iter=1000)
        rf_model: Any = RandomForestClassifier(n_estimators=200, random_state=SEED)
    else:
        baseline_model = LinearRegression()
        rf_model = RandomForestRegressor(n_estimators=200, random_state=SEED)

    fitted_models: dict[str, Any] = {}
    results: dict[str, dict[str, float]] = {}
    for name, model in [("Baseline", baseline_model), ("Random Forest", rf_model)]:
        model.fit(X_train_t, y_train)
        preds = model.predict(X_test_t)
        if task_type is MlTaskType.CLASSIFICATION:
            metrics = {"accuracy": round(float(accuracy_score(y_test, preds)), 4), "f1": round(float(f1_score(y_test, preds, average="weighted")), 4)}
        else:
            metrics = {"rmse": round(float(mean_squared_error(y_test, preds) ** 0.5), 4), "r2": round(float(r2_score(y_test, preds)), 4)}
        fitted_models[name] = model
        results[name] = metrics

    confusion, confusion_labels = None, None
    if task_type is MlTaskType.CLASSIFICATION:
        confusion_labels = sorted(str(v) for v in y.unique().tolist())
        rf_preds = fitted_models["Random Forest"].predict(X_test_t)
        confusion = sk_confusion_matrix(y_test, rf_preds, labels=sorted(y.unique().tolist())).tolist()

    importances = None
    if hasattr(fitted_models["Random Forest"], "feature_importances_"):
        importances = pd.Series(fitted_models["Random Forest"].feature_importances_, index=feature_names).sort_values(ascending=False)

    try:
        cv_results = run_cross_validation(frame, feature_cols, target_col, task_type)
    except Exception as error:
        cv_results = {"error": str(error)}

    return {
        "task_type": task_type, "results": results, "confusion_matrix": confusion, "confusion_labels": confusion_labels,
        "feature_importances": importances, "n_train": len(X_train), "n_test": len(X_test),
        "smote_before_after": smote_before_after, "cv_results": cv_results,
        "fitted_rf_model": fitted_models["Random Forest"], "X_train_transformed": X_train_t, "X_test_transformed": X_test_t, "feature_names": feature_names,
    }


def build_verdict(baseline_result: dict[str, Any]) -> str:
    """Direct port of modules/mllab.py::build_verdict."""
    task_type = baseline_result["task_type"]
    metric_key = "f1" if task_type is MlTaskType.CLASSIFICATION else "r2"
    metric_label = "F1 score" if task_type is MlTaskType.CLASSIFICATION else "R²"

    baseline_score = baseline_result["results"]["Baseline"][metric_key]
    rf_score = baseline_result["results"]["Random Forest"][metric_key]
    better_name = "Random Forest" if rf_score >= baseline_score else "Baseline"
    pct_diff = abs(rf_score - baseline_score) / abs(baseline_score) * 100 if baseline_score else 0.0
    direction = "higher" if rf_score >= baseline_score else "lower"

    verdict = f"{better_name} wins on {metric_label} ({max(rf_score, baseline_score):.3f} vs {min(rf_score, baseline_score):.3f}, {pct_diff:.0f}% {direction} than the other model)."
    importances = baseline_result.get("feature_importances")
    if importances is not None and not importances.empty:
        verdict += f" Top driver: {importances.index[0]}."
    return verdict


@router.post("/datasets/{dataset_id}/baseline", response_model=MlBaselineResult)
def baseline(dataset_id: str, request: MlBaselineRequest) -> MlBaselineResult:
    stored = overview_store.get(dataset_id)
    _require_columns(stored.frame, [*request.feature_cols, request.target_col])

    task_type = request.task_type
    if task_type is None:
        task_type, _ = detect_task_type(stored.frame[request.target_col])

    result = run_baseline_models(stored.frame, request.feature_cols, request.target_col, task_type, request.use_smote)
    verdict = build_verdict(result)

    importances = result["feature_importances"]
    feature_importances = [MlFeatureImportance(feature=name, importance=float(value)) for name, value in importances.head(SHAP_MAX_DISPLAY).items()] if importances is not None else []

    cv_results = result["cv_results"]
    cv: Optional[MlCvResult] = None
    cv_error: Optional[str] = None
    if "error" in cv_results:
        cv_error = cv_results["error"]
    else:
        cv = MlCvResult(results={model: {metric: MlCvMetric(**values) for metric, values in metrics.items()} for model, metrics in cv_results["results"].items()}, n_splits=cv_results["n_splits"])

    return MlBaselineResult(
        task_type=task_type, results=result["results"], confusion_matrix=result["confusion_matrix"], confusion_labels=result["confusion_labels"],
        feature_importances=feature_importances, n_train=result["n_train"], n_test=result["n_test"], smote_before_after=result["smote_before_after"],
        cv=cv, cv_error=cv_error, verdict=verdict, leakage_note=LEAKAGE_NOTE,
        provenance=_provenance(stored, "baseline", {"feature_cols": request.feature_cols, "target_col": request.target_col, "task_type": task_type.value, "use_smote": request.use_smote, "split": "80/20 stratified" if task_type is MlTaskType.CLASSIFICATION else "80/20"}),
    )


# --- Feature selection: three-method consensus ------------------------------------


def run_feature_selection(frame: pd.DataFrame, feature_cols: list[str], target_col: str, task_type: MlTaskType, top_k: Optional[int] = None) -> dict[str, Any]:
    """Direct port of modules/mllab.py::run_feature_selection."""
    if len(feature_cols) < FEATURE_SELECTION_MIN_FEATURES:
        return {"error": f"Feature Selection needs at least {FEATURE_SELECTION_MIN_FEATURES} feature columns."}

    from scipy import sparse

    data = frame[[*feature_cols, target_col]].dropna(subset=[target_col])
    X, y = data[feature_cols], data[target_col]
    preprocessor = _preprocessor(feature_cols, X)
    X_transformed = preprocessor.fit_transform(X)
    if sparse.issparse(X_transformed):
        X_transformed = X_transformed.toarray()
    feature_names = _feature_names(preprocessor)
    n_features = len(feature_names)
    if n_features < FEATURE_SELECTION_MIN_FEATURES:
        return {"error": "Fewer than 2 usable features after preprocessing (check for all-null columns)."}

    k = top_k if top_k is not None else max(1, n_features // 2)
    k = min(k, n_features)
    y_values = y.to_numpy()
    n_samples = X_transformed.shape[0]

    mi_func = mutual_info_classif if task_type is MlTaskType.CLASSIFICATION else mutual_info_regression
    try:
        mi_scores = mi_func(X_transformed, y_values, random_state=SEED)
    except ValueError:
        mi_scores = np.zeros(n_features)
    mi_series = pd.Series(mi_scores, index=feature_names)
    mi_rank = mi_series.rank(ascending=False, method="min")

    if task_type is MlTaskType.CLASSIFICATION:
        l1_model: Any = LogisticRegression(penalty="l1", solver="liblinear", C=1.0, max_iter=2000)
        l1_model.fit(X_transformed, y_values)
        coefs = np.abs(l1_model.coef_)
        l1_scores = coefs.max(axis=0) if coefs.ndim > 1 else coefs
    else:
        cv_folds = min(5, max(2, n_samples // 5))
        try:
            l1_model = LassoCV(cv=cv_folds, random_state=SEED, max_iter=10000)
            l1_model.fit(X_transformed, y_values)
        except ValueError:
            l1_model = Lasso(alpha=0.01, max_iter=10000)
            l1_model.fit(X_transformed, y_values)
        l1_scores = np.abs(l1_model.coef_)
    l1_series = pd.Series(l1_scores, index=feature_names)
    l1_rank = l1_series.rank(ascending=False, method="min")

    rf_estimator: Any = RandomForestClassifier(n_estimators=100, random_state=SEED) if task_type is MlTaskType.CLASSIFICATION else RandomForestRegressor(n_estimators=100, random_state=SEED)
    rfe = RFE(estimator=rf_estimator, n_features_to_select=k)
    rfe.fit(X_transformed, y_values)
    rfe_selected = pd.Series(rfe.support_, index=feature_names)
    rfe_rank = pd.Series(rfe.ranking_, index=feature_names)

    ranking = pd.DataFrame({"mutual_info": mi_series, "mutual_info_rank": mi_rank, "l1_coef_abs": l1_series, "l1_rank": l1_rank, "rfe_selected": rfe_selected, "rfe_rank": rfe_rank})
    ranking["consensus_votes"] = (ranking["mutual_info_rank"] <= k).astype(int) + (ranking["l1_rank"] <= k).astype(int) + ranking["rfe_selected"].astype(int)
    ranking["consensus_rank"] = ranking[["mutual_info_rank", "l1_rank", "rfe_rank"]].mean(axis=1)
    ranking = ranking.sort_values(["consensus_votes", "consensus_rank"], ascending=[False, True])

    return {"task_type": task_type, "top_k": k, "n_features": n_features, "ranking": ranking, "recommended_features": ranking.head(k).index.tolist()}


@router.post("/datasets/{dataset_id}/feature-selection", response_model=MlFeatureSelectionResult)
def feature_selection(dataset_id: str, request: MlFeatureSelectionRequest) -> MlFeatureSelectionResult:
    stored = overview_store.get(dataset_id)
    _require_columns(stored.frame, [*request.feature_cols, request.target_col])
    task_type = request.task_type
    if task_type is None:
        task_type, _ = detect_task_type(stored.frame[request.target_col])

    result = run_feature_selection(stored.frame, request.feature_cols, request.target_col, task_type, request.top_k)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    ranking_df = result["ranking"]
    rows = [
        MlFeatureRankingRow(feature=str(name), mutual_info=float(row["mutual_info"]), mutual_info_rank=float(row["mutual_info_rank"]), l1_coef_abs=float(row["l1_coef_abs"]), l1_rank=float(row["l1_rank"]), rfe_selected=bool(row["rfe_selected"]), rfe_rank=float(row["rfe_rank"]), consensus_votes=int(row["consensus_votes"]), consensus_rank=float(row["consensus_rank"]))
        for name, row in ranking_df.iterrows()
    ]
    return MlFeatureSelectionResult(
        task_type=task_type, top_k=result["top_k"], n_features=result["n_features"], ranking=rows, recommended_features=[str(f) for f in result["recommended_features"]],
        provenance=_provenance(stored, "feature_selection", {"feature_cols": request.feature_cols, "target_col": request.target_col, "task_type": task_type.value, "top_k": result["top_k"]}),
    )


# --- SHAP explainability: global importance for the Random Forest ---------------------


def shap_for_display(shap_values: Any) -> Any:
    """Direct port of modules/mllab.py::shap_for_display."""
    values = getattr(shap_values, "values", None)
    if values is not None and values.ndim == 3:
        class_idx = int(np.abs(values).mean(axis=(0, 1)).argmax())
        return shap_values[:, :, class_idx]
    return shap_values


def explain_with_shap(model: Any, X_background: Any, X_explain: Any, feature_names: list[str]) -> Any:
    """Direct port of modules/mllab.py::explain_with_shap."""
    import shap
    from scipy import sparse

    if sparse.issparse(X_background):
        X_background = X_background.toarray()
    if sparse.issparse(X_explain):
        X_explain = X_explain.toarray()

    explainer = shap.Explainer(model, X_background, feature_names=feature_names)
    try:
        return explainer(X_explain)
    except shap.utils._exceptions.ExplainerError:
        return explainer(X_explain, check_additivity=False)


@router.post("/datasets/{dataset_id}/shap", response_model=MlShapResult)
def shap_explain(dataset_id: str, request: MlShapRequest) -> MlShapResult:
    """Re-fits the Random Forest with the same seed/split as /baseline rather than caching a
    fitted model object across requests — deterministic given the same configuration (rule
    36: reproducible from the configuration alone), and avoids holding unserializable model
    state in server memory between calls."""
    stored = overview_store.get(dataset_id)
    _require_columns(stored.frame, [*request.feature_cols, request.target_col])
    task_type = request.task_type
    if task_type is None:
        task_type, _ = detect_task_type(stored.frame[request.target_col])

    result = run_baseline_models(stored.frame, request.feature_cols, request.target_col, task_type, use_smote=False)
    try:
        shap_values = explain_with_shap(result["fitted_rf_model"], result["X_train_transformed"], result["X_test_transformed"], result["feature_names"])
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"SHAP explanation failed: {error}") from error

    display_values = shap_for_display(shap_values)
    mean_abs = np.abs(display_values.values).mean(axis=0)
    ranked = sorted(zip(result["feature_names"], mean_abs), key=lambda item: -item[1])[:SHAP_MAX_DISPLAY]

    return MlShapResult(
        task_type=task_type, model_explained="Random Forest",
        global_importance=[MlShapImportance(feature=name, mean_abs_shap=float(value)) for name, value in ranked],
        note="Global importance is the mean absolute SHAP value per feature across the test set — how much each feature moved predictions away from the baseline, on average, in either direction. This describes what the model used, not what causes the outcome.",
        provenance=_provenance(stored, "shap", {"feature_cols": request.feature_cols, "target_col": request.target_col, "task_type": task_type.value, "model_explained": "Random Forest"}),
    )


# --- Atlas: explains the deterministic result, never invents or retrains a model --------


@router.post("/datasets/{dataset_id}/atlas", response_model=AtlasMlResponse)
def atlas_action(dataset_id: str, request: AtlasMlRequest) -> AtlasMlResponse:
    stored = overview_store.get(dataset_id)
    _require_columns(stored.frame, [*request.feature_cols, request.target_col])
    uncertainty = "This explanation describes a deterministic model-evaluation result; it does not establish causation, and Atlas never retrains or alters a model outside an explicit PRISM command."

    task_type = request.task_type
    if task_type is None:
        task_type, _ = detect_task_type(stored.frame[request.target_col])

    if request.action is AtlasMlAction.EXPLAIN_TASK_TYPE:
        _, reason = detect_task_type(stored.frame[request.target_col])
        return AtlasMlResponse(action=request.action, summary=reason, uncertainty=uncertainty, evidence=[AtlasEvidence(label="Task type", value=task_type.value)])

    if request.action is AtlasMlAction.EXPLAIN_IMBALANCE:
        if task_type is not MlTaskType.CLASSIFICATION:
            return AtlasMlResponse(action=request.action, summary="Class imbalance applies to classification targets only; this target looks like a regression target.", uncertainty=uncertainty, evidence=[])
        info = check_class_imbalance(stored.frame[request.target_col].dropna())
        return AtlasMlResponse(action=request.action, summary=imbalance_explanation(info), uncertainty=uncertainty, evidence=[AtlasEvidence(label="Minority class", value=f"{info['minority_pct']}%")])

    result = run_baseline_models(stored.frame, request.feature_cols, request.target_col, task_type, use_smote=False)

    if request.action is AtlasMlAction.COMPARE_MODELS:
        return AtlasMlResponse(action=request.action, summary=build_verdict(result), uncertainty=uncertainty, evidence=[AtlasEvidence(label=name, value=", ".join(f"{k}={v}" for k, v in metrics.items())) for name, metrics in result["results"].items()])

    if request.action is AtlasMlAction.EXPLAIN_CROSS_VALIDATION:
        cv_results = result["cv_results"]
        if "error" in cv_results:
            return AtlasMlResponse(action=request.action, summary=f"Cross-validation could not run: {cv_results['error']}", uncertainty=uncertainty, evidence=[])
        summary = f"A single 80/20 split is one draw from many possible splits — {cv_results['n_splits']}-fold cross-validation instead reports each model's mean ± std across folds, showing how stable the score actually is."
        evidence = [AtlasEvidence(label=f"{name} {metric}", value=f"{values['mean']:.3f} ± {values['std']:.3f}") for name, metrics in cv_results["results"].items() for metric, values in metrics.items()]
        return AtlasMlResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=evidence)

    if request.action is AtlasMlAction.EXPLAIN_FEATURE_IMPORTANCE:
        importances = result["feature_importances"]
        if importances is None or importances.empty:
            return AtlasMlResponse(action=request.action, summary="No feature importances are available for this run.", uncertainty=uncertainty, evidence=[])
        top = importances.head(5)
        return AtlasMlResponse(action=request.action, summary=f"Random Forest's feature_importances_ ranks {top.index[0]!r} highest — how much each split on that feature reduced prediction error on average, across all trees. This measures predictive usefulness to this model, not a causal effect.", uncertainty=uncertainty, evidence=[AtlasEvidence(label=name, value=f"{value:.4f}") for name, value in top.items()])

    # IDENTIFY_OVERFITTING
    cv_results = result["cv_results"]
    metric_key = "f1" if task_type is MlTaskType.CLASSIFICATION else "r2"
    holdout_score = result["results"]["Random Forest"][metric_key]
    if "error" in cv_results:
        return AtlasMlResponse(action=request.action, summary=f"Cross-validation could not run to compare against the holdout score ({cv_results['error']}); overfitting cannot be assessed from this run alone.", uncertainty=uncertainty, evidence=[])
    cv_mean = cv_results["results"]["Random Forest"][metric_key]["mean"]
    gap = holdout_score - cv_mean
    flag = "a meaningful gap between the single holdout score and the cross-validated mean — possible overfitting to that particular split" if abs(gap) > 0.1 else "no meaningful gap between the single holdout score and the cross-validated mean"
    return AtlasMlResponse(action=request.action, summary=f"Random Forest scored {holdout_score:.3f} on the holdout test set vs. a {cv_mean:.3f} mean across {cv_results['n_splits']} cross-validation folds — {flag}.", uncertainty=uncertainty, evidence=[AtlasEvidence(label="Holdout score", value=f"{holdout_score:.3f}"), AtlasEvidence(label="CV mean", value=f"{cv_mean:.3f}")])
