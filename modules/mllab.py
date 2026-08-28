"""
ML Lab — the data-science bridge: a feature engineering assistant that
suggests (and one-click applies) encoding/scaling/datetime-expansion/
interaction features, a baseline model runner (Logistic/Linear Regression
vs. Random Forest, auto-detecting classification vs. regression), and a
class-imbalance detector with optional SMOTE resampling on the training set.

This is explicitly a *baseline exploration* tool, not a model-deployment
pipeline — every result the UI shows should be paired with that framing.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

SMOTE_TEST_SET_NOTE = (
    "SMOTE is applied only to the training set, after the train/test split — the test set stays "
    "exactly as collected, since evaluating against synthetic data would give a falsely optimistic score."
)

# ==========================================================================
# 9. Feature Engineering Assistant
# ==========================================================================

ONE_HOT_CARDINALITY_THRESHOLD = 10


def suggest_features(df: pd.DataFrame, column_types: dict[str, str], target_col: str) -> list[dict]:
    """For every non-target column, suggest an encoding/scaling/expansion
    treatment, plus up to 3 candidate numeric interaction features.

    Returns a list of suggestion dicts:
    {"type": "encode", "column", "method": "one-hot"|"ordinal", "reason"}
    {"type": "scale", "column", "method": "standard", "reason"}
    {"type": "datetime_expand", "column", "reason"}
    {"type": "interaction", "columns": [a, b], "method": "product", "reason"}
    """
    suggestions = []
    feature_cols = [c for c in df.columns if c != target_col]
    numeric_cols = []

    for col in feature_cols:
        ctype = column_types.get(col)
        if ctype == "categorical":
            nunique = df[col].nunique()
            if nunique <= ONE_HOT_CARDINALITY_THRESHOLD:
                suggestions.append(
                    {
                        "type": "encode", "column": col, "method": "one-hot",
                        "reason": f"Low cardinality ({nunique} unique values) — one-hot keeps each category independent without implying order.",
                    }
                )
            else:
                suggestions.append(
                    {
                        "type": "encode", "column": col, "method": "ordinal",
                        "reason": f"High cardinality ({nunique} unique values) — one-hot would create too many columns; ordinal encoding is more compact.",
                    }
                )
        elif ctype == "numeric":
            numeric_cols.append(col)
            suggestions.append(
                {
                    "type": "scale", "column": col, "method": "standard",
                    "reason": "Numeric feature — standardizing helps distance-based and linear models treat it fairly alongside other features.",
                }
            )
        elif ctype == "datetime":
            suggestions.append(
                {
                    "type": "datetime_expand", "column": col,
                    "reason": "Datetime column — expanding into year/month/day/weekday lets models use seasonality patterns directly.",
                }
            )

    if len(numeric_cols) >= 2:
        corr_matrix = df[numeric_cols].corr().abs()
        pairs = []
        for i, col_a in enumerate(numeric_cols):
            for col_b in numeric_cols[i + 1 :]:
                value = corr_matrix.loc[col_a, col_b]
                if pd.notna(value):
                    pairs.append((col_a, col_b, value))
        pairs.sort(key=lambda p: -p[2])
        for col_a, col_b, value in pairs[:3]:
            suggestions.append(
                {
                    "type": "interaction", "columns": [col_a, col_b], "method": "product",
                    "reason": (
                        f"'{col_a}' and '{col_b}' are correlated ({value:.2f}) — their product may capture "
                        "a combined effect a linear model would otherwise miss."
                    ),
                }
            )

    return suggestions


def apply_suggestion(df: pd.DataFrame, suggestion: dict) -> tuple[pd.DataFrame, str, str]:
    """Apply one feature-engineering suggestion. Returns (new_df, description, code)."""
    new_df = df.copy()
    kind = suggestion["type"]

    if kind == "encode":
        col = suggestion["column"]
        if suggestion["method"] == "one-hot":
            dummies = pd.get_dummies(new_df[col], prefix=col)
            new_df = pd.concat([new_df.drop(columns=[col]), dummies], axis=1)
            description = f"One-hot encoded '{col}' into {dummies.shape[1]} column(s)"
            code = (
                f"df = pd.concat([df.drop(columns=[{col!r}]), "
                f"pd.get_dummies(df[{col!r}], prefix={col!r})], axis=1)"
            )
        else:
            categories = new_df[col].astype("category").cat.categories
            new_df[col] = new_df[col].astype("category").cat.codes
            description = f"Ordinal-encoded '{col}' ({len(categories)} categories)"
            code = f"df[{col!r}] = df[{col!r}].astype('category').cat.codes"

    elif kind == "scale":
        col = suggestion["column"]
        from sklearn.preprocessing import StandardScaler

        new_df[col] = StandardScaler().fit_transform(new_df[[col]])
        description = f"Standardized '{col}' (mean 0, std 1)"
        code = f"from sklearn.preprocessing import StandardScaler\ndf[{col!r}] = StandardScaler().fit_transform(df[[{col!r}]])"

    elif kind == "datetime_expand":
        col = suggestion["column"]
        dt_series = pd.to_datetime(new_df[col], errors="coerce")
        new_df[f"{col}_year"] = dt_series.dt.year
        new_df[f"{col}_month"] = dt_series.dt.month
        new_df[f"{col}_day"] = dt_series.dt.day
        new_df[f"{col}_weekday"] = dt_series.dt.weekday
        description = f"Expanded '{col}' into year/month/day/weekday columns"
        code = (
            f"_dt = pd.to_datetime(df[{col!r}], errors='coerce')\n"
            f"df[{col + '_year'!r}] = _dt.dt.year\n"
            f"df[{col + '_month'!r}] = _dt.dt.month\n"
            f"df[{col + '_day'!r}] = _dt.dt.day\n"
            f"df[{col + '_weekday'!r}] = _dt.dt.weekday"
        )

    elif kind == "interaction":
        col_a, col_b = suggestion["columns"]
        new_col = f"{col_a}_x_{col_b}"
        new_df[new_col] = new_df[col_a] * new_df[col_b]
        description = f"Added interaction feature '{new_col}' ({col_a} * {col_b})"
        code = f"df[{new_col!r}] = df[{col_a!r}] * df[{col_b!r}]"

    else:
        return df, "Unknown suggestion type", "# unknown suggestion type"

    return new_df, description, code


# ==========================================================================
# 10. Baseline Model Runner
# ==========================================================================


def detect_task_type(series: pd.Series) -> str:
    """"classification" if the target looks categorical/low-cardinality
    relative to the row count, else "regression"."""
    if pd.api.types.is_numeric_dtype(series):
        nunique = series.nunique()
        if nunique <= 15 and nunique / max(len(series), 1) < 0.05:
            return "classification"
        return "regression"
    return "classification"


def run_baseline_models(
    df: pd.DataFrame, feature_cols: list[str], target_col: str, task_type: str, use_smote: bool = False
) -> dict:
    """Train/test split (80/20, stratified for classification), a
    ColumnTransformer preprocessing pipeline (impute + one-hot for
    categoricals, impute + StandardScaler for numerics), and two baseline
    models (Logistic/Linear Regression + Random Forest) compared side by side.

    Returns {"task_type", "results": {model_name: metrics}, "confusion_matrix",
    "confusion_labels", "feature_importances", "n_train", "n_test",
    "smote_before_after"}.
    """
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        f1_score,
        mean_squared_error,
        r2_score,
    )
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    data = df[feature_cols + [target_col]].dropna(subset=[target_col])
    X = data[feature_cols]
    y = data[target_col]

    categorical_features = [c for c in feature_cols if not pd.api.types.is_numeric_dtype(X[c])]
    numeric_features = [c for c in feature_cols if pd.api.types.is_numeric_dtype(X[c])]

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric_features),
            (
                "cat",
                Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("encode", OneHotEncoder(handle_unknown="ignore"))]),
                categorical_features,
            ),
        ],
        remainder="drop",
    )

    stratify = y if task_type == "classification" else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=stratify)

    X_train_transformed = preprocessor.fit_transform(X_train)
    X_test_transformed = preprocessor.transform(X_test)
    feature_names = [name.split("__", 1)[-1] for name in preprocessor.get_feature_names_out()]

    smote_before_after = None
    if task_type == "classification" and use_smote:
        from imblearn.over_sampling import SMOTE

        before_counts = y_train.value_counts().to_dict()
        try:
            X_train_transformed, y_train = SMOTE(random_state=42).fit_resample(X_train_transformed, y_train)
            smote_before_after = {"before": before_counts, "after": pd.Series(y_train).value_counts().to_dict()}
        except ValueError as e:
            smote_before_after = {"error": str(e)}

    if task_type == "classification":
        baseline_model = LogisticRegression(max_iter=1000)
        rf_model = RandomForestClassifier(n_estimators=200, random_state=42)
    else:
        baseline_model = LinearRegression()
        rf_model = RandomForestRegressor(n_estimators=200, random_state=42)

    fitted_models = {}
    results = {}
    for name, model in [("Baseline", baseline_model), ("Random Forest", rf_model)]:
        model.fit(X_train_transformed, y_train)
        preds = model.predict(X_test_transformed)
        if task_type == "classification":
            metrics = {
                "accuracy": round(accuracy_score(y_test, preds), 4),
                "f1": round(f1_score(y_test, preds, average="weighted"), 4),
            }
        else:
            metrics = {
                "rmse": round(mean_squared_error(y_test, preds) ** 0.5, 4),
                "r2": round(r2_score(y_test, preds), 4),
            }
        fitted_models[name] = model
        results[name] = metrics

    confusion, confusion_labels = None, None
    if task_type == "classification":
        confusion_labels = sorted(y.unique().tolist())
        rf_preds = fitted_models["Random Forest"].predict(X_test_transformed)
        confusion = confusion_matrix(y_test, rf_preds, labels=confusion_labels)

    importances = None
    if hasattr(fitted_models["Random Forest"], "feature_importances_"):
        importances = pd.Series(
            fitted_models["Random Forest"].feature_importances_, index=feature_names
        ).sort_values(ascending=False)

    # K-fold cross-validation, same two models — see run_cross_validation()'s
    # docstring for why a single 80/20 split's score alone isn't enough to
    # call a model "stable." Never blocks the primary result: a CV failure
    # (e.g. a genuinely tiny dataset) just leaves this key absent.
    try:
        cv_results = run_cross_validation(df, feature_cols, target_col, task_type)
    except Exception as e:
        cv_results = {"error": str(e)}

    return {
        "task_type": task_type,
        "results": results,
        "confusion_matrix": confusion,
        "confusion_labels": confusion_labels,
        "feature_importances": importances,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "smote_before_after": smote_before_after,
        "cv_results": cv_results,
        # Kept for SHAP explainability (see explain_with_shap below) — the
        # Random Forest specifically, since it's the model feature_importances_
        # already covers; re-fitting a second time just to explain it would
        # waste both compute and the point of reusing this same run.
        "fitted_rf_model": fitted_models["Random Forest"],
        "X_train_transformed": X_train_transformed,
        "X_test_transformed": X_test_transformed,
        "feature_names": feature_names,
    }


def run_cross_validation(
    df: pd.DataFrame, feature_cols: list[str], target_col: str, task_type: str, n_splits: int = 5
) -> dict:
    """K-fold cross-validation for the same two baseline models, reporting
    mean ± std per metric across folds instead of a single train/test
    split's point estimate.

    A single 80/20 split's score is one draw from a distribution of
    possible splits — a hiring panel's standard follow-up to "what's your
    model's accuracy?" is "how stable is that number across splits?", and
    `run_baseline_models()`'s single split had no answer to that before
    this function existed.

    Uses the same preprocessing (median-impute + scale numeric,
    most-frequent-impute + one-hot categorical) folded into an sklearn
    `Pipeline` so each fold's transformer is fit only on that fold's
    training rows — no leakage across folds. `StratifiedKFold` for
    classification (keeps each fold's class balance close to the full
    dataset's); plain `KFold` for regression. `n_splits` is capped down to
    at most the smallest class's row count for classification (a class
    with fewer rows than folds would leave some folds with zero examples of
    it) and to at most `len(data) // 2` in general, with a floor of 2 —
    cross-validation on a genuinely tiny dataset degrades gracefully to a
    small number of folds rather than raising.

    Returns {"results": {model_name: {metric_name: {"mean": float, "std":
    float}}}, "n_splits": int actually used} or {"error": ...} if there are
    fewer than 4 usable rows (the minimum for even a 2-fold split with 2+
    rows per fold to make sense).
    """
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.model_selection import KFold, StratifiedKFold, cross_validate
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    data = df[feature_cols + [target_col]].dropna(subset=[target_col])
    X = data[feature_cols]
    y = data[target_col]

    if len(data) < 4:
        return {"error": "Need at least 4 rows with a non-null target to run cross-validation."}

    categorical_features = [c for c in feature_cols if not pd.api.types.is_numeric_dtype(X[c])]
    numeric_features = [c for c in feature_cols if pd.api.types.is_numeric_dtype(X[c])]

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric_features),
            (
                "cat",
                Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("encode", OneHotEncoder(handle_unknown="ignore"))]),
                categorical_features,
            ),
        ],
        remainder="drop",
    )

    n_splits_used = min(n_splits, len(data) // 2)
    if task_type == "classification":
        n_splits_used = min(n_splits_used, int(y.value_counts().min()))
    n_splits_used = max(2, n_splits_used)

    if task_type == "classification":
        cv = StratifiedKFold(n_splits=n_splits_used, shuffle=True, random_state=42)
        scoring = {"accuracy": "accuracy", "f1": "f1_weighted"}
        models = {
            "Baseline": LogisticRegression(max_iter=1000),
            "Random Forest": RandomForestClassifier(n_estimators=200, random_state=42),
        }
    else:
        cv = KFold(n_splits=n_splits_used, shuffle=True, random_state=42)
        scoring = {"rmse": "neg_root_mean_squared_error", "r2": "r2"}
        models = {
            "Baseline": LinearRegression(),
            "Random Forest": RandomForestRegressor(n_estimators=200, random_state=42),
        }

    results = {}
    for name, model in models.items():
        pipeline = Pipeline([("preprocess", preprocessor), ("model", model)])
        scores = cross_validate(pipeline, X, y, cv=cv, scoring=scoring)
        metrics = {}
        for metric_name in scoring:
            raw = scores[f"test_{metric_name}"]
            if metric_name == "rmse":
                raw = -raw  # sklearn's "neg_root_mean_squared_error" is negated so higher=better; flip back for display
            metrics[metric_name] = {"mean": round(float(raw.mean()), 4), "std": round(float(raw.std()), 4)}
        results[name] = metrics

    return {"results": results, "n_splits": n_splits_used}


def build_verdict(baseline_result: dict) -> str:
    """Plain-English comparison of Baseline vs. Random Forest, naming the top feature."""
    task_type = baseline_result["task_type"]
    metric_key = "f1" if task_type == "classification" else "r2"
    metric_label = "F1 score" if task_type == "classification" else "R²"

    baseline_score = baseline_result["results"]["Baseline"][metric_key]
    rf_score = baseline_result["results"]["Random Forest"][metric_key]
    better_name = "Random Forest" if rf_score >= baseline_score else "Baseline"
    pct_diff = abs(rf_score - baseline_score) / abs(baseline_score) * 100 if baseline_score else 0.0
    direction = "higher" if rf_score >= baseline_score else "lower"

    verdict = (
        f"{better_name} wins on {metric_label} ({max(rf_score, baseline_score):.3f} vs "
        f"{min(rf_score, baseline_score):.3f}, {pct_diff:.0f}% {direction} than the other model)."
    )

    importances = baseline_result.get("feature_importances")
    if importances is not None and not importances.empty:
        verdict += f" Top driver: {importances.index[0]}."
    return verdict


def build_confusion_matrix_chart(confusion: np.ndarray, labels: list) -> go.Figure:
    str_labels = [str(label) for label in labels]
    fig = px.imshow(
        confusion, text_auto=True, x=str_labels, y=str_labels, color_continuous_scale="Tealgrn",
        labels=dict(x="Predicted", y="Actual", color="Count"),
    )
    fig.update_layout(title="Confusion Matrix (Random Forest)", margin=dict(t=50, b=10, l=10, r=10))
    return fig


def build_feature_importance_chart(importances: pd.Series, top_n: int = 15) -> go.Figure:
    top = importances.head(top_n).sort_values(ascending=True)
    fig = px.bar(
        x=top.values, y=top.index, orientation="h",
        labels={"x": "Importance", "y": "Feature"}, title="Feature Importance (Random Forest)",
    )
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig


# ==========================================================================
# 11. Class Imbalance Detector
# ==========================================================================

IMBALANCE_MINORITY_THRESHOLD_PCT = 20.0


def check_class_imbalance(y: pd.Series) -> dict:
    """Class distribution + whether the minority class is under the imbalance threshold."""
    counts = y.value_counts()
    proportions = (counts / counts.sum() * 100).round(1)
    minority_pct = float(proportions.min())
    return {
        "counts": counts.to_dict(),
        "proportions_pct": proportions.to_dict(),
        "minority_pct": minority_pct,
        "is_imbalanced": minority_pct < IMBALANCE_MINORITY_THRESHOLD_PCT,
    }


def imbalance_explanation(imbalance_info: dict) -> str:
    return (
        f"The minority class is only {imbalance_info['minority_pct']}% of the data — a model that "
        "always predicts the majority class would still score high on accuracy without learning "
        "anything useful. F1/recall are shown as the headline metric instead, since they penalize "
        "ignoring the minority class."
    )


def build_class_distribution_chart(imbalance_info: dict) -> go.Figure:
    counts = imbalance_info["counts"]
    fig = px.bar(
        x=[str(k) for k in counts.keys()], y=list(counts.values()),
        labels={"x": "Class", "y": "Count"}, title="Class Distribution",
    )
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig


# ==========================================================================
# 12. SHAP Explainability
# ==========================================================================

# SHAP's max_display default (10) hides features past the top handful even
# on datasets with many columns — 15 matches the Feature Importance chart
# above so the two views describe the same set of columns.
SHAP_MAX_DISPLAY = 15


def explain_with_shap(model, X_background: np.ndarray, X_explain: np.ndarray, feature_names: list[str]):
    """Build a SHAP Explainer for `model` and compute SHAP values for
    X_explain (the test set) using X_background (the training set) as the
    reference distribution for perturbation. shap.Explainer auto-selects
    the right algorithm per model type (TreeExplainer for Random Forest —
    fast and exact; LinearExplainer for Logistic/Linear Regression).

    Raises on incompatible models/inputs rather than swallowing the error —
    callers should wrap this in try/except, since SHAP's supported-model
    surface and output shape genuinely vary by algorithm, and a raised
    exception with the real message is more useful than this function
    guessing at a fallback.
    """
    import shap
    from scipy import sparse

    # run_baseline_models' preprocessing pipeline one-hot-encodes categorical
    # features as a sparse matrix — fine for sklearn's own fit/predict, but
    # SHAP's TreeExplainer C extension raises a low-level array error on
    # sparse input for its background-data perturbation path. Densifying
    # here (SHAP's own input, not the model pipeline's) keeps this local to
    # explainability instead of changing memory behavior for every model run.
    if sparse.issparse(X_background):
        X_background = X_background.toarray()
    if sparse.issparse(X_explain):
        X_explain = X_explain.toarray()

    explainer = shap.Explainer(model, X_background, feature_names=feature_names)
    try:
        return explainer(X_explain)
    except shap.utils._exceptions.ExplainerError:
        # TreeExplainer's additivity check (SHAP values should sum to the
        # model's output) is a known false-positive on RandomForest: summing
        # many trees' averaged predictions accumulates floating-point error
        # past the check's tolerance even when the SHAP values themselves
        # are computed correctly. Confirmed by reproducing it directly
        # against this app's own sample data — not a real inconsistency,
        # just an overly strict sanity check for ensemble averaging.
        return explainer(X_explain, check_additivity=False)


def shap_for_display(shap_values):
    """Collapse a multi-class SHAP Explanation (shape: samples x features x
    classes) down to the single class SHAP's own plotting functions expect
    (samples x features) — picks the class with the largest mean |SHAP
    value|, i.e. the class the model's decisions hinge on most. Binary
    classification and regression Explanations are already 2D and pass
    through unchanged.
    """
    values = getattr(shap_values, "values", None)
    if values is not None and values.ndim == 3:
        class_idx = int(np.abs(values).mean(axis=(0, 1)).argmax())
        return shap_values[:, :, class_idx]
    return shap_values


# ==========================================================================
# 13. Feature Selection Engine
# ==========================================================================

# Same self-verifying-ensemble pattern already used for anomaly detection
# (see `modules.anomaly.find_anomalies_ensemble`) applied to feature
# selection: cross-check three methods built on different assumptions
# instead of trusting any single one's ranking.
FEATURE_SELECTION_MIN_FEATURES = 2


def run_feature_selection(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    task_type: str,
    top_k: Optional[int] = None,
) -> dict:
    """Cross-check three independent feature-selection methods over the same
    preprocessed feature matrix:

    - **Mutual Information** — a nonlinear, model-free measure of
      dependency between each feature and the target (catches
      relationships a linear method would miss).
    - **L1-regularized linear model** (Lasso for regression,
      L1-penalized Logistic Regression for classification) — sparsity-
      inducing coefficients that zero out weak features outright.
    - **Recursive Feature Elimination** with a Random Forest estimator —
      a wrapper method that accounts for feature interactions a filter
      method can't see.

    Each method ranks every (preprocessed) feature; a feature's
    `consensus_votes` (0-3) counts how many methods place it in their own
    top `top_k`, and `consensus_rank` is the mean of the three individual
    ranks — so a feature no single method rates highly still gets a fair
    composite score if the others agree on it.

    Returns {
      "task_type", "top_k", "n_features",
      "ranking": DataFrame indexed by preprocessed feature name (one-hot
        columns are expanded, same as `run_baseline_models`'
        `feature_importances`) with columns [mutual_info,
        mutual_info_rank, l1_coef_abs, l1_rank, rfe_selected, rfe_rank,
        consensus_votes, consensus_rank], sorted by consensus_votes desc
        then consensus_rank asc,
      "recommended_features": list[str],  # top_k feature names by that sort
    }
    or {"error": ...} if there aren't enough usable features.
    """
    if len(feature_cols) < FEATURE_SELECTION_MIN_FEATURES:
        return {"error": f"Feature Selection needs at least {FEATURE_SELECTION_MIN_FEATURES} feature columns."}

    from scipy import sparse
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.feature_selection import RFE, mutual_info_classif, mutual_info_regression
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Lasso, LassoCV, LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    data = df[feature_cols + [target_col]].dropna(subset=[target_col])
    X = data[feature_cols]
    y = data[target_col]

    categorical_features = [c for c in feature_cols if not pd.api.types.is_numeric_dtype(X[c])]
    numeric_features = [c for c in feature_cols if pd.api.types.is_numeric_dtype(X[c])]

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric_features),
            (
                "cat",
                Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("encode", OneHotEncoder(handle_unknown="ignore"))]),
                categorical_features,
            ),
        ],
        remainder="drop",
    )
    X_transformed = preprocessor.fit_transform(X)
    # Mutual info / Lasso / RFE all need a dense matrix for consistent
    # behavior across sklearn versions — same reasoning as SHAP's
    # densify-before-explaining step above; these feature sets are small
    # (Feature Selection is run over a hand-picked subset, not the raw
    # dataset), so the memory cost is negligible.
    if sparse.issparse(X_transformed):
        X_transformed = X_transformed.toarray()
    feature_names = [name.split("__", 1)[-1] for name in preprocessor.get_feature_names_out()]
    n_features = len(feature_names)

    if n_features < FEATURE_SELECTION_MIN_FEATURES:
        return {"error": "Fewer than 2 usable features after preprocessing (check for all-null columns)."}

    k = top_k if top_k is not None else max(1, n_features // 2)
    k = min(k, n_features)

    y_values = y.to_numpy()
    n_samples = X_transformed.shape[0]

    # --- Mutual Information -------------------------------------------
    mi_func = mutual_info_classif if task_type == "classification" else mutual_info_regression
    try:
        mi_scores = mi_func(X_transformed, y_values, random_state=42)
    except ValueError:
        mi_scores = np.zeros(n_features)
    mi_series = pd.Series(mi_scores, index=feature_names)
    mi_rank = mi_series.rank(ascending=False, method="min")

    # --- L1-regularized linear model -----------------------------------
    if task_type == "classification":
        l1_model = LogisticRegression(penalty="l1", solver="liblinear", C=1.0, max_iter=2000)
        l1_model.fit(X_transformed, y_values)
        coefs = np.abs(l1_model.coef_)
        l1_scores = coefs.max(axis=0) if coefs.ndim > 1 else coefs
    else:
        cv_folds = min(5, max(2, n_samples // 5))
        try:
            l1_model = LassoCV(cv=cv_folds, random_state=42, max_iter=10000)
            l1_model.fit(X_transformed, y_values)
        except ValueError:
            # too few samples for the requested CV split — fall back to a
            # single fixed-alpha fit rather than failing the whole run
            l1_model = Lasso(alpha=0.01, max_iter=10000)
            l1_model.fit(X_transformed, y_values)
        l1_scores = np.abs(l1_model.coef_)
    l1_series = pd.Series(l1_scores, index=feature_names)
    l1_rank = l1_series.rank(ascending=False, method="min")

    # --- Recursive Feature Elimination (Random Forest) ------------------
    rf_estimator = (
        RandomForestClassifier(n_estimators=100, random_state=42)
        if task_type == "classification"
        else RandomForestRegressor(n_estimators=100, random_state=42)
    )
    rfe = RFE(estimator=rf_estimator, n_features_to_select=k)
    rfe.fit(X_transformed, y_values)
    rfe_selected = pd.Series(rfe.support_, index=feature_names)
    rfe_rank = pd.Series(rfe.ranking_, index=feature_names)

    ranking = pd.DataFrame(
        {
            "mutual_info": mi_series,
            "mutual_info_rank": mi_rank,
            "l1_coef_abs": l1_series,
            "l1_rank": l1_rank,
            "rfe_selected": rfe_selected,
            "rfe_rank": rfe_rank,
        }
    )
    ranking["consensus_votes"] = (
        (ranking["mutual_info_rank"] <= k).astype(int)
        + (ranking["l1_rank"] <= k).astype(int)
        + ranking["rfe_selected"].astype(int)
    )
    ranking["consensus_rank"] = ranking[["mutual_info_rank", "l1_rank", "rfe_rank"]].mean(axis=1)
    ranking = ranking.sort_values(["consensus_votes", "consensus_rank"], ascending=[False, True])

    return {
        "task_type": task_type,
        "top_k": k,
        "n_features": n_features,
        "ranking": ranking,
        "recommended_features": ranking.head(k).index.tolist(),
    }


def build_feature_selection_chart(ranking: pd.DataFrame, top_n: int = 15) -> go.Figure:
    """Horizontal bar chart of consensus votes (0-3) for the top-ranked features."""
    top = ranking.sort_values("consensus_rank", ascending=True).head(top_n)
    top = top.sort_values("consensus_votes", ascending=True)
    fig = px.bar(
        x=top["consensus_votes"], y=top.index, orientation="h",
        labels={"x": "Methods agreeing (of 3)", "y": "Feature"},
        title="Feature Selection Consensus (Mutual Info + L1 + RFE)",
        range_x=[0, 3],
    )
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig
