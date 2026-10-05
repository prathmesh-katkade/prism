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
    BoxStats,
    ChartDrillDownRequest,
    ChartDrillDownResponse,
    OverviewColumn,
    OverviewProvenance,
    VisualizationDataResponse,
    VisualizationDatum,
    VisualizationFacet,
    VisualizationSpec,
    VisualizationSuggestion,
    VizAggregation,
    VizIntent,
    VizMark,
)
from prism_overview_analytics import ANALYTICS_SERVICE_VERSION, build_overview

from .analytical_objects import register_visualization
from .clean import _json_value
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


def _filtered_frame(frame: pd.DataFrame, spec: VisualizationSpec) -> pd.DataFrame:
    """Apply saved chart filters for rendering and mark inspection alike."""
    result = frame
    for column, expected in spec.filters.items():
        _require_column(frame, column, "filter")
        if isinstance(expected, list):
            if any(isinstance(item, (dict, list)) for item in expected):
                raise HTTPException(status_code=422, detail=f"Filter {column!r} must contain scalar values.")
            result = result.loc[result[column].isin(expected)]
        elif expected is None:
            result = result.loc[result[column].isna()]
        elif isinstance(expected, (str, int, float, bool)):
            result = result.loc[result[column].astype(str) == str(expected)]
        else:
            raise HTTPException(status_code=422, detail=f"Filter {column!r} must be a scalar or list of scalars.")
    return result


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
    frame = _filtered_frame(frame, spec)
    if frame.empty:
        raise HTTPException(status_code=422, detail="The chart filters leave no rows to render.")
    if spec.mark is VizMark.HISTOGRAM:
        column = _require_column(frame, spec.measure or spec.dimension, "measure")
        numeric = pd.to_numeric(frame[column], errors="coerce").dropna()
        if numeric.empty:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{column!r} has no numeric values to build a distribution from.")
        bins = spec.histogram_bins or min(20, max(5, int(len(numeric) ** 0.5)))
        counts = pd.cut(numeric, bins=bins, duplicates="drop")
        table = counts.value_counts().sort_index()
        data = [VisualizationDatum(label=f"{interval.left:.2f}–{interval.right:.2f}", value=float(count), bin_start=float(interval.left), bin_end=float(interval.right)) for interval, count in table.items()]
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
        return [
            VisualizationDatum(label=f"{dimension}={row[dimension]:,.2f}, {measure}={row[measure]:,.2f}", value=float(row[measure]), x=float(row[dimension]))
            for _, row in sample.iterrows()
        ], truncated, warnings
    if spec.mark is VizMark.BOX:
        measure = _require_column(frame, spec.measure, "measure")
        numeric = pd.to_numeric(frame[measure], errors="coerce")
        working = frame.assign(**{measure: numeric}).dropna(subset=[measure, dimension])
        if working.empty:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"No numeric {measure!r} values are available to summarize per {dimension!r} group.")
        boxes: list[tuple[str, float, BoxStats]] = []
        for key, values in working.groupby(dimension, dropna=True)[measure]:
            if values.empty:
                continue
            q1, q2, q3 = (float(value) for value in values.quantile([0.25, 0.5, 0.75]))
            iqr = q3 - q1
            lower_fence, upper_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            within = values[(values >= lower_fence) & (values <= upper_fence)]
            outliers = sorted(float(value) for value in values[(values < lower_fence) | (values > upper_fence)])
            boxes.append((str(key), q2, BoxStats(
                q1=q1, median=q2, q3=q3,
                whisker_low=float(within.min()) if not within.empty else q1,
                whisker_high=float(within.max()) if not within.empty else q3,
                outliers=outliers,
            )))
        boxes.sort(key=lambda item: item[1], reverse=True)
        truncated = len(boxes) > spec.max_categories
        if truncated:
            warnings.append(f"{len(boxes) - spec.max_categories} additional {dimension!r} groups are not shown (top {spec.max_categories} by median); this many box plots side by side would be unreadable.")
            boxes = boxes[: spec.max_categories]
        return [VisualizationDatum(label=label, value=median, box=box) for label, median, box in boxes], truncated, warnings
    grouped = frame.groupby(dimension, dropna=True)
    if spec.aggregation is VizAggregation.NONE and spec.measure is not None:
        raise HTTPException(status_code=422, detail="Grouped bar and line charts need count, sum, mean, or median aggregation.")
    if spec.aggregation is VizAggregation.COUNT or spec.measure is None:
        series = grouped.size()
    else:
        measure = _require_column(frame, spec.measure, "measure")
        numeric = pd.to_numeric(frame[measure], errors="coerce")
        series = getattr(frame.assign(**{measure: numeric}).groupby(dimension, dropna=True)[measure], spec.aggregation.value)()
    if spec.mark is VizMark.LINE:
        # A trend reads left-to-right in the dimension's own order (chronological for
        # a datetime axis); sorting by value instead -- as the ranking branch below
        # does -- would scramble the line into a meaningless zig-zag.
        series = series.sort_index()
        truncated = len(series) > spec.max_categories
        if truncated:
            warnings.append(f"{len(series) - spec.max_categories} additional {dimension!r} points are not shown (first {spec.max_categories} in sequence); narrow the date range instead of viewing a truncated trend.")
            series = series.iloc[: spec.max_categories]
    else:
        series = series.sort_values(ascending=False)
        truncated = len(series) > spec.max_categories
        if truncated:
            warnings.append(f"{len(series) - spec.max_categories} additional {dimension!r} categories are not shown (top {spec.max_categories} by value); a bar chart with this many categories would be unreadable, not just long.")
            series = series.iloc[: spec.max_categories]
        if len(series) > 12 and spec.mark is VizMark.BAR:
            warnings.append("More than 12 categories are shown; consider a Pareto/ranking view or filtering to the segment you care about.")
    return [VisualizationDatum(label=str(index), value=float(value)) for index, value in series.items()], truncated, warnings


