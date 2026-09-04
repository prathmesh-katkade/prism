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
    """Diagnostic state for an optional provider or required persistence boundary.

    AI configuration remains non-blocking. Durable analytical history is reported
    separately because a production history-enabled deployment must not silently
    accept work when its evidence store is unavailable.
    """

    name: str = Field(min_length=1)
    status: Literal["configured", "not_configured", "ready", "unavailable"]
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


# --- Phase 10: Atlas Local Intelligence Foundry ------------------------------


class AtlasModelProviderName(str, Enum):
    DETERMINISTIC = "deterministic"
    OLLAMA = "ollama"


class AtlasProviderCapability(str, Enum):
    STRUCTURED_PLANNING = "structured_planning"
    LOCAL_INFERENCE = "local_inference"
    STREAMING = "streaming"


class AtlasModelProviderCapabilities(ContractModel):
    provider: AtlasModelProviderName
    available: bool
    capabilities: list[AtlasProviderCapability] = Field(default_factory=list)
    raw_data_policy: Literal["never", "explicitly_authorized"] = "never"
    detail: str = Field(min_length=1)


class AtlasPlanState(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AtlasStepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class AtlasStepKind(str, Enum):
    PROFILE_DATASET = "profile_dataset"
    DATA_QUALITY = "data_quality"
    SQL_QUESTION = "sql_question"
    METHODOLOGY_REVIEW = "methodology_review"
    STATISTICAL_ANALYSIS = "statistical_analysis"
    FORECAST = "forecast"
    MACHINE_LEARNING = "machine_learning"
    VISUALIZATION = "visualization"
    EXPLAIN_HISTORY = "explain_history"
    PYTHON_ANALYSIS = "python_analysis"
    RESEARCH = "research"
    AUDIT_EVIDENCE = "audit_evidence"


class AtlasSpecialistId(str, Enum):
    ATLAS = "atlas"
    SCOUT = "scout"
    CURATOR = "curator"
    QUERY = "query"
    STAT = "stat"
    FORGE = "forge"
    ORACLE = "oracle"
    LENS = "lens"
    RESEARCHER = "researcher"
    LIBRARIAN = "librarian"
    AUDITOR = "auditor"


class AtlasSpecialistIdentity(ContractModel):
    specialist: AtlasSpecialistId
    display_name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=240)
    visible: bool = True
    speaks_to_user: bool = False


class AtlasEvidenceReference(ContractModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    kind: Literal["dataset_revision", "overview_profile", "analytical_object", "tool_output", "web_research", "memory", "project_knowledge"]
    summary: str = Field(min_length=1, max_length=1_000)
    dataset_id: Optional[str] = None
    dataset_revision: Optional[int] = Field(default=None, ge=0)
    source_fingerprint: Optional[str] = Field(default=None, min_length=16)


class AtlasPlanStep(ContractModel):
    step_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    kind: AtlasStepKind
    specialist: AtlasSpecialistId
    tool_name: str = Field(min_length=1, max_length=120)
    rationale: str = Field(default="", max_length=1_000)
    dependencies: list[str] = Field(default_factory=list, max_length=20)
    tool_args: dict[str, object] = Field(default_factory=dict)
    expected_evidence: list[str] = Field(default_factory=list, max_length=20)
    state: AtlasStepState = AtlasStepState.PENDING
    max_attempts: int = Field(default=3, ge=1, le=3)
    attempts: int = Field(default=0, ge=0, le=3)
    requires_approval: bool = False
    evidence: list[AtlasEvidenceReference] = Field(default_factory=list)
    error: Optional[str] = None


class AtlasStructuredPlan(ContractModel):
    plan_id: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=2_000)
    dataset_id: str = Field(min_length=1)
    state: AtlasPlanState = AtlasPlanState.DRAFT
    provider: AtlasModelProviderName
    steps: list[AtlasPlanStep] = Field(min_length=1, max_length=20)
    created_at: datetime


class AtlasCouncilConclusion(ContractModel):
    specialist: AtlasSpecialistId
    conclusion: str = Field(min_length=1, max_length=2_000)
    confidence: Literal["low", "medium", "high"]
    objections: list[str] = Field(default_factory=list)
    evidence: list[AtlasEvidenceReference] = Field(default_factory=list)


class AtlasRunEventType(str, Enum):
    RUN_CREATED = "run_created"
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    COUNCIL_CONCLUSION = "council_conclusion"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


class AtlasRunEvent(ContractModel):
    event_id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    sequence: int = Field(ge=1)
    type: AtlasRunEventType
    occurred_at: datetime
    specialist: Optional[AtlasSpecialistId] = None
    step_id: Optional[str] = None
    payload: dict[str, object] = Field(default_factory=dict)


