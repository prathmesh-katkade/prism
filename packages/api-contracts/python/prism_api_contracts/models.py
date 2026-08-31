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


class ProviderReadiness(ContractModel):
    """Diagnostic configuration status for one optional dependency — never a live network probe
    (a readiness check must stay fast and must not itself hang on an external service), and never
    used to fail readiness on its own: PRISM's deterministic path works with every optional
    provider unconfigured or unreachable."""

    name: str = Field(min_length=1)
    status: Literal["configured", "not_configured"]
    detail: str = Field(min_length=1)


class ReadinessResponse(ContractModel):
    status: Literal["ready"] = "ready"
    contract_version: str = "v1"
    generated_at: datetime
    providers: tuple[ProviderReadiness, ...]


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


# --- Phase 6A: Clean ---------------------------------------------------------


class CleanIssueKind(str, Enum):
    MISSING_VALUES = "missing_values"
    DUPLICATE_ROWS = "duplicate_rows"
    ALL_NULL_COLUMN = "all_null_column"
    TYPE_MISMATCH = "type_mismatch"
    OUTLIER_BURDEN = "outlier_burden"


class CleanOperation(str, Enum):
    DROP_DUPLICATES = "drop_duplicates"
    FILL_MISSING = "fill_missing"
    DROP_MISSING_ROWS = "drop_missing_rows"
    CONVERT_TYPE = "convert_type"
    RENAME_COLUMN = "rename_column"
    DROP_COLUMN = "drop_column"
    TRIM_WHITESPACE = "trim_whitespace"
    NORMALIZE_CASE = "normalize_case"


class FillStrategy(str, Enum):
    MEAN = "mean"
    MEDIAN = "median"
    MODE = "mode"
    CONSTANT = "constant"
    FORWARD_FILL = "forward_fill"


class CleanIssue(ContractModel):
    issue_id: str = Field(min_length=1)
    kind: CleanIssueKind
    column: Optional[str] = None
    severity: Literal["low", "medium", "high"]
    affected_rows: int = Field(ge=0)
    description: str = Field(min_length=1)
    suggested_operation: Optional[CleanOperation] = None


class CleanTransformationRequest(ContractModel):
    operation: CleanOperation
    column: Optional[str] = Field(default=None, min_length=1)
    new_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    target_type: Optional[Literal["numeric", "text", "datetime", "boolean"]] = None
    fill_strategy: Optional[FillStrategy] = None
    fill_value: Optional[str] = None
    case: Optional[Literal["lower", "upper", "title"]] = None


class CleanTransformation(ContractModel):
    transformation_id: str = Field(min_length=1)
    operation: CleanOperation
    column: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    affected_rows: int = Field(ge=0)
    affected_columns: list[str] = Field(default_factory=list)
    source_revision: int = Field(ge=0)
    resulting_revision: int = Field(ge=0)
    source_fingerprint: str = Field(min_length=16)
    resulting_fingerprint: str = Field(min_length=16)
    reversible: bool = True
    created_at: datetime


class CleanPreviewResponse(ContractModel):
    operation: CleanOperation
    affected_rows: int = Field(ge=0)
    affected_columns: list[str] = Field(default_factory=list)
    before_sample: list[dict[str, Optional[Any]]]
    after_sample: list[dict[str, Optional[Any]]]
    warnings: list[str] = Field(default_factory=list)
    projected_health: OverviewHealth


class CleanApplyResponse(ContractModel):
    dataset: OverviewDataset
    transformation: CleanTransformation
    issues: list[CleanIssue]
    health: OverviewHealth


class CleanStateResponse(ContractModel):
    dataset: OverviewDataset
    issues: list[CleanIssue]
    history: list[CleanTransformation]
    health: OverviewHealth


class CleanUndoRequest(ContractModel):
    to_revision: int = Field(ge=0)


class AtlasCleanAction(str, Enum):
    EXPLAIN_ISSUE = "explain_issue"
    PROPOSE_FIX = "propose_fix"
    COMPARE_BEFORE_AFTER = "compare_before_after"


class AtlasCleanRequest(ContractModel):
    action: AtlasCleanAction
    issue_id: Optional[str] = None


