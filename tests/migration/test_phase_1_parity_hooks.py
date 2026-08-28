from prism_api.migration import PHASE_1_MIGRATIONS
from prism_api_contracts import ReleaseChannel


def test_phase_6_promotes_clean_and_visualize_after_their_own_parity_evidence() -> None:
    """Only the approved workflows are enabled: Phase 5's AI Analyst plus Phase 6's Clean/Visualize."""
    assert {state.workflow for state in PHASE_1_MIGRATIONS} == {"overview", "sql-lab", "ai-analyst", "clean", "visualize"}
    channels = {state.workflow: state.channel for state in PHASE_1_MIGRATIONS}
    assert channels["overview"] is ReleaseChannel.ENABLED
    assert channels["sql-lab"] is ReleaseChannel.ENABLED
    assert channels["ai-analyst"] is ReleaseChannel.ENABLED
    assert channels["clean"] is ReleaseChannel.ENABLED
    assert channels["visualize"] is ReleaseChannel.ENABLED
    assert all(state.parity_required for state in PHASE_1_MIGRATIONS)
