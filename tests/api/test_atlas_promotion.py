from __future__ import annotations

from prism_api.atlas_adapter_foundation import (
    report_adapter_capability,
    report_all_adapter_capabilities,
)
from prism_api.atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash
from prism_api.atlas_bench_runner import (
    FirstChoiceSubject,
    PerfectReferenceSubject,
    WorstReferenceSubject,
    run_suite,
)
from prism_api.atlas_promotion import (
    CRITICAL_CATEGORIES,
    DurableAtlasPromotionStore,
    decide_promotion,
    shadow_compare,
)
from prism_api_contracts import AtlasAdapterId, AtlasPromotionDecision, AtlasPromotionVerdict


def _runs():  # type: ignore[no-untyped-def]
    tasks = all_tasks()
    production_run, _ = run_suite(WorstReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    return tasks, production_run


def test_a_strictly_better_candidate_with_no_critical_regression_is_promote_eligible() -> None:
    tasks, production_run = _runs()
    candidate_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="candidate"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is AtlasPromotionVerdict.PROMOTE_ELIGIBLE
    assert decision.critical_regressions == []
    assert decision.overall_candidate_pass_rate > decision.overall_production_pass_rate


def test_identical_performance_is_hold() -> None:
    tasks = all_tasks()
    production_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    candidate_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="candidate"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is AtlasPromotionVerdict.HOLD


def test_a_worse_candidate_that_regresses_a_critical_category_is_rejected_even_with_overall_improvement_impossible() -> None:
    tasks = all_tasks()
    production_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    candidate_run, _ = run_suite(WorstReferenceSubject(tasks, subject_id="candidate"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is AtlasPromotionVerdict.REJECT
    assert decision.critical_regressions
    assert all(item.category in CRITICAL_CATEGORIES for item in decision.critical_regressions)


def test_critical_regression_blocks_promotion_even_if_aggregate_score_would_otherwise_pass() -> None:
    # A candidate that aces every non-critical category but regresses even one
    # critical category must still be rejected -- "cannot win on aggregate
    # score while catastrophically regressing a critical category."
    tasks = all_tasks()
    production_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())

    class _MostlyPerfectButFailsOneCritical:
        subject_id = "candidate"

        def __init__(self, tasks):  # type: ignore[no-untyped-def]
            self._correct = {task.task_id: task.correct_choice for task in tasks}

        def answer(self, prompt, choices):  # type: ignore[no-untyped-def]
            for task in tasks:
                if task.prompt == prompt:
                    if task.task_id == "sql_001":  # SQL is a critical category
                        return next(i for i in range(len(choices)) if i != task.correct_choice)
                    return task.correct_choice
            return 0

    candidate_run, _ = run_suite(_MostlyPerfectButFailsOneCritical(tasks), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is AtlasPromotionVerdict.REJECT
    assert decision.overall_candidate_pass_rate < 1.0  # sanity: it really did miss one


def test_shadow_compare_runs_both_subjects_and_returns_a_decision() -> None:
    tasks = all_tasks()
    production_run, candidate_run, decision = shadow_compare(
        WorstReferenceSubject(tasks, subject_id="prod"),
        PerfectReferenceSubject(tasks, subject_id="candidate"),
        tasks,
        corpus_version=CORPUS_VERSION,
        corpus_hash_value=corpus_hash(),
    )
    assert production_run.subject_id == "prod"
    assert candidate_run.subject_id == "candidate"
    assert decision.verdict is AtlasPromotionVerdict.PROMOTE_ELIGIBLE


def test_promotion_store_refuses_to_promote_a_non_eligible_decision(tmp_path) -> None:  # type: ignore[no-untyped-def]
    tasks = all_tasks()
    production_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    candidate_run, _ = run_suite(FirstChoiceSubject(subject_id="candidate"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is not AtlasPromotionVerdict.PROMOTE_ELIGIBLE

    store = DurableAtlasPromotionStore(f"sqlite:///{(tmp_path / 'promotion.sqlite').as_posix()}")
    try:
        store.promote(decision, reason="should not be allowed")
    except ValueError as error:
        assert "not promote_eligible" in str(error)
    else:
        raise AssertionError("promoting a non-eligible decision should have raised")
    assert store.current_production() is None


def test_promotion_is_atomic_auditable_and_never_overwrites_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    tasks, production_run = _runs()
    store = DurableAtlasPromotionStore(f"sqlite:///{(tmp_path / 'promotion.sqlite').as_posix()}")

    candidate_a_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="candidate_a"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision_a = decide_promotion("candidate_a", production_run, candidate_a_run)
    pointer_a = store.promote(decision_a, reason="first promotion")
    assert pointer_a.candidate_id == "candidate_a"
    assert pointer_a.previous_candidate_id is None

    candidate_b_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="candidate_b"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision_b = decide_promotion("candidate_b", candidate_a_run, candidate_b_run)
    # candidate_b ties candidate_a (both perfect) -> HOLD, not eligible; use a
    # synthetic eligible decision to exercise a second real promotion instead.
    import datetime as _dt

    from prism_api_contracts import AtlasPromotionDecision

    forced_eligible = AtlasPromotionDecision(
        decision_id=decision_b.decision_id,
        candidate_id="candidate_b",
        production_run_id=decision_b.production_run_id,
        candidate_run_id=decision_b.candidate_run_id,
        verdict=AtlasPromotionVerdict.PROMOTE_ELIGIBLE,
        overall_production_pass_rate=decision_b.overall_production_pass_rate,
        overall_candidate_pass_rate=decision_b.overall_candidate_pass_rate,
        critical_regressions=[],
        decided_at=_dt.datetime.now(_dt.timezone.utc),
    )
    pointer_b = store.promote(forced_eligible, reason="second promotion")
    assert pointer_b.candidate_id == "candidate_b"
    assert pointer_b.previous_candidate_id == "candidate_a"

    history = store.history()
    assert [item.candidate_id for item in history] == ["candidate_b", "candidate_a"]
    assert store.current_production().candidate_id == "candidate_b"  # type: ignore[union-attr]

    rolled_back = store.rollback(reason="candidate_b regressed in production")
    assert rolled_back.candidate_id == "candidate_a"
    assert rolled_back.is_rollback is True
    assert store.current_production().candidate_id == "candidate_a"  # type: ignore[union-attr]
    # Rollback is a new event, not a deletion: all three events remain.
    assert len(store.history()) == 3


def test_rollback_without_prior_production_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasPromotionStore(f"sqlite:///{(tmp_path / 'promotion.sqlite').as_posix()}")
    try:
        store.rollback(reason="nothing to roll back to")
    except ValueError as error:
        assert "No prior production candidate" in str(error)
    else:
        raise AssertionError("rollback with no history should have raised")


def test_promotion_ordering_survives_equal_promoted_at_timestamps(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A configured MySQL DATETIME can give two promotions within the same
    second an identical promoted_at; current_production()/history() must
    still resolve to genuine insertion order via the sequence tiebreaker,
    not an arbitrary DB-dependent order among tied rows."""
    import os
    import uuid
    from datetime import datetime as _datetime
    from datetime import timezone as _timezone
    from unittest.mock import patch

    # Real MySQL is what genuinely exercises the tie: it clusters rows by
    # primary key (a random UUID here), not insertion order, so tied
    # promoted_at values return in an order uncorrelated with which
    # promotion actually happened second -- unlike SQLite, whose tie order
    # happens to coincide with insertion order and would pass even with the
    # old (buggy) promoted_at-only ordering. CI's phase-4-live-e2e job runs
    # this file with PRISM_ANALYTICAL_HISTORY_DATABASE_URL set to a real
    # MySQL service container for exactly this reason.
    #
    # Real MySQL also has no tmp_path-style per-test isolation -- this test's
    # rows land in the same shared table every other test in this file using
    # the same fallback writes to -- so candidate ids are made unique per run
    # and `history()` is read only for its first two (most recent) entries,
    # never asserted as the database's entire content.
    run_id = uuid.uuid4().hex[:8]
    candidate_a, candidate_b = f"candidate_a_{run_id}", f"candidate_b_{run_id}"
    configured = os.environ.get("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", "")
    database_url = configured if configured.startswith("mysql") else f"sqlite:///{(tmp_path / 'tied-promotions.sqlite').as_posix()}"
    store = DurableAtlasPromotionStore(database_url)
    tied_instant = _datetime.now(_timezone.utc).replace(microsecond=0)
    # bootstrap() is idempotent by design -- it no-ops once any production
    # candidate exists, which on shared MySQL a prior test in this file may
    # already have established -- so the anchor event is appended directly
    # through the same low-level path promote()/rollback() use, with the
    # tied instant passed explicitly rather than via the datetime.now() mock
    # below (which only the still-public promote() call needs).
    store._append_with_retry(  # noqa: SLF001
        candidate_id=candidate_a, previous_candidate_id=None, decision_id=None,
        is_rollback=False, reason="bootstrap", now=tied_instant,
    )
    with patch("prism_api.atlas_promotion.datetime") as clock:
        clock.now.return_value = tied_instant

        forced = AtlasPromotionDecision(
            decision_id=f"decision_{run_id}",
            candidate_id=candidate_b,
            production_run_id="prod",
            candidate_run_id="cand",
            verdict=AtlasPromotionVerdict.PROMOTE_ELIGIBLE,
            overall_production_pass_rate=0.5,
            overall_candidate_pass_rate=0.9,
            critical_regressions=[],
            decided_at=tied_instant,
        )
        promoted = store.promote(forced, reason="tied-clock promotion")
        assert promoted.candidate_id == candidate_b

    # Both events share the same (mocked) promoted_at, so only the sequence
    # tiebreaker can correctly say candidate_b is current, not candidate_a.
    assert store.current_production().candidate_id == candidate_b  # type: ignore[union-attr]
    assert [item.candidate_id for item in store.history(limit=2)] == [candidate_b, candidate_a]

    rolled_back = store.rollback(reason="tied-clock rollback")
    assert rolled_back.candidate_id == candidate_a
    assert store.current_production().candidate_id == candidate_a  # type: ignore[union-attr]


def test_concurrent_promotion_events_never_share_a_sequence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Two overlapping appends (e.g. a promote racing a rollback) must not
    both allocate the same sequence -- with_for_update() alone is a no-op on
    SQLite, so the UNIQUE index on sequence is the real guarantee; the loser
    raises IntegrityError and _append_with_retry() re-reads and retries."""
    import os
    import threading
    import uuid
    from datetime import datetime, timezone

    # Real MySQL has no tmp_path-style per-test isolation -- every test using
    # the `configured` fallback appends to the same shared table across the
    # whole file, so this test's own rows must be identified by their own
    # unique candidate ids rather than by an exact total row count.
    run_id = uuid.uuid4().hex[:8]
    root_candidate = f"candidate_root_{run_id}"
    concurrent_candidates = [f"candidate_{i}_{run_id}" for i in range(4)]

    configured = os.environ.get("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", "")
    database_url = configured if configured.startswith("mysql") else f"sqlite:///{(tmp_path / 'concurrent-promotions.sqlite').as_posix()}"
    store = DurableAtlasPromotionStore(database_url)
    # bootstrap() is idempotent by design -- it no-ops once any production
    # candidate exists, which on shared MySQL a prior test in this file may
    # already have established. Append the root event directly through the
    # same low-level path the concurrent appends below use, so it always
    # actually lands as its own row regardless of what ran before it.
    store._append_with_retry(  # noqa: SLF001
        candidate_id=root_candidate, previous_candidate_id=None, decision_id=None,
        is_rollback=False, reason="bootstrap", now=datetime.now(timezone.utc),
    )

    errors: list[BaseException] = []

    def append(candidate_id: str) -> None:
        try:
            store._append_with_retry(  # noqa: SLF001 -- exercising the lock/retry path directly
                candidate_id=candidate_id,
                previous_candidate_id=root_candidate,
                decision_id=None,
                is_rollback=False,
                reason=f"concurrent append {candidate_id}",
                now=datetime.now(timezone.utc),
            )
        except BaseException as exc:  # noqa: BLE001 -- surfaced via `errors` for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=append, args=(candidate_id,)) for candidate_id in concurrent_candidates]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"append raised under concurrency: {errors}"
    this_run = {root_candidate, *concurrent_candidates}
    sequences = [item.candidate_id for item in store.history(limit=200) if item.candidate_id in this_run]
    assert len(sequences) == 5  # bootstrap + 4 concurrent appends
    assert len(set(sequences)) == 5, f"no candidate should be lost or duplicated: {sequences}"


def test_promotion_store_migrates_a_pre_sequence_database_in_original_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A database written before the sequence tiebreaker existed must not
    break on open, and its existing history must keep its real order."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, create_engine, insert

    database_url = f"sqlite:///{(tmp_path / 'legacy-promotions.sqlite').as_posix()}"
    legacy_metadata = MetaData()
    legacy_events = Table(
        "prism_atlas_production_pointer_events",
        legacy_metadata,
        Column("event_id", String(120), primary_key=True),
        Column("candidate_id", String(120), nullable=False),
        Column("previous_candidate_id", String(120), nullable=True),
        Column("decision_id", String(120), nullable=True),
        Column("is_rollback", Boolean, nullable=False),
        Column("reason", String(1_000), nullable=False),
        Column("promoted_at", DateTime(timezone=True), nullable=False),
    )
    engine = create_engine(database_url, future=True)
    legacy_metadata.create_all(engine)
    # Safely in the past relative to the real wall clock, so the fresh
    # promotion below (using real datetime.now()) is unambiguously later
    # regardless of how many milliseconds this test takes to run -- this
    # test is about surviving migration, not about a timestamp tie.
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    with engine.begin() as connection:
        for offset, (candidate, previous) in enumerate([("legacy_a", None), ("legacy_b", "legacy_a")]):
            connection.execute(
                insert(legacy_events).values(
                    event_id=f"promo_{uuid.uuid4().hex}",
                    candidate_id=candidate,
                    previous_candidate_id=previous,
                    decision_id=None,
                    is_rollback=False,
                    reason="pre-migration history",
                    promoted_at=base + timedelta(seconds=offset),
                )
            )
    engine.dispose()

    # Opening the store against the legacy schema must migrate in place
    # (ADD COLUMN + backfill), not raise, and must preserve real order.
    store = DurableAtlasPromotionStore(database_url)
    assert [item.candidate_id for item in store.history()] == ["legacy_b", "legacy_a"]
    assert store.current_production().candidate_id == "legacy_b"  # type: ignore[union-attr]

    # New writes against the migrated database keep working and sort after
    # every backfilled row.
    forced = AtlasPromotionDecision(
        decision_id="decision_c",
        candidate_id="legacy_c",
        production_run_id="prod",
        candidate_run_id="cand",
        verdict=AtlasPromotionVerdict.PROMOTE_ELIGIBLE,
        overall_production_pass_rate=0.5,
        overall_candidate_pass_rate=0.9,
        critical_regressions=[],
        decided_at=datetime.now(timezone.utc),
    )
    store.promote(forced, reason="first promotion after migration")
    assert [item.candidate_id for item in store.history()] == ["legacy_c", "legacy_b", "legacy_a"]


def test_adapter_capabilities_are_honestly_all_unsupported_right_now() -> None:
    for adapter in AtlasAdapterId:
        capability = report_adapter_capability(adapter)
        assert capability.can_load is False
        assert capability.can_unload is False
        assert capability.can_hot_swap is False
        assert "falls back to its core" in capability.detail
    assert len(report_all_adapter_capabilities()) == len(list(AtlasAdapterId))
