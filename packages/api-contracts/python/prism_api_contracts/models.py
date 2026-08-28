from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ReleaseChannel(str, Enum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    ENABLED = "enabled"


class MigrationState(ContractModel):
    workflow: str = Field(min_length=1, max_length=100)
    channel: ReleaseChannel
    parity_required: bool = True
    legacy_reference: str = Field(min_length=1)


class HealthResponse(ContractModel):
    status: str = "ok"
    contract_version: str = "v1"
    generated_at: datetime
    migrations: tuple[MigrationState, ...]


class ApiError(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    request_id: Optional[str] = None


class OverviewDataset(ContractModel):
    dataset_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    source_name: str = Field(min_length=1)
    source_fingerprint: str = Field(min_length=16)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)


class OverviewProvenance(ContractModel):
    source_fingerprint: str = Field(min_length=16)
    dataset_revision: int = Field(ge=0)
    parameters: dict[str, object] = Field(default_factory=dict)
    service_version: str = Field(min_length=1)
    computed_at: datetime


class OutlierFinding(ContractModel):
    count: int = Field(ge=0)
    pct: float = Field(ge=0, le=100)


class OverviewQuality(ContractModel):
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    missing_by_column: dict[str, float]
    total_missing_cells: int = Field(ge=0)
    total_missing_pct: float = Field(ge=0, le=100)
    duplicate_rows: int = Field(ge=0)
    memory_usage: str
    outliers: dict[str, OutlierFinding]
    all_null_columns: list[str]


class OverviewHealth(ContractModel):
    completeness: int = Field(ge=0, le=30)
    consistency: int = Field(ge=0, le=25)
    uniqueness: int = Field(ge=0, le=15)
    validity: int = Field(ge=0, le=15)
    outlier_burden: int = Field(ge=0, le=15)
    total: int = Field(ge=0, le=100)


class DistributionBucket(ContractModel):
    label: Optional[Any]
    count: int = Field(ge=0)


class NumericSummary(ContractModel):
    min: Optional[Union[float, int, str]] = None
    max: Optional[Union[float, int, str]] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    skewness: Optional[str] = None
    kurtosis: Optional[str] = None


class OverviewColumn(ContractModel):
    name: str = Field(min_length=1)
    semantic_type: Literal["numeric", "datetime", "categorical", "text", "all_null"]
    missing_pct: float = Field(ge=0, le=100)
    unique_count: int = Field(ge=0)
    health: Literal["good", "warning", "issue"]
    issues: list[str]
    warnings: list[str]
    distribution: list[DistributionBucket]
    numeric: Optional[NumericSummary] = None


class CorrelationFinding(ContractModel):
    left: str = Field(min_length=1)
    right: str = Field(min_length=1)
    coefficient: float = Field(ge=-1, le=1)


class OverviewSuggestion(ContractModel):
    workflow: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class OverviewProfileResponse(ContractModel):
    dataset: OverviewDataset
    provenance: OverviewProvenance
    quality: OverviewQuality
    health: OverviewHealth
    columns: list[OverviewColumn]
    correlations: list[CorrelationFinding]
    suggestions: list[OverviewSuggestion]


class DatasetRowsResponse(ContractModel):
    dataset: OverviewDataset
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    total_rows: int = Field(ge=0)
    rows: list[dict[str, Optional[Any]]]
    provenance: OverviewProvenance


class AtlasOverviewAction(str, Enum):
    EXPLAIN_DATASET = "explain_dataset"
    DIAGNOSE_QUALITY = "diagnose_quality"
    INSPECT_ANOMALY = "inspect_anomaly"
    SUGGEST_NEXT_ANALYSIS = "suggest_next_analysis"
    TRACE_SOURCE = "trace_source"
    COMPARE_COLUMNS = "compare_columns"
    SUMMARIZE_RISKS = "summarize_risks"


class AtlasOverviewRequest(ContractModel):
    action: AtlasOverviewAction
    column: Optional[str] = None
    comparison_column: Optional[str] = None


class AtlasEvidence(ContractModel):
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)


class AtlasOverviewResponse(ContractModel):
    action: AtlasOverviewAction
    summary: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    evidence: list[AtlasEvidence]
    provenance: OverviewProvenance


class SqlSourceType(str, Enum):
    LOCAL_DATASET = "local_dataset"
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    SQLSERVER = "sqlserver"
    SQLITE = "sqlite"


class SqlDialect(str, Enum):
    DUCKDB = "duckdb"
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    SQLSERVER = "sqlserver"
    SQLITE = "sqlite"


class QueryExecutionState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class QueryRisk(str, Enum):
    SAFE_READ = "safe_read"
    GOVERNED_WRITE = "governed_write"
    UNKNOWN = "unknown"


class SqlCapability(ContractModel):
    name: str = Field(min_length=1)
    supported: bool
    reason: Optional[str] = None


class SqlConnectionSummary(ContractModel):
    connection_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    source_type: SqlSourceType
    dialect: SqlDialect
    status: Literal["ready", "degraded", "unavailable"]
    capabilities: list[SqlCapability]
    source_fingerprint: Optional[str] = None


class SqlColumn(ContractModel):
    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    nullable: bool
    sample_count: int = Field(ge=0)


class SqlTable(ContractModel):
    name: str = Field(min_length=1)
    columns: list[SqlColumn]