class AtlasRunRequest(ContractModel):
    dataset_id: str = Field(min_length=1)
    objective: str = Field(min_length=3, max_length=2_000)
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=120)


class AtlasRunResponse(ContractModel):
    run_id: str = Field(min_length=1, max_length=120)
    plan: AtlasStructuredPlan
    answer: Optional[str] = None
    uncertainty: Optional[str] = None
    evidence: list[AtlasEvidenceReference] = Field(default_factory=list)
    council: list[AtlasCouncilConclusion] = Field(default_factory=list)
    events: list[AtlasRunEvent] = Field(default_factory=list)
    cancellation_requested: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AtlasMemoryScope(str, Enum):
    SESSION = "session"
    PROJECT = "project"
    WORKSPACE = "workspace"
    GLOBAL = "global"


class AtlasMemoryClass(str, Enum):
    DATA_EVIDENCE = "data_evidence"
    PROJECT_KNOWLEDGE = "project_knowledge"
    USER_MEMORY = "user_memory"
    MODEL_KNOWLEDGE = "model_knowledge"
    WEB_RESEARCH = "web_research"


class AtlasMemoryRecord(ContractModel):
    memory_id: str = Field(min_length=1)
    scope: AtlasMemoryScope
    knowledge_class: AtlasMemoryClass
    content: str = Field(min_length=1, max_length=8_000)
    source: str = Field(min_length=1, max_length=500)
    confidence: Literal["low", "medium", "high"]
    timestamp: datetime
    source_ref: Optional[str] = None
    workspace_id: Optional[str] = None
    sensitivity: Literal["public", "internal", "private", "restricted"] = "internal"
    user_editable: bool = True
    deletable: bool = True
    provenance: list[AtlasEvidenceReference] = Field(default_factory=list)
    reinforcement: int = Field(default=0, ge=0)
    last_used: Optional[datetime] = None
    contradictions: list[str] = Field(default_factory=list)
    superseded_by: Optional[str] = None
    project_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class AtlasMemoryWriteRequest(ContractModel):
    scope: AtlasMemoryScope
    knowledge_class: AtlasMemoryClass
    content: str = Field(min_length=1, max_length=8_000)
    source: str = Field(min_length=1, max_length=500)
    source_ref: Optional[str] = Field(default=None, max_length=2_000)
    confidence: Literal["low", "medium", "high"] = "medium"
    project_id: Optional[str] = Field(default=None, max_length=200)
    workspace_id: Optional[str] = Field(default=None, max_length=200)
    sensitivity: Literal["public", "internal", "private", "restricted"] = "internal"
    user_editable: bool = True
    provenance: list[AtlasEvidenceReference] = Field(default_factory=list)


class AtlasMemoryQuery(ContractModel):
    scope: Optional[AtlasMemoryScope] = None
    knowledge_class: Optional[AtlasMemoryClass] = None
    project_id: Optional[str] = None
    workspace_id: Optional[str] = None
    min_confidence: Optional[Literal["low", "medium", "high"]] = None
    updated_after: Optional[datetime] = None
    limit: int = Field(default=25, ge=1, le=100)


class AtlasKnowledgeSourceRequest(ContractModel):
    project_id: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(min_length=1, max_length=2_000)
    content: str = Field(min_length=1, max_length=200_000)
    content_version: str = Field(min_length=1, max_length=200)
    kind: Literal["markdown", "text", "python", "sql", "notebook_metadata", "documentation"]


class AtlasKnowledgeChunk(ContractModel):
    chunk_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    content_version: str = Field(min_length=1)
    location: str = Field(min_length=1)
    content: str = Field(min_length=1)
    injection_detected: bool = False
    score: float = 0


class AtlasKnowledgeSearchRequest(ContractModel):
    project_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=8, ge=1, le=25)


class AtlasResearchRequest(ContractModel):
    query: str = Field(min_length=1, max_length=2_000)
    url: Optional[str] = Field(default=None, max_length=2_000)
    project_id: Optional[str] = Field(default=None, max_length=200)
    offline: bool = False


class AtlasResearchResult(ContractModel):
    research_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    status: Literal["completed", "blocked", "offline", "failed"]
    source_url: Optional[str] = None
    title: Optional[str] = None
    retrieved_at: datetime
    content_hash: Optional[str] = None
    excerpt: Optional[str] = None
    citations: list[AtlasEvidenceReference] = Field(default_factory=list)
    injection_detected: bool = False
    detail: str = Field(min_length=1, max_length=2_000)


