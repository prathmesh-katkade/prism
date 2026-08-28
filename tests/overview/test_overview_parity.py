from __future__ import annotations

import pandas as pd
from prism_overview_analytics import (
    build_overview,
    detect_column_types,
    get_data_quality_report,
    get_health_breakdown,
    profile_all_columns,
)

from modules import data_engine, pii_detector, profiling


def representative_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": [1, 2, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            "revenue": [10.0, 12.0, 12.0, None, 15.0, 16.0, 17.0, 18.0, 20.0, 21.0, 22.0, 500.0],
            "segment": ["North", "South", "South", "South", "North", "North", "West", "West", "West", "East", "East", "East"],
            "email": ["a@example.com", "b@example.com", "b@example.com", "d@example.com", "e@example.com", "f@example.com", "g@example.com", "h@example.com", "i@example.com", "j@example.com", "k@example.com", "l@example.com"],
            "empty": [None] * 12,
            "event_date": ["2026-01-01", "2026-01-02", "2026-01-02", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-10", "2026-01-11", "2026-01-12"],
        }
    )


def test_new_analytical_service_matches_legacy_quality_and_health() -> None:
    frame = representative_frame()
    legacy_types = data_engine.detect_column_types(frame)
    legacy_quality = data_engine.get_data_quality_report(frame, legacy_types)
    pii_findings = pii_detector.scan_dataframe(frame, legacy_types)

    assert detect_column_types(frame) == legacy_types
    assert get_data_quality_report(frame, legacy_types) == legacy_quality
    assert get_health_breakdown(legacy_quality, legacy_types, pii_detector.has_findings(pii_findings)) == data_engine.get_health_breakdown(legacy_quality, legacy_types, pii_findings)
    assert profile_all_columns(frame, legacy_types, legacy_quality) == profiling.profile_all_columns(frame, legacy_types, legacy_quality)


def test_overview_payload_does_not_expose_raw_dataset_rows() -> None:
    payload = build_overview(representative_frame(), pii_detected=True)

    assert {"quality", "health", "columns", "correlations", "suggestions"} == set(payload)
    assert "rows" not in payload
    assert payload["quality"]["duplicate_rows"] == 1
    assert payload["health"]["total"] <= 93  # PII is a visible validity deduction.


def test_empty_and_low_signal_frames_preserve_legacy_failure_free_behavior() -> None:
    frame = pd.DataFrame({"empty": [None, None], "only_text": ["one", "two"]})
    types = detect_column_types(frame)

    assert types == data_engine.detect_column_types(frame)
    assert build_overview(frame)["correlations"] == []
