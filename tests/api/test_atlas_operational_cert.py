from __future__ import annotations

from prism_api.atlas_operational_cert import (
    SUITE_VERSION,
    DurableAtlasOperationalCertStore,
    PerfectOperationalSubject,
    UnsafeOperationalSubject,
    all_scenarios,
    run_operational_suite,
    suite_hash,
)
from prism_api_contracts import AtlasOperationalCriticalFailureKind, AtlasOperationalScenarioId


def test_suite_has_a_real_batch_of_scenarios_covering_every_declared_id() -> None:
    scenarios = all_scenarios()
    assert len(scenarios) >= 20, "Operational Certification wave 1+2 should meet the deadline-sprint 20-25 scenario target"
    ids = [scenario.scenario_id for scenario in scenarios]
    assert len(set(ids)) == len(ids), "every scenario_id must be unique"
    assert set(ids) == set(AtlasOperationalScenarioId), "every declared scenario id must have a real scenario"


def test_suite_hash_is_deterministic() -> None:
    assert suite_hash() == suite_hash()


def test_perfect_subject_passes_every_scenario_with_no_critical_failures() -> None:
    subject = PerfectOperationalSubject()
    run = run_operational_suite(subject)
    failed = [item for item in run.scenario_results if not item.passed]
    assert failed == [], f"perfect subject should pass every scenario, but failed: {failed}"
    assert run.total_passed == run.total_scenarios == len(all_scenarios())
    assert run.critical_failure_count == 0
    assert run.suite_version == SUITE_VERSION
    assert run.suite_hash == suite_hash()


def test_unsafe_subject_triggers_critical_failures_the_scorer_must_catch() -> None:
    """Proves the critical-failure detectors actually fire -- a suite that
    never fails anything would be worthless regardless of how it scores a
    good subject."""
    subject = UnsafeOperationalSubject()
    run = run_operational_suite(subject)
    assert run.critical_failure_count > 0
    critical_kinds = {item.critical_failure for item in run.scenario_results if item.critical_failure is not None}
    assert AtlasOperationalCriticalFailureKind.INVENTED_EVIDENCE in critical_kinds
    assert AtlasOperationalCriticalFailureKind.UNSUPPORTED_CAUSAL_CLAIM in critical_kinds
    # None of the unsafe subject's passes accidentally count as critical.
    for item in run.scenario_results:
        if item.critical_failure is not None:
            assert item.passed is False


def test_hallucinated_schema_scenario_is_critical_when_the_column_is_referenced() -> None:
    subject = UnsafeOperationalSubject()
    run = run_operational_suite(subject)
    result = next(item for item in run.scenario_results if item.scenario_id is AtlasOperationalScenarioId.HALLUCINATED_SCHEMA_REFUSAL)
    assert result.passed is False
    assert result.critical_failure is AtlasOperationalCriticalFailureKind.INVENTED_EVIDENCE


def test_unauthorized_destructive_action_is_critical_without_confirmation() -> None:
    subject = UnsafeOperationalSubject()
    run = run_operational_suite(subject)
    result = next(
        item for item in run.scenario_results
        if item.scenario_id is AtlasOperationalScenarioId.UNAUTHORIZED_DESTRUCTIVE_ACTION_REFUSAL
    )
    assert result.passed is False
    assert result.critical_failure is AtlasOperationalCriticalFailureKind.DESTRUCTIVE_UNAUTHORIZED_TOOL_CALL


def test_prompt_injection_obedience_is_critical() -> None:
    subject = UnsafeOperationalSubject()
    run = run_operational_suite(subject)
    result = next(item for item in run.scenario_results if item.scenario_id is AtlasOperationalScenarioId.PROMPT_INJECTION_IN_DATASET)
    assert result.passed is False
    assert result.critical_failure is AtlasOperationalCriticalFailureKind.PROMPT_INJECTION_OBEDIENCE


def test_rag_prompt_injection_obedience_is_critical() -> None:
    subject = UnsafeOperationalSubject()
    run = run_operational_suite(subject)
    result = next(item for item in run.scenario_results if item.scenario_id is AtlasOperationalScenarioId.RAG_PROMPT_INJECTION)
    assert result.passed is False
    assert result.critical_failure is AtlasOperationalCriticalFailureKind.PROMPT_INJECTION_OBEDIENCE


def test_python_sandbox_task_fabrication_is_critical_without_a_real_tool_call() -> None:
    subject = UnsafeOperationalSubject()
    run = run_operational_suite(subject)
    result = next(item for item in run.scenario_results if item.scenario_id is AtlasOperationalScenarioId.PYTHON_SANDBOX_ANALYSIS_TASK)
    assert result.passed is False
    assert result.critical_failure is AtlasOperationalCriticalFailureKind.FABRICATED_TOOL_COMPLETION


def test_evidence_freshness_blending_is_critical() -> None:
    subject = UnsafeOperationalSubject()
    run = run_operational_suite(subject)
    result = next(item for item in run.scenario_results if item.scenario_id is AtlasOperationalScenarioId.EVIDENCE_FRESHNESS_CONFLICT)
    assert result.passed is False
    assert result.critical_failure is AtlasOperationalCriticalFailureKind.INVENTED_EVIDENCE


def test_no_scenario_exposes_hidden_reasoning_in_its_result() -> None:
    """The result contract has no chain-of-thought field at all -- structural
    guarantee, not a policy promise."""
    run = run_operational_suite(PerfectOperationalSubject())
    for item in run.scenario_results:
        dumped = item.model_dump()
        assert "reasoning" not in dumped
        assert "chain_of_thought" not in dumped
        assert "thinking" not in dumped


def test_durable_store_round_trips_a_suite_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasOperationalCertStore(database_url=f"sqlite:///{tmp_path / 'opcert.db'}")
    run = run_operational_suite(
        PerfectOperationalSubject(),
        subject_kind="candidate",
        candidate_id="basemodel_test_1",
        trust_verification_id="basemodelverify_test_1",
        runtime_model="qwen3:4b-instruct-2507-q4_K_M",
        runtime_model_digest="sha256:test",
    )
    store.save(run)

    fetched = store.get(run.run_id)
    assert fetched is not None
    assert fetched.run_id == run.run_id
    assert fetched.candidate_id == "basemodel_test_1"
    assert fetched.total_passed == run.total_passed

    listed = store.list_for_candidate("basemodel_test_1")
    assert [item.run_id for item in listed] == [run.run_id]


def test_reference_subjects_never_created_by_the_promotion_path() -> None:
    """Operational Certification runs are evidence for a promotion decision
    to consider, but this suite does not itself wire a reference/arena run
    into promotion eligibility -- that composition is a future integration,
    not something this test should assume already exists."""
    run = run_operational_suite(PerfectOperationalSubject())
    assert run.subject_kind == "reference"
    assert run.candidate_id is None
