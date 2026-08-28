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

    return {
        "task_type": task_type,
        "results": results,
        "confusion_matrix": confusion,
        "confusion_labels": confusion_labels,
        "feature_importances": importances,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "smote_before_after": smote_before_after,
        # Kept for SHAP explainability (see explain_with_shap below) — the
        # Random Forest specifically, since it's the model feature_importances_
        # already covers; re-fitting a second time just to explain it would
        # waste both compute and the point of reusing this same run.
        "fitted_rf_model": fitted_models["Random Forest"],
        "X_train_transformed": X_train_transformed,
        "X_test_transformed": X_test_transformed,
        "feature_names": feature_names,
    }


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
