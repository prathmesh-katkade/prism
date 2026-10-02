"""Saved charts and reports: the "save a report" step the release objective ends
on. A saved chart is an immutable record of a chart spec against a specific dataset
revision; a report composes saved charts with user notes. When a chart's source
dataset has moved on to a later revision than the report last acknowledged, the
report discloses that explicitly (needs_refresh) rather than silently presenting a
stale chart as current — and refreshing is a deliberate action, never automatic.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    ChartFreshnessStatus,
    Report,
    ReportAddChartRequest,
    ReportAddNoteRequest,
    ReportCreateRequest,
    ReportDetail,
    ReportRefreshRequest,
    SavedChart,
    SavedChartCreateRequest,
    VisualizationDataResponse,
)

from .durable_report_store import DurableReportStore
from .overview import store as overview_store
from .visualize import _aggregate, _provenance

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

store = DurableReportStore()


@router.post("/charts", response_model=SavedChart, status_code=status.HTTP_201_CREATED)
def save_chart(request: SavedChartCreateRequest) -> SavedChart:
    stored = overview_store.get(request.dataset_id)
    if ((request.source_revision is not None and request.source_revision != stored.dataset.revision) or
            (request.source_fingerprint is not None and request.source_fingerprint != stored.source_fingerprint)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chart source changed since it was rendered; render again before saving.")
    data, truncated, warnings = _aggregate(stored.frame, request.spec)
    result = VisualizationDataResponse(spec=request.spec, data=data, truncated=truncated,
                                       warnings=warnings, provenance=_provenance(stored))
    return store.save_chart(
        name=request.name, dataset_id=request.dataset_id, dataset_revision=stored.dataset.revision,
        source_fingerprint=stored.source_fingerprint, spec=request.spec, rationale=request.rationale, result=result,
    )


@router.get("/charts", response_model=list[SavedChart])
def list_charts() -> list[SavedChart]:
    return store.list_charts()


@router.get("/charts/{chart_id}", response_model=SavedChart)
def get_chart(chart_id: str) -> SavedChart:
    return store.get_chart(chart_id)


@router.post("", response_model=Report, status_code=status.HTTP_201_CREATED)
def create_report(request: ReportCreateRequest) -> Report:
    return store.create_report(request.name)


@router.get("", response_model=list[Report])
def list_reports() -> list[Report]:
    return store.list_reports()


def _freshness(report: Report) -> tuple[list[SavedChart], list[ChartFreshnessStatus]]:
    charts: list[SavedChart] = []
    freshness: list[ChartFreshnessStatus] = []
    for ref in report.chart_refs:
        chart = store.get_chart(ref.chart_id)
        charts.append(chart)
        try:
            current = overview_store.get(chart.dataset_id)
            current_revision = current.dataset.revision
            current_fingerprint = current.source_fingerprint
            freshness.append(ChartFreshnessStatus(
                chart_id=chart.chart_id, saved_revision=chart.dataset_revision, acknowledged_revision=ref.acknowledged_revision,
                current_revision=current_revision, current_fingerprint=current_fingerprint,
                needs_refresh=(current_revision != ref.acknowledged_revision or
                               current_fingerprint != (ref.acknowledged_fingerprint or chart.source_fingerprint)),
                dataset_unavailable=False,
            ))
        except HTTPException:
            freshness.append(ChartFreshnessStatus(
                chart_id=chart.chart_id, saved_revision=chart.dataset_revision, acknowledged_revision=ref.acknowledged_revision,
                current_revision=None, needs_refresh=True, dataset_unavailable=True,
            ))
    return charts, freshness


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(report_id: str) -> ReportDetail:
    report = store.get_report(report_id)
    charts, freshness = _freshness(report)
    return ReportDetail(report=report, charts=charts, freshness=freshness)


@router.post("/{report_id}/charts", response_model=ReportDetail)
def add_chart_to_report(report_id: str, request: ReportAddChartRequest) -> ReportDetail:
    chart = store.get_chart(request.chart_id)
    report = store.add_chart(report_id, request.chart_id, acknowledged_revision=chart.dataset_revision,
                             acknowledged_fingerprint=chart.source_fingerprint)
    charts, freshness = _freshness(report)
    return ReportDetail(report=report, charts=charts, freshness=freshness)


@router.delete("/{report_id}/charts/{chart_id}", response_model=ReportDetail)
def remove_chart_from_report(report_id: str, chart_id: str) -> ReportDetail:
    report = store.remove_chart(report_id, chart_id)
    charts, freshness = _freshness(report)
    return ReportDetail(report=report, charts=charts, freshness=freshness)


@router.post("/{report_id}/notes", response_model=Report)
def add_note(report_id: str, request: ReportAddNoteRequest) -> Report:
    return store.add_note(report_id, request.text)


@router.delete("/{report_id}/notes/{note_id}", response_model=Report)
def remove_note(report_id: str, note_id: str) -> Report:
    return store.remove_note(report_id, note_id)


@router.post("/{report_id}/refresh", response_model=ReportDetail)
def refresh_report(report_id: str, request: ReportRefreshRequest) -> ReportDetail:
    """Recompute selected charts against explicitly reviewed source identities.

    Each old chart and its result remain immutable and inspectable by chart id.
    Missing or changed sources fail closed before any report reference moves.
    """
    report = store.get_report(report_id)
    target_ids = set(request.chart_ids) if request.chart_ids else {ref.chart_id for ref in report.chart_refs}
    if target_ids - {ref.chart_id for ref in report.chart_refs}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A selected chart is not in this report.")
    prepared = []
    for ref in report.chart_refs:
        if ref.chart_id not in target_ids:
            continue
        chart = store.get_chart(ref.chart_id)
        try:
            current = overview_store.get(chart.dataset_id)
        except HTTPException as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Source for chart {ref.chart_id} is unavailable; refresh was not performed.") from error
        if (request.source_revisions.get(ref.chart_id) != current.dataset.revision or
                request.source_fingerprints.get(ref.chart_id) != current.source_fingerprint):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Source for chart {ref.chart_id} changed since review; reload and select its current revision and fingerprint.")
        data, truncated, warnings = _aggregate(current.frame, chart.spec)
        result = VisualizationDataResponse(spec=chart.spec, data=data, truncated=truncated,
                                           warnings=warnings, provenance=_provenance(current))
        prepared.append((chart, current, result))
    for chart, current, result in prepared:
        new_chart = store.save_chart(name=chart.name, dataset_id=chart.dataset_id,
                                     dataset_revision=current.dataset.revision,
                                     source_fingerprint=current.source_fingerprint,
                                     spec=chart.spec, rationale=chart.rationale, result=result,
                                     previous_chart_id=chart.chart_id)
        report = store.replace_chart(report_id, chart.chart_id, new_chart)
    charts, freshness = _freshness(report)
    return ReportDetail(report=report, charts=charts, freshness=freshness)


@router.post("/{report_id}/acknowledge/{chart_id}", response_model=ReportDetail)
def acknowledge_old_snapshot(report_id: str, chart_id: str) -> ReportDetail:
    """Mark a source change as seen without changing the frozen saved result."""
    report = store.get_report(report_id)
    if chart_id not in {ref.chart_id for ref in report.chart_refs}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart is not in this report.")
    chart = store.get_chart(chart_id)
    try:
        current = overview_store.get(chart.dataset_id)
    except HTTPException as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The chart source is unavailable.") from error
    report = store.acknowledge_refresh(report_id, chart_id, current.dataset.revision, current.source_fingerprint)
    charts, freshness = _freshness(report)
    return ReportDetail(report=report, charts=charts, freshness=freshness)
