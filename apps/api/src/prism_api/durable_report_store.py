"""Durable immutable chart snapshots and versioned report content."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from prism_api_contracts import (
    Report,
    ReportChartRef,
    ReportNote,
    ReportTable,
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
    Column("tables_json", Text, nullable=False),
    Column("table_history_json", Text, nullable=False),
    Column("item_order_json", Text, nullable=False),
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
            report_columns = {column["name"] for column in inspect(self.engine).get_columns("prism_reports")}
            # Add nullable columns then backfill: literal TEXT defaults are not
            # portable to MySQL. Application writes always supply these fields.
            # Repeat the backfill on startup to recover an interrupted migration.
            for column in ("tables_json", "table_history_json", "item_order_json"):
                if column not in report_columns:
                    connection.execute(text(f"ALTER TABLE prism_reports ADD COLUMN {column} TEXT"))
                connection.execute(text(f"UPDATE prism_reports SET {column} = '[]' WHERE {column} IS NULL"))

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
        return self._update_report(report, chart_refs=next_refs, item_order=[*report.item_order, chart_id])

    def replace_chart(self, report_id: str, previous_chart_id: str, chart: SavedChart) -> Report:
        report = self.get_report(report_id)
        if not any(ref.chart_id == previous_chart_id for ref in report.chart_refs):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart is not in this report.")
        refs = [
            ref.model_copy(update={"chart_id": chart.chart_id, "acknowledged_revision": chart.dataset_revision,
                                   "acknowledged_fingerprint": chart.source_fingerprint})
            if ref.chart_id == previous_chart_id else ref for ref in report.chart_refs
        ]
        return self._update_report(report, chart_refs=refs, item_order=[chart.chart_id if item == previous_chart_id else item for item in report.item_order])

    def remove_chart(self, report_id: str, chart_id: str) -> Report:
        report = self.get_report(report_id)
        next_refs = [ref for ref in report.chart_refs if ref.chart_id != chart_id]
        return self._update_report(report, chart_refs=next_refs, item_order=[item for item in report.item_order if item != chart_id])

    def add_note(self, report_id: str, text: str) -> Report:
        report = self.get_report(report_id)
        note = ReportNote(note_id=f"note_{uuid.uuid4().hex}", text=text, created_at=datetime.now(timezone.utc))
        return self._update_report(report, notes=[*report.notes, note], item_order=[*report.item_order, note.note_id])

    def remove_note(self, report_id: str, note_id: str) -> Report:
        report = self.get_report(report_id)
        return self._update_report(report, notes=[note for note in report.notes if note.note_id != note_id], item_order=[item for item in report.item_order if item != note_id])

    def add_table(self, report_id: str, table: ReportTable) -> Report:
        report = self.get_report(report_id)
        return self._update_report(report, tables=[*report.tables, table], item_order=[*report.item_order, table.table_id])

    def remove_table(self, report_id: str, table_id: str) -> Report:
        report = self.get_report(report_id)
        return self._update_report(report, tables=[table for table in report.tables if table.table_id != table_id], item_order=[item for item in report.item_order if item != table_id])

    def replace_table(self, report_id: str, previous_table_id: str, table: ReportTable) -> Report:
        report = self.get_report(report_id)
        previous = next((item for item in report.tables if item.table_id == previous_table_id), None)
        if previous is None:
            raise HTTPException(status_code=404, detail="Table is not in this report.")
        tables = [table if item.table_id == previous_table_id else item for item in report.tables]
        order = [table.table_id if item == previous_table_id else item for item in report.item_order]
        return self._update_report(report, tables=tables, table_history=[*report.table_history, previous], item_order=order)

    def reorder(self, report_id: str, item_order: list[str]) -> Report:
        report = self.get_report(report_id)
        actual = [ref.chart_id for ref in report.chart_refs] + [note.note_id for note in report.notes] + [table.table_id for table in report.tables]
        if len(item_order) != len(actual) or set(item_order) != set(actual):
            raise HTTPException(status_code=422, detail="Report order must include each current chart, note, and table exactly once.")
        return self._update_report(report, item_order=item_order)

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
                tables_json=json.dumps([table.model_dump(mode="json") for table in report.tables]),
                table_history_json=json.dumps([table.model_dump(mode="json") for table in report.table_history]),
                item_order_json=json.dumps(report.item_order),
                created_at=report.created_at, updated_at=report.updated_at,
            ))

    def _update_report(self, report: Report, chart_refs: list[ReportChartRef] | None = None, notes: list[ReportNote] | None = None, tables: list[ReportTable] | None = None, table_history: list[ReportTable] | None = None, item_order: list[str] | None = None) -> Report:
        updated = report.model_copy(update={
            "chart_refs": chart_refs if chart_refs is not None else report.chart_refs,
            "notes": notes if notes is not None else report.notes,
            "tables": tables if tables is not None else report.tables,
            "table_history": table_history if table_history is not None else report.table_history,
            "item_order": item_order if item_order is not None else report.item_order,
            "updated_at": datetime.now(timezone.utc),
        })
        with self.engine.begin() as connection:
            connection.execute(update(_reports).where(_reports.c.report_id == report.report_id).values(
                chart_refs_json=json.dumps([ref.model_dump(mode="json") for ref in updated.chart_refs]),
                notes_json=json.dumps([note.model_dump(mode="json") for note in updated.notes]),
                tables_json=json.dumps([table.model_dump(mode="json") for table in updated.tables]),
                table_history_json=json.dumps([table.model_dump(mode="json") for table in updated.table_history]),
                item_order_json=json.dumps(updated.item_order),
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
    tables = [ReportTable(**item) for item in json.loads(mapping.get("tables_json") or "[]")]
    table_history = [ReportTable(**item) for item in json.loads(mapping.get("table_history_json") or "[]")]
    order = json.loads(mapping.get("item_order_json") or "[]")
    if not order:
        order = [ref.chart_id for ref in chart_refs] + [note.note_id for note in notes] + [table.table_id for table in tables]
    return Report(report_id=mapping["report_id"], name=mapping["name"], chart_refs=chart_refs, notes=notes, tables=tables, table_history=table_history, item_order=order, created_at=mapping["created_at"], updated_at=mapping["updated_at"])
