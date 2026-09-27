"""Targeted human notes never become executed checks or invented messages."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from prism_api.atlas_interventions import DurableAtlasInterventionStore, valid_targets
from prism_api_contracts import (
    AtlasCouncilConclusion,
    AtlasInterventionWriteRequest,
    AtlasModelProviderName,
    AtlasPlanStep,
    AtlasRunResponse,
    AtlasSpecialistId,
    AtlasStepKind,
    AtlasStructuredPlan,
)


def _run() -> AtlasRunResponse:
    now = datetime.now(timezone.utc)
    return AtlasRunResponse(
        run_id="run-1",
        plan=AtlasStructuredPlan(
            plan_id="plan-1", objective="Check the evidence", dataset_id="dataset-1",
            provider=AtlasModelProviderName.DETERMINISTIC, created_at=now,
            steps=[AtlasPlanStep(
                step_id="profile", title="Profile", kind=AtlasStepKind.PROFILE_DATASET,
                specialist=AtlasSpecialistId.SCOUT, tool_name="overview.profile",
            )],
        ),
        council=[AtlasCouncilConclusion(
            specialist=AtlasSpecialistId.AUDITOR, conclusion="Descriptive only.",
            confidence="high", objections=["Causality is unresolved."],
        )],
    )


def test_intervention_is_append_only_and_targeted(tmp_path: Path) -> None:
    store = DurableAtlasInterventionStore(f"sqlite:///{tmp_path}/interventions.sqlite")
    run = _run()
    assert {"profile", "council:0", "objection:0:0"} <= valid_targets(run)
    with patch("prism_api.atlas_interventions.runs.get", return_value=run):
        first = store.record("run-1", AtlasInterventionWriteRequest(
            target_id="objection:0:0", text="Request assignment records."
        ))
        second = store.record("run-1", AtlasInterventionWriteRequest(
            target_id="profile", text="Check cohort exclusions."
        ))
        records = store.list_for_run("run-1")
        assert [item.intervention_id for item in records] == [first.intervention_id, second.intervention_id]
        assert all(item.author == "human" for item in records)
        assert records[0].target_id == "objection:0:0"
        with pytest.raises(HTTPException) as missing:
            store.record("run-1", AtlasInterventionWriteRequest(target_id="unknown", text="No target"))
        assert missing.value.status_code == 422