class AtlasCleanResponse(ContractModel):
    action: AtlasCleanAction
    summary: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    evidence: list[AtlasEvidence]
    proposed_operation: Optional[CleanTransformationRequest] = None


# --- Phase 6B: Visualize ------------------------------------------------------


class VizMark(str, Enum):
    BAR = "bar"
    LINE = "line"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    BOX = "box"


class VizIntent(str, Enum):
    COMPARISON = "comparison"
    DISTRIBUTION = "distribution"
    RELATIONSHIP = "relationship"
    COMPOSITION = "composition"
    TREND = "trend"
    RANKING = "ranking"


class VizAggregation(str, Enum):
    COUNT = "count"
    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    NONE = "none"


class VisualizationSpec(ContractModel):
    mark: VizMark
    intent: VizIntent
    dimension: Optional[str] = None
    measure: Optional[str] = None
    aggregation: VizAggregation
    filters: dict[str, Any] = Field(default_factory=dict)
    max_categories: int = Field(default=20, ge=1, le=200)


class VisualizationSuggestion(ContractModel):
    spec: VisualizationSpec
    rationale: str = Field(min_length=1)
    alternatives: list[VizMark] = Field(default_factory=list)


class VisualizationDatum(ContractModel):
    label: str
    value: float


class VisualizationDataResponse(ContractModel):
    spec: VisualizationSpec
    data: list[VisualizationDatum]
    truncated: bool
    warnings: list[str] = Field(default_factory=list)
    provenance: OverviewProvenance


class AtlasVisualizeAction(str, Enum):
    EXPLAIN_CHART = "explain_chart"
    IDENTIFY_ANOMALY = "identify_anomaly"
    PROPOSE_ALTERNATIVE = "propose_alternative"


class AtlasVisualizeRequest(ContractModel):
    action: AtlasVisualizeAction
    spec: VisualizationSpec


class AtlasVisualizeResponse(ContractModel):
    action: AtlasVisualizeAction
    summary: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    evidence: list[AtlasEvidence]


# --- Phase 7A: Stats Lab -------------------------------------------------------


class StatTestKind(str, Enum):
    TTEST = "ttest"
    ANOVA = "anova"
    CHI2 = "chi2"
    PEARSON = "pearson"


class StatNormalityCheck(ContractModel):
    subject: str = Field(min_length=1)
    p_value: Optional[float] = None
    is_normal: Optional[bool] = None
    note: str = ""


class StatSuggestionResponse(ContractModel):
    col_a: str = Field(min_length=1)
    col_b: str = Field(min_length=1)
    test: Optional[StatTestKind] = None
    reason: Optional[str] = None
    numeric_col: Optional[str] = None
    cat_col: Optional[str] = None
    error: Optional[str] = None


class StatTestRequest(ContractModel):
    test: StatTestKind
    col_a: str = Field(min_length=1)
    col_b: str = Field(min_length=1)
    numeric_col: Optional[str] = None
    cat_col: Optional[str] = None


class StatTestResult(ContractModel):
    test: StatTestKind
    statistic: float
    p_value: float = Field(ge=0, le=1)
    effect_size: float
    effect_size_name: str = Field(min_length=1)
    effect_size_label: Literal["negligible", "small", "medium", "large"]
    groups: dict[str, int] = Field(default_factory=dict)
    means: dict[str, float] = Field(default_factory=dict)
    dof: Optional[int] = None
    n: Optional[int] = None
    low_expected_pct: Optional[float] = None
    normality: list[StatNormalityCheck] = Field(default_factory=list)
    significant: bool
    interpretation: str = Field(min_length=1)
    evidence_statement: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    provenance: OverviewProvenance


class AtlasStatsAction(str, Enum):
    EXPLAIN_TEST = "explain_test"
    EXPLAIN_ASSUMPTIONS = "explain_assumptions"
    EXPLAIN_EFFECT_SIZE = "explain_effect_size"
    RECOMMEND_NEXT_STEP = "recommend_next_step"


class AtlasStatsRequest(ContractModel):
    action: AtlasStatsAction
    col_a: str = Field(min_length=1)
    col_b: str = Field(min_length=1)


class AtlasStatsResponse(ContractModel):
    action: AtlasStatsAction
    summary: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    evidence: list[AtlasEvidence]


