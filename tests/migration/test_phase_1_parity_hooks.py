from prism_api.migration import PHASE_1_MIGRATIONS
from prism_api_contracts import ReleaseChannel


def test_phase_5_promotes_ai_analyst_after_its_own_parity_evidence() -> None:
    """Only the approved AI Analyst workflow is enabled by this Phase 5 slice."""
    assert {state.workflow for state in PHASE_1_MIGRATIONS} == {"overview", "sql-lab", "ai-analyst"}
    channels = {state.workflow: state.channel for state in PHASE_1_MIGRATIONS}
    assert channels["overview"] is ReleaseChannel.ENABLED
    assert channels["sql-lab"] is ReleaseChannel.ENABLED
    assert channels["ai-analyst"] is ReleaseChannel.ENABLED
    assert all(state.parity_required for state in PHASE_1_MIGRATIONS)
