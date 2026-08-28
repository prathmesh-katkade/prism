"""Framework-free analytical primitives shared by legacy Overview and the PRISM API."""

from .service import (
    ANALYTICS_SERVICE_VERSION,
    HEALTH_COMPONENT_WEIGHTS,
    build_overview,
    detect_column_types,
    detect_outliers_iqr,
    detect_pii_present,
    get_data_quality_report,
    get_health_breakdown,
    get_health_score,
    profile_all_columns,
    profile_column,
)

__all__ = [
    "ANALYTICS_SERVICE_VERSION",
    "HEALTH_COMPONENT_WEIGHTS",
    "build_overview",
    "detect_column_types",
    "detect_outliers_iqr",
    "detect_pii_present",
    "get_data_quality_report",
    "get_health_breakdown",
    "get_health_score",
    "profile_all_columns",
    "profile_column",
]