# --- Phase 7B: Forecasting -----------------------------------------------------


class ForecastPoint(ContractModel):
    timestamp: datetime
    value: float


class ForecastInterval(ContractModel):
    timestamp: datetime
    lower: float
    upper: float


class ForecastMetrics(ContractModel):
    mae: Optional[float] = None
    rmse: Optional[float] = None
    mape: Optional[float] = None
    holdout_points: int = Field(default=0, ge=0)
    note: str = ""


class ForecastRequest(ContractModel):
    datetime_col: str = Field(min_length=1)
    numeric_col: str = Field(min_length=1)
    horizon: int = Field(default=12, ge=1, le=365)


class ForecastResult(ContractModel):
    datetime_col: str
    numeric_col: str
    frequency: str
    model_used: str = Field(min_length=1)
    horizon: int = Field(ge=1)
    observed: list[ForecastPoint]
    forecast: list[ForecastPoint]
    intervals: list[ForecastInterval]
    metrics: ForecastMetrics
    caveat: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    provenance: OverviewProvenance


class DecomposeRequest(ContractModel):
    datetime_col: str = Field(min_length=1)
    numeric_col: str = Field(min_length=1)


class DecompositionResult(ContractModel):
    datetime_col: str
    numeric_col: str
    seasonal_period: int = Field(ge=1)
    trend_strength: float = Field(ge=0, le=1)
    seasonal_strength: float = Field(ge=0, le=1)
    observed: list[ForecastPoint]
    trend: list[ForecastPoint]
    seasonal: list[ForecastPoint]
    resid: list[ForecastPoint]
    verdict: str = Field(min_length=1)
    provenance: OverviewProvenance


class ChangepointRequest(ContractModel):
    datetime_col: str = Field(min_length=1)
    numeric_col: str = Field(min_length=1)
    max_changepoints: int = Field(default=5, ge=1, le=20)


class ChangepointFinding(ContractModel):
    position: int = Field(ge=0)
    timestamp: datetime
    before_mean: float
    after_mean: float
    delta: float
    pct_change: Optional[float] = None
    before_n: int = Field(ge=0)
    after_n: int = Field(ge=0)


class ChangepointResult(ContractModel):
    datetime_col: str
    numeric_col: str
    observed: list[ForecastPoint]
    changepoints: list[ChangepointFinding]
    n_segments: int = Field(ge=1)
    verdict: str = Field(min_length=1)
    provenance: OverviewProvenance


class AtlasForecastAction(str, Enum):
    EXPLAIN_METHOD = "explain_method"
    EXPLAIN_TREND = "explain_trend"
    EXPLAIN_SEASONALITY = "explain_seasonality"
    EXPLAIN_CHANGEPOINTS = "explain_changepoints"
    EXPLAIN_INTERVALS = "explain_intervals"


class AtlasForecastRequest(ContractModel):
    action: AtlasForecastAction
    datetime_col: str = Field(min_length=1)
    numeric_col: str = Field(min_length=1)


class AtlasForecastResponse(ContractModel):
    action: AtlasForecastAction
    summary: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    evidence: list[AtlasEvidence]


# --- Phase 7C: ML Lab -----------------------------------------------------------


class MlSuggestionType(str, Enum):
    ENCODE = "encode"
    SCALE = "scale"
    DATETIME_EXPAND = "datetime_expand"
    INTERACTION = "interaction"


class MlFeatureSuggestion(ContractModel):
    kind: MlSuggestionType
    column: Optional[str] = None
    columns: Optional[list[str]] = None
    method: Optional[str] = None
    reason: str = Field(min_length=1)


class MlFeatureSuggestionsResponse(ContractModel):
    target_col: str
    suggestions: list[MlFeatureSuggestion]


class MlApplyFeatureRequest(ContractModel):
    suggestion: MlFeatureSuggestion


class MlApplyFeatureResponse(ContractModel):
    dataset: OverviewDataset
    description: str = Field(min_length=1)
    provenance: OverviewProvenance


class MlTaskType(str, Enum):
    CLASSIFICATION = "classification"
    REGRESSION = "regression"


class MlTaskDetectionResponse(ContractModel):
    target_col: str
    task_type: MlTaskType
    reason: str = Field(min_length=1)


