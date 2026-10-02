"""Durable store for saved charts and reports.

A SavedChart is append-only and immutable once created (captures the spec,
rationale, and the dataset revision/fingerprint it was saved against — a frozen
record of "this chart, against this data, as of this point"). A Report references
charts by id and tracks, per reference, the dataset revision the user last
explicitly acknowledged ("refreshed") — comparing that against the dataset's
*current* revision is what drives the needs_refresh flag. Refreshing never rewrites
a SavedChart or silently changes what a report's saved charts mean; it only updates
which revision has been acknowledged, and when.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from prism_api_contracts import (
    Report,
    ReportChartRef,
    ReportNote,
    SavedChart,
    VisualizationDataResponse,
    VisualizationSpec,
)
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    inspect,
    select,
    text,
    update,
)

from .durable_registry import history_database_url

_metadata = MetaData()
_charts = Table(
    "prism_saved_charts", _metadata,
    Column("chart_id", String(255), primary_key=True),
    Column("name", String(500), nullable=False),
    Column("dataset_id", String(255), nullable=False, index=True),
    Column("dataset_revision", Integer, nullable=False),
    Column("source_fingerprint", String(255), nullable=False),
    Column("spec_json", Text, nullable=False),
    Column("rationale", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("result_json", Text, nullable=True),
    Column("previous_chart_id", String(255), nullable=True),
)
_reports = Table(
    "prism_reports", _metadata,
    Column("report_id", String(255), primary_key=True),
    Column("name", String(500), nullable=False),
    Column("chart_refs_json", Text, nullable=False),
    Column("notes_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class DurableReportStore:
    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or history_database_url()
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        _metadata.create_all(self.engine)
        existing = {column["name"] for column in inspect(self.engine).get_columns("prism_saved_charts")}
        with self.engine.begin() as connection:
            if "result_json" not in existing:
                connection.execute(text("ALTER TABLE prism_saved_charts ADD COLUMN result_json TEXT"))
            if "previous_chart_id" not in existing:
                connection.execute(text("ALTER TABLE prism_saved_charts ADD COLUMN previous_chart_id VARCHAR(255)"))

    # -- saved charts ----------------------------------------------------
    def save_chart(self, name: str, dataset_id: str, dataset_revision: int, source_fingerprint: str, spec: VisualizationSpec, rationale: str, result: VisualizationDataResponse, previous_chart_id: str | None = None) -> SavedChart:
        chart = SavedChart(
            chart_id=f"chart_{uuid.uuid4().hex}", name=name, dataset_id=dataset_id, dataset_revision=dataset_revision,
            source_fingerprint=source_fingerprint, spec=spec, rationale=rationale, created_at=datetime.now(timezone.utc),
            result=result, previous_chart_id=previous_chart_id,
        )
        with self.engine.begin() as connection:
            connection.execute(insert(_charts).values(
                chart_id=chart.chart_id, name=chart.name, dataset_id=chart.dataset_id, dataset_revision=chart.dataset_revision,
                source_fingerprint=chart.source_fingerprint, spec_json=chart.spec.model_dump_json(), rationale=chart.rationale,
                created_at=chart.created_at, result_json=chart.result.model_dump_json() if chart.result else None,
                previous_chart_id=chart.previous_chart_id,
            ))
        return chart

    def list_charts(self) -> list[SavedChart]:
        with self.engine.begin() as connection:
            rows = connection.execute(select(_charts).order_by(_charts.c.created_at.desc())).mappings().all()
        return [_row_to_chart(row) for row in rows]

    def get_chart(self, chart_id: str) -> SavedChart:
        with self.engine.begin() as connection:
            row = connection.execute(select(_charts).where(_charts.c.chart_id == chart_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Saved chart {chart_id!r} was not found.")
        return _row_to_chart(row)

    # -- reports -----------------------------------------------------------
    def create_report(self, name: str) -> Report:
        now = datetime.now(timezone.utc)
        report = Report(report_id=f"report_{uuid.uuid4().hex}", name=name, chart_refs=[], notes=[], created_at=now, updated_at=now)
        self._insert_report(report)
        return report

    def list_reports(self) -> list[Report]:
        with self.engine.begin() as connection:
            rows = connection.execute(select(_reports).order_by(_reports.c.updated_at.desc())).mappings().all()
        return [_row_to_report(row) for row in rows]

    def get_report(self, report_id: str) -> Report:
        with self.engine.begin() as connection:
            row = connection.execute(select(_reports).where(_reports.c.report_id == report_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Report {report_id!r} was not found.")
        return _row_to_report(row)

    def add_chart(self, report_id: str, chart_id: str, acknowledged_revision: int, acknowledged_fingerprint: str | None = None) -> Report:
        report = self.get_report(report_id)
        if any(ref.chart_id == chart_id for ref in report.chart_refs):
            return report
        next_refs = [*report.chart_refs, ReportChartRef(chart_id=chart_id, acknowledged_revision=acknowledged_revision, acknowledged_fingerprint=acknowledged_fingerprint, added_at=datetime.now(timezone.utc))]
        return self._update_report(report, chart_refs=next_refs)

    def replace_chart(self, report_id: str, previous_chart_id: str, chart: SavedChart) -> Report:
        report = self.get_report(report_id)
        if not any(ref.chart_id == previous_chart_id for ref in report.chart_refs):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart is not in this report.")
        refs = [
            ref.model_copy(update={"chart_id": chart.chart_id, "acknowledged_revision": chart.dataset_revision,
                                   "acknowledged_fingerprint": chart.source_fingerprint})
            if ref.chart_id == previous_chart_id else ref for ref in report.chart_refs
        ]
        return self._update_report(report, chart_refs=refs)

    def remove_chart(self, report_id: str, chart_id: str) -> Report:
        report = self.get_report(report_id)
        next_refs = [ref for ref in report.chart_refs if ref.chart_id != chart_id]
        return self._update_report(report, chart_refs=next_refs)

    def add_note(self, report_id: str, text: str) -> Report:
        report = self.get_report(report_id)
        note = ReportNote(note_id=f"note_{uuid.uuid4().hex}", text=text, created_at=datetime.now(timezone.utc))
        return self._update_report(report, notes=[*report.notes, note])

    def remove_note(self, report_id: str, note_id: str) -> Report:
        report = self.get_report(report_id)
        return self._update_report(report, notes=[note for note in report.notes if note.note_id != note_id])

    def acknowledge_refresh(self, report_id: str, chart_id: str, revision: int, fingerprint: str) -> Report:
        report = self.get_report(report_id)
        next_refs = [
            ref.model_copy(update={"acknowledged_revision": revision, "acknowledged_fingerprint": fingerprint}) if ref.chart_id == chart_id else ref
            for ref in report.chart_refs
        ]
        return self._update_report(report, chart_refs=next_refs)

    def _insert_report(self, report: Report) -> None:
        with self.engine.begin() as connection:
            connection.execute(insert(_reports).values(
                report_id=report.report_id, name=report.name,
                chart_refs_json=json.dumps([ref.model_dump(mode="json") for ref in report.chart_refs]),
                notes_json=json.dumps([note.model_dump(mode="json") for note in report.notes]),
                created_at=report.created_at, updated_at=report.updated_at,
            ))

    def _update_report(self, report: Report, chart_refs: list[ReportChartRef] | None = None, notes: list[ReportNote] | None = None) -> Report:
        updated = report.model_copy(update={
            "chart_refs": chart_refs if chart_refs is not None else report.chart_refs,
            "notes": notes if notes is not None else report.notes,
            "updated_at": datetime.now(timezone.utc),
        })
        with self.engine.begin() as connection:
            connection.execute(update(_reports).where(_reports.c.report_id == report.report_id).values(
                chart_refs_json=json.dumps([ref.model_dump(mode="json") for ref in updated.chart_refs]),
                notes_json=json.dumps([note.model_dump(mode="json") for note in updated.notes]),
                updated_at=updated.updated_at,
            ))
        return updated


def _row_to_chart(row: object) -> SavedChart:
    mapping = dict(row)  # type: ignore[call-overload]
    return SavedChart(
        chart_id=mapping["chart_id"], name=mapping["name"], dataset_id=mapping["dataset_id"],
        dataset_revision=mapping["dataset_revision"], source_fingerprint=mapping["source_fingerprint"],
        spec=VisualizationSpec.model_validate_json(mapping["spec_json"]), rationale=mapping["rationale"], created_at=mapping["created_at"],
        result=VisualizationDataResponse.model_validate_json(mapping["result_json"]) if mapping.get("result_json") else None,
        previous_chart_id=mapping.get("previous_chart_id"),
    )


def _row_to_report(row: object) -> Report:
    mapping = dict(row)  # type: ignore[call-overload]
    chart_refs = [ReportChartRef(**item) for item in json.loads(mapping["chart_refs_json"])]
    notes = [ReportNote(**item) for item in json.loads(mapping["notes_json"])]
    return Report(report_id=mapping["report_id"], name=mapping["name"], chart_refs=chart_refs, notes=notes, created_at=mapping["created_at"], updated_at=mapping["updated_at"])