def _facets(frame: pd.DataFrame, spec: VisualizationSpec) -> tuple[list[VisualizationFacet], list[str]]:
    if not spec.facet:
        return [], []
    if spec.mark not in {VizMark.BAR, VizMark.LINE}:
        raise HTTPException(status_code=422, detail="Shared-scale small multiples currently support bar and line charts.")
    column = _require_column(frame, spec.facet, "facet")
    filtered = _filtered_frame(frame, spec)
    values = sorted(str(value) for value in filtered[column].dropna().unique())
    if not values:
        raise HTTPException(status_code=422, detail=f"Facet {column!r} has no non-missing values after filtering.")
    warnings = [f"Showing the first 6 of {len(values)} {column!r} panels; filter the source to inspect the others."] if len(values) > 6 else []
    facets: list[VisualizationFacet] = []
    for value in values[:6]:
        panel_spec = spec.model_copy(update={"facet": None, "filters": {**spec.filters, column: value}})
        data, _, panel_warnings = _aggregate(frame, panel_spec)
        warnings.extend(f"{column}={value}: {warning}" for warning in panel_warnings)
        facets.append(VisualizationFacet(value=value, data=data))
    return facets, warnings


@router.post("/datasets/{dataset_id}/render", response_model=VisualizationDataResponse)
def render(dataset_id: str, spec: VisualizationSpec) -> VisualizationDataResponse:
    stored = overview_store.get(dataset_id)
    data, truncated, warnings = _aggregate(stored.frame, spec)
    facets, facet_warnings = _facets(stored.frame, spec)
    warnings.extend(facet_warnings)
    provenance = _provenance(stored)
    register_visualization(stored, spec, truncated, warnings)
    return VisualizationDataResponse(spec=spec, data=data, truncated=truncated, warnings=warnings, provenance=provenance, facets=facets)


DRILL_DOWN_SAMPLE_LIMIT = 500


@router.post("/datasets/{dataset_id}/drilldown", response_model=ChartDrillDownResponse)
def drill_down(dataset_id: str, request: ChartDrillDownRequest) -> ChartDrillDownResponse:
    """Resolve a single clicked mark back to its contributing rows, server-side —
    never by shipping the whole dataset to the browser so it can filter locally."""
    stored = overview_store.get(dataset_id)
    frame = _filtered_frame(stored.frame, request.spec)
    spec = request.spec
    filters_applied: dict[str, object] = {}
    if spec.mark is VizMark.HISTOGRAM:
        measure = _require_column(frame, spec.measure or spec.dimension, "measure")
        if request.bin_start is None or request.bin_end is None:
            raise HTTPException(status_code=422, detail="bin_start and bin_end are required to inspect a histogram bin.")
        numeric = pd.to_numeric(frame[measure], errors="coerce")
        mask = numeric.gt(request.bin_start) & numeric.le(request.bin_end)
        filters_applied = {**spec.filters, measure: {"greater_than": request.bin_start, "less_than_or_equal": request.bin_end}}
    elif spec.mark is VizMark.SCATTER:
        dimension = _require_column(frame, spec.dimension, "dimension")
        measure = _require_column(frame, spec.measure, "measure")
        if request.x_value is None or request.y_value is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Both x_value and y_value are required to drill into a scatter point.")
        dim_numeric = pd.to_numeric(frame[dimension], errors="coerce").round(6)
        measure_numeric = pd.to_numeric(frame[measure], errors="coerce").round(6)
        mask = (dim_numeric == round(request.x_value, 6)) & (measure_numeric == round(request.y_value, 6))
        filters_applied = {**spec.filters, dimension: request.x_value, measure: request.y_value}
    else:
        dimension = _require_column(frame, spec.dimension, "dimension")
        if request.dimension_value is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="dimension_value is required to drill into this mark.")
        mask = frame[dimension].astype(str) == request.dimension_value
        filters_applied = {**spec.filters, dimension: request.dimension_value}
    matching = frame.loc[mask]
    total = len(matching)
    limit = min(request.limit, DRILL_DOWN_SAMPLE_LIMIT)
    page = matching.iloc[request.offset: request.offset + limit]
    rows = [{str(key): _json_value(value) for key, value in row.items()} for row in page.to_dict(orient="records")]
    return ChartDrillDownResponse(
        total_matching_rows=total, rows=rows, offset=request.offset, limit=limit,
        truncated=total > request.offset + limit, filters_applied=filters_applied,
    )


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