class MlImbalanceInfo(ContractModel):
    target_col: str
    counts: dict[str, int]
    proportions_pct: dict[str, float]
    minority_pct: float
    is_imbalanced: bool
    explanation: str = Field(min_length=1)


class MlCvMetric(ContractModel):
    mean: float
    std: float


class MlCvResult(ContractModel):
    results: dict[str, dict[str, MlCvMetric]]
    n_splits: int = Field(ge=2)


class MlFeatureImportance(ContractModel):
    feature: str
    importance: float


class MlBaselineRequest(ContractModel):
    feature_cols: list[str] = Field(min_length=1)
    target_col: str = Field(min_length=1)
    task_type: Optional[MlTaskType] = None
    use_smote: bool = False


class MlBaselineResult(ContractModel):
    task_type: MlTaskType
    results: dict[str, dict[str, float]]
    confusion_matrix: Optional[list[list[int]]] = None
    confusion_labels: Optional[list[str]] = None
    feature_importances: list[MlFeatureImportance]
    n_train: int = Field(ge=0)
    n_test: int = Field(ge=0)
    smote_before_after: Optional[dict[str, Any]] = None
    cv: Optional[MlCvResult] = None
    cv_error: Optional[str] = None
    verdict: str = Field(min_length=1)
    leakage_note: str = Field(min_length=1)
    provenance: OverviewProvenance


class MlFeatureSelectionRequest(ContractModel):
    feature_cols: list[str] = Field(min_length=1)
    target_col: str = Field(min_length=1)
    task_type: Optional[MlTaskType] = None
    top_k: Optional[int] = Field(default=None, ge=1)


class MlFeatureRankingRow(ContractModel):
    feature: str
    mutual_info: float
    mutual_info_rank: float
    l1_coef_abs: float
    l1_rank: float
    rfe_selected: bool
    rfe_rank: float
    consensus_votes: int = Field(ge=0, le=3)
    consensus_rank: float


class MlFeatureSelectionResult(ContractModel):
    task_type: MlTaskType
    top_k: int = Field(ge=1)
    n_features: int = Field(ge=1)
    ranking: list[MlFeatureRankingRow]
    recommended_features: list[str]
    provenance: OverviewProvenance


class MlShapRequest(ContractModel):
    feature_cols: list[str] = Field(min_length=1)
    target_col: str = Field(min_length=1)
    task_type: Optional[MlTaskType] = None


class MlShapImportance(ContractModel):
    feature: str
    mean_abs_shap: float


class MlShapResult(ContractModel):
    task_type: MlTaskType
    model_explained: str = Field(min_length=1)
    global_importance: list[MlShapImportance]
    note: str = Field(min_length=1)
    provenance: OverviewProvenance


class AtlasMlAction(str, Enum):
    EXPLAIN_TASK_TYPE = "explain_task_type"
    COMPARE_MODELS = "compare_models"
    EXPLAIN_CROSS_VALIDATION = "explain_cross_validation"
    EXPLAIN_IMBALANCE = "explain_imbalance"
    EXPLAIN_FEATURE_IMPORTANCE = "explain_feature_importance"
    IDENTIFY_OVERFITTING = "identify_overfitting"


class AtlasMlRequest(ContractModel):
    action: AtlasMlAction
    feature_cols: list[str] = Field(min_length=1)
    target_col: str = Field(min_length=1)
    task_type: Optional[MlTaskType] = None


class AtlasMlResponse(ContractModel):
    action: AtlasMlAction
    summary: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    evidence: list[AtlasEvidence]


class AtlasLineageAction(str, Enum):
    EXPLAIN_PROVENANCE = "explain_provenance"
    EXPLAIN_STALENESS = "explain_staleness"
    EXPLAIN_LINEAGE = "explain_lineage"
    COMPARE_VERSIONS = "compare_versions"
    RECOMMEND_RERUNS = "recommend_reruns"
    EXPLAIN_EVIDENCE = "explain_evidence"


class AtlasLineageRequest(ContractModel):
    action: AtlasLineageAction
    compare_to_object_id: Optional[str] = None


class AtlasLineageResponse(ContractModel):
    action: AtlasLineageAction
    summary: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    evidence: list[AtlasEvidence]
    limitation: Optional[str] = None
