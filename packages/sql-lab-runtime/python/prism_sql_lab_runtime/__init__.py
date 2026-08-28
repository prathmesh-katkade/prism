"""Framework-free SQL Lab execution and safety semantics."""

from .external import (
    ExternalConnectorError,
    ExternalSource,
    execute_external_query,
    external_driver_error,
    external_plan,
    external_schema,
    load_external_sources,
    scrub_connector_error,
)
from .service import (
    SQL_LAB_SERVICE_VERSION,
    QueryClassification,
    classify_query,
    execute_local_query,
    execute_sqlite_query,
    schema_for_frame,
)

__all__ = [
    "ExternalConnectorError",
    "ExternalSource",
    "SQL_LAB_SERVICE_VERSION",
    "QueryClassification",
    "classify_query",
    "execute_local_query",
    "execute_sqlite_query",
    "execute_external_query",
    "external_driver_error",
    "external_plan",
    "external_schema",
    "load_external_sources",
    "schema_for_frame",
    "scrub_connector_error",
]
