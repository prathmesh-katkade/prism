"""Phase 6B native Visualize: intent-first chart specs with server-side aggregation.

Charts are described by a small, renderer-agnostic ``VisualizationSpec`` (mark +
dimension/measure/aggregation), not by calling into a specific charting library from
analytical code. Chart-type suggestion is deterministic — driven by the same column
semantic types Overview already computes — not an AI guess. Data for a chart is always
aggregated server-side (DataFrame groupby, capped category count) so the browser never
receives raw rows, and every response carries a trust warning when the aggregation
would mislead (categorical overload, an empty/degenerate measure).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    AtlasEvidence,
    AtlasVisualizeAction,
    AtlasVisualizeRequest,
    AtlasVisualizeResponse,
    OverviewColumn,
    OverviewProvenance,
    VisualizationDataResponse,
    VisualizationDatum,
    VisualizationSpec,
    VisualizationSuggestion,
    VizAggregation,
    VizIntent,
    VizMark,
)
from prism_overview_analytics import ANALYTICS_SERVICE_VERSION, build_overview

from .analytical_objects import register_visualization
from .overview import StoredDataset
from .overview import store as overview_store

router = APIRouter(prefix="/api/v1/visualize", tags=["visualize"])
DEFAULT_MAX_CATEGORIES = 20


def _column_types(frame: pd.DataFrame) -> dict[str, str]:
    columns = [OverviewColumn(**item) for item in build_overview(frame)["columns"]]
    return {column.name: column.semantic_type for column in columns}


def _require_column(frame: pd.DataFrame, column: str | None, role: str) -> str:
    if not column:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"A {role} column is required.")
    if column not in frame.columns:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {column!r} is not in the active dataset. PRISM will not chart a column that does not exist.")
    return column


@router.post("/datasets/{dataset_id}/suggest", response_model=VisualizationSuggestion)
def suggest(dataset_id: str, intent: VizIntent | None = None, dimension: str | None = None, measure: str | None = None) -> VisualizationSuggestion:
    """Deterministic mark selection: the same (intent, column-types) always yields the same mark."""
    stored = overview_store.get(dataset_id)
    types = _column_types(stored.frame)
    if dimension and dimension not in types:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {dimension!r} is not in the active dataset.")
    if measure and measure not in types:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {measure!r} is not in the active dataset.")
    if dimension is None:
        dimension = next((name for name, kind in types.items() if kind == "categorical"), None)
    if measure is None:
        measure = next((name for name, kind in types.items() if kind == "numeric" and name != dimension), None)
    dim_kind = types.get(dimension) if dimension else None
    resolved_intent = intent or (
        VizIntent.TREND if dim_kind == "datetime"
        else VizIntent.RELATIONSHIP if measure and dimension and types.get(measure) == "numeric" and dim_kind == "numeric"
        else VizIntent.DISTRIBUTION if measure and dimension is None
        else VizIntent.COMPARISON
    )
    if resolved_intent is VizIntent.TREND:
        mark, aggregation, alternatives = VizMark.LINE, VizAggregation.SUM if measure else VizAggregation.COUNT, [VizMark.BAR]
    elif resolved_intent is VizIntent.RELATIONSHIP:
        mark, aggregation, alternatives = VizMark.SCATTER, VizAggregation.NONE, []
    elif resolved_intent is VizIntent.DISTRIBUTION:
        mark, aggregation, alternatives = VizMark.HISTOGRAM, VizAggregation.NONE, [VizMark.BOX]
    elif resolved_intent is VizIntent.RANKING:
        mark, aggregation, alternatives = VizMark.BAR, VizAggregation.SUM if measure else VizAggregation.COUNT, []
    else:
        mark, aggregation, alternatives = VizMark.BAR, VizAggregation.SUM if measure else VizAggregation.COUNT, [VizMark.LINE]
    if dimension is None and mark is not VizMark.HISTOGRAM:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No categorical or datetime column is available to chart against. Try a distribution of a single numeric column instead.")
    spec = VisualizationSpec(mark=mark, intent=resolved_intent, dimension=dimension, measure=measure, aggregation=aggregation, max_categories=DEFAULT_MAX_CATEGORIES)
    rationale = f"{resolved_intent.value.capitalize()} question → {mark.value} chart" + (f" of {measure} by {dimension}." if dimension and measure else f" of {dimension or measure}.")
    return VisualizationSuggestion(spec=spec, rationale=rationale, alternatives=alternatives)


def _aggregate(frame: pd.DataFrame, spec: VisualizationSpec) -> tuple[list[VisualizationDatum], bool, list[str]]:
    warnings: list[str] = []
    if spec.mark is VizMark.HISTOGRAM:
        column = _require_column(frame, spec.measure or spec.dimension, "measure")
        numeric = pd.to_numeric(frame[column], errors="coerce").dropna()
        if numeric.empty:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{column!r} has no numeric values to build a distribution from.")
        bins = min(20, max(5, int(len(numeric) ** 0.5)))
        counts = pd.cut(numeric, bins=bins, duplicates="drop")
        table = counts.value_counts().sort_index()
        data = [VisualizationDatum(label=f"{interval.left:.2f}–{interval.right:.2f}", value=float(count)) for interval, count in table.items()]
        return data, False, warnings
    dimension = _require_column(frame, spec.dimension, "dimension")
    if spec.mark is VizMark.SCATTER:
        measure = _require_column(frame, spec.measure, "measure")
        if measure == dimension:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A relationship needs two different columns; the dimension and measure are the same column.")
        pairs = frame[[dimension, measure]].apply(pd.to_numeric, errors="coerce").dropna()
        if pairs.empty:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No numeric pairs are available for this relationship.")
        sample = pairs.sample(n=min(500, len(pairs)), random_state=0).sort_index()
        truncated = len(sample) < len(pairs)
        if truncated:
            warnings.append(f"Showing a random sample of {len(sample):,} of {len(pairs):,} points; overplotting would otherwise obscure the relationship.")
        return [VisualizationDatum(label=str(row[dimension]), value=float(row[measure])) for _, row in sample.iterrows()], truncated, warnings
    grouped = frame.groupby(dimension, dropna=True)
    if spec.aggregation is VizAggregation.COUNT or spec.measure is None:
        series = grouped.size()
    else:
        measure = _require_column(frame, spec.measure, "measure")
        numeric = pd.to_numeric(frame[measure], errors="coerce")
        series = getattr(frame.assign(**{measure: numeric}).groupby(dimension, dropna=True)[measure], spec.aggregation.value)()
    series = series.sort_values(ascending=False)
    truncated = len(series) > spec.max_categories
    if truncated:
        warnings.append(f"{len(series) - spec.max_categories} additional {dimension!r} categories are not shown (top {spec.max_categories} by value); a bar chart with this many categories would be unreadable, not just long.")
        series = series.iloc[: spec.max_categories]
    if len(series) > 12 and spec.mark is VizMark.BAR:
        warnings.append("More than 12 categories are shown; consider a Pareto/ranking view or filtering to the segment you care about.")
    return [VisualizationDatum(label=str(index), value=float(value)) for index, value in series.items()], truncated, warnings


@router.post("/datasets/{dataset_id}/render", response_model=VisualizationDataResponse)
def render(dataset_id: str, spec: VisualizationSpec) -> VisualizationDataResponse:
    stored = overview_store.get(dataset_id)
    data, truncated, warnings = _aggregate(stored.frame, spec)
    provenance = _provenance(stored)
    register_visualization(stored, spec, truncated, warnings)
    return VisualizationDataResponse(spec=spec, data=data, truncated=truncated, warnings=warnings, provenance=provenance)


def _provenance(stored: StoredDataset) -> OverviewProvenance:
    return OverviewProvenance(
        source_fingerprint=stored.source_fingerprint, dataset_revision=stored.dataset.revision,
        parameters={"renderer": "prism-native-svg/v1"}, service_version=ANALYTICS_SERVICE_VERSION, computed_at=datetime.now(timezone.utc),
    )


@router.post("/datasets/{dataset_id}/atlas", response_model=AtlasVisualizeResponse)
def atlas_action(dataset_id: str, request: AtlasVisualizeRequest) -> AtlasVisualizeResponse:
    stored = overview_store.get(dataset_id)
    data, truncated, warnings = _aggregate(stored.frame, request.spec)
    uncertainty = "This explains what the chart shows and how it was aggregated; it does not establish why a pattern exists."
    if request.action is AtlasVisualizeAction.EXPLAIN_CHART:
        top = max(data, key=lambda item: item.value) if data else None
        summary = (
            f"This {request.spec.mark.value} chart answers a {request.spec.intent.value} question"
            + (f" using {request.spec.aggregation.value} of {request.spec.measure} by {request.spec.dimension}." if request.spec.dimension else ".")
        )
        evidence = [AtlasEvidence(label="Categories shown", value=str(len(data)))]
        if top is not None:
            evidence.append(AtlasEvidence(label="Highest value", value=f"{top.label}: {top.value:,.2f}"))
        return AtlasVisualizeResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=evidence)
    if request.action is AtlasVisualizeAction.IDENTIFY_ANOMALY:
        if not data:
            return AtlasVisualizeResponse(action=request.action, summary="No data is available to inspect.", uncertainty=uncertainty, evidence=[])
        values = [item.value for item in data]
        mean, spread = sum(values) / len(values), (max(values) - min(values)) or 1
        standouts = [item for item in data if abs(item.value - mean) > 1.5 * spread / 2]
        summary = f"{len(standouts)} of {len(data)} shown categories deviate notably from the mean ({mean:,.2f})." if standouts else "No shown category deviates sharply from the others."
        return AtlasVisualizeResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=[AtlasEvidence(label=item.label, value=f"{item.value:,.2f}") for item in standouts[:5]])
    trust_notes = warnings or ["No trust issues were detected for this spec (no truncation, no overplotting sample, no missing aggregation)."]
    summary = "Trust check: " + " ".join(trust_notes)
    return AtlasVisualizeResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=[])