class SqlSchemaResponse(ContractModel):
    connection: SqlConnectionSummary
    tables: list[SqlTable]
    schema_fingerprint: str = Field(min_length=16)
    warnings: list[str] = Field(default_factory=list)


class SqlRunRequest(ContractModel):
    connection_id: str = Field(min_length=1)
    sql: str = Field(min_length=1, max_length=250_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=30_000, ge=100, le=120_000)
    result_limit: int = Field(default=1_000, ge=1, le=10_000)
    client_request_id: Optional[str] = Field(default=None, min_length=8, max_length=128)


class SqlResultColumn(ContractModel):
    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)


class SqlProvenance(ContractModel):
    connection_id: str = Field(min_length=1)
    source_fingerprint: str = Field(min_length=16)
    schema_fingerprint: str = Field(min_length=16)
    sql_fingerprint: str = Field(min_length=16)
    sql_version: int = Field(default=1, ge=1)
    dialect: SqlDialect
    parameters: dict[str, Any] = Field(default_factory=dict)
    service_version: str = Field(min_length=1)
    executed_at: datetime
    result_fingerprint: Optional[str] = None
    downstream_objects: list[str] = Field(default_factory=list)


class SqlRunResponse(ContractModel):
    run_id: str = Field(min_length=1)
    state: QueryExecutionState
    risk: QueryRisk
    sql: str
    result_columns: list[SqlResultColumn] = Field(default_factory=list)
    row_count: int = Field(default=0, ge=0)
    returned_row_count: int = Field(default=0, ge=0)
    truncated: bool = False
    duration_ms: Optional[int] = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    provenance: SqlProvenance


class SqlResultPageResponse(ContractModel):
    run: SqlRunResponse
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=1_000)
    rows: list[dict[str, Optional[Any]]]


class SqlResultPromotionResponse(ContractModel):
    run: SqlRunResponse
    dataset: OverviewDataset


class SqlPlanResponse(ContractModel):
    connection_id: str = Field(min_length=1)
    supported: bool
    plan: list[str] = Field(default_factory=list)
    warning: Optional[str] = None


class SqlSnippet(ContractModel):
    snippet_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    sql: str = Field(min_length=1, max_length=250_000)
    dialect: SqlDialect
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SqlSnippetCreate(ContractModel):
    name: str = Field(min_length=1, max_length=120)
    sql: str = Field(min_length=1, max_length=250_000)
    dialect: SqlDialect
    parameters: dict[str, Any] = Field(default_factory=dict)


class AtlasSqlAction(str, Enum):
    EXPLAIN_QUERY = "explain_query"
    OPTIMIZE_QUERY = "optimize_query"
    DEBUG_ERROR = "debug_error"
    INSPECT_PLAN = "inspect_plan"
    GENERATE_SQL = "generate_sql"
    COMPARE_QUERIES = "compare_queries"
    EXPLAIN_SELECTION = "explain_selection"
    TRACE_LINEAGE = "trace_lineage"
    CONVERT_RESULT = "convert_result"


class AtlasSqlRequest(ContractModel):
    action: AtlasSqlAction
    connection_id: str = Field(min_length=1)
    sql: Optional[str] = Field(default=None, max_length=250_000)
    selected_text: Optional[str] = Field(default=None, max_length=50_000)
    intent: Optional[str] = Field(default=None, max_length=2_000)
    comparison_sql: Optional[str] = Field(default=None, max_length=250_000)


class AtlasSqlResponse(ContractModel):
    action: AtlasSqlAction
    summary: str = Field(min_length=1)
    draft_sql: Optional[str] = None
    evidence: list[AtlasEvidence]
    uncertainty: str = Field(min_length=1)
    executable: bool = False


class AiAnalystOutcome(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SQL_READY = "sql_ready"
    PROVIDER_FALLBACK = "provider_fallback"


class AiProviderStatus(str, Enum):
    DETERMINISTIC = "deterministic"
    OLLAMA = "ollama"
    FALLBACK = "fallback"


class AiAnalystRequest(ContractModel):
    question: str = Field(min_length=3, max_length=4_000)
    dataset_id: Optional[str] = Field(default=None, min_length=1)
    result_run_id: Optional[str] = Field(default=None, min_length=1)
    follow_up_to: Optional[str] = Field(default=None, min_length=1)


class AiEvidence(ContractModel):
    kind: Literal["dataset", "quality", "column", "correlation", "sql_result", "limitation"]
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=1_000)
    provenance_ref: str = Field(min_length=1, max_length=200)


class AiContextPacket(ContractModel):
    dataset_id: str = Field(min_length=1)
    source_fingerprint: str = Field(min_length=16)
    column_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    raw_sample_rows: int = Field(ge=0, le=12)
    token_budget: int = Field(ge=1, le=8_000)
    prompt_version: str = Field(min_length=1)
    config_version: str = Field(min_length=1)
    result_run_id: Optional[str] = None


class AiAnalystResponse(ContractModel):
    request_id: str = Field(min_length=1)
    outcome: AiAnalystOutcome
    answer: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    limiting_factors: list[str] = Field(default_factory=list)
    recommended_next_step: str = Field(min_length=1)
    evidence: list[AiEvidence]
    context: AiContextPacket
    provider: AiProviderStatus
    sql_draft: Optional[str] = Field(default=None, max_length=250_000)
    sql_connection_id: Optional[str] = None
    provenance: dict[str, Any] = Field(default_factory=dict)
