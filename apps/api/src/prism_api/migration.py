from __future__ import annotations

from prism_api_contracts import MigrationState, ReleaseChannel

PHASE_1_MIGRATIONS: tuple[MigrationState, ...] = (
    MigrationState(
        workflow="overview",
        channel=ReleaseChannel.ENABLED,
        legacy_reference="app.py:Overview (parity reference)",
    ),
    MigrationState(
        workflow="sql-lab",
        channel=ReleaseChannel.ENABLED,
        legacy_reference="modules/sql_lab.py",
    ),
    MigrationState(
        workflow="ai-analyst",
        channel=ReleaseChannel.ENABLED,
        legacy_reference="modules/ai_analyst.py",
    ),
)