class CortexNodeKind(str, Enum):
    RUN = "run"
    PLAN_STEP = "plan_step"
    SPECIALIST = "specialist"
    EVIDENCE = "evidence"
    DATASET = "dataset"
    ANALYTICAL_OBJECT = "analytical_object"
    TOOL = "tool"
    ARTIFACT = "artifact"


class CortexNode(ContractModel):
    node_id: str = Field(min_length=1)
    kind: CortexNodeKind
    label: str = Field(min_length=1, max_length=240)
    state: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1)


class CortexEdge(ContractModel):
    edge_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    relation: Literal["contains", "executed_by", "produced", "supports", "uses", "generated_by"]


class CortexGraphState(ContractModel):
    run_id: str = Field(min_length=1)
    nodes: list[CortexNode] = Field(default_factory=list)
    edges: list[CortexEdge] = Field(default_factory=list)
    generated_at: datetime


class AtlasSandboxErrorKind(str, Enum):
    POLICY = "policy"
    PATH = "path"
    NETWORK = "network"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RESOURCE_LIMIT = "resource_limit"
    EXECUTION = "execution"


class AtlasSandboxArtifact(ContractModel):
    artifact_id: str = Field(min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=120)
    byte_count: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)


class AtlasSandboxExecutionRequest(ContractModel):
    code: str = Field(min_length=1, max_length=24_000)
    timeout_ms: int = Field(default=15_000, ge=100, le=60_000)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)


class AtlasSandboxExecutionResult(ContractModel):
    execution_id: str = Field(min_length=1, max_length=160)
    state: Literal["completed", "failed", "cancelled", "timed_out"]
    stdout: str = Field(default="", max_length=32_000)
    stderr: str = Field(default="", max_length=32_000)
    artifacts: list[AtlasSandboxArtifact] = Field(default_factory=list)
    error_kind: Optional[AtlasSandboxErrorKind] = None
    error: Optional[str] = Field(default=None, max_length=2_000)
    duration_ms: int = Field(ge=0)
    limits_enforced: list[str] = Field(default_factory=list)


class AtlasSandboxWorkerHealth(ContractModel):
    state: Literal["ready", "degraded"]
    execution_mode: Literal["native_worker", "container_worker"]
    network_policy: Literal["deny_by_default"]
    process_tree_termination: bool
    cpu_quota_enforced: bool
    memory_quota_enforced: bool
    container_available: bool
    detail: str = Field(min_length=1, max_length=2_000)


class AtlasModelTrust(ContractModel):
    source_verified: bool = False
    license_verified: bool = False
    manifest_verified: bool = False
    checksum_verified: bool = False
    compatibility_verified: bool = False
    atlasbench_verified: bool = False


class AtlasBenchmarkVerdict(str, Enum):
    PENDING = "pending"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class AtlasBenchmarkResult(ContractModel):
    suite_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    critical_regressions: int = Field(ge=0)
    verdict: AtlasBenchmarkVerdict
    evaluated_at: datetime


class AtlasResourcePriority(int, Enum):
    USER_INTERACTION = 0
    ATLAS_INFERENCE = 1
    ACTIVE_ANALYSIS = 2
    SPECIALIST_INFERENCE = 3
    INDEXING = 4
    FOUNDRY_TRAINING = 5
    MAINTENANCE = 6


class AtlasResourceWorkload(ContractModel):
    workload_id: str = Field(min_length=1)
    priority: AtlasResourcePriority
    cancellable: bool = True
    description: str = Field(min_length=1, max_length=500)
    requires_gpu: bool = False
    cpu_slots: int = Field(default=1, ge=1, le=64)
    memory_mb: int = Field(default=256, ge=64, le=262_144)


class AtlasResourceLeaseRequest(ContractModel):
    workload: AtlasResourceWorkload
    allow_preemption: bool = True


class AtlasResourceLease(ContractModel):
    lease_id: str = Field(min_length=1)
    workload: AtlasResourceWorkload
    state: Literal["active", "queued", "preempted", "released", "cancelled"]
    granted_at: Optional[datetime] = None
    reason: str = Field(min_length=1, max_length=1_000)


class AtlasResourceSnapshot(ContractModel):
    cpu_count: int = Field(ge=1)
    memory_total_mb: Optional[int] = Field(default=None, ge=0)
    memory_available_mb: Optional[int] = Field(default=None, ge=0)
    storage_free_mb: Optional[int] = Field(default=None, ge=0)
    gpu_available: bool = False
    gpu_name: Optional[str] = None
    vram_total_mb: Optional[int] = Field(default=None, ge=0)
    gpu_telemetry_detail: str = Field(min_length=1, max_length=1_000)
    active_leases: list[AtlasResourceLease] = Field(default_factory=list)
