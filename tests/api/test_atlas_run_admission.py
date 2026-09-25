from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from prism_api.atlas_run_admission import AtlasRunAdmission
from prism_api.atlas_runtime import (
    AtlasRunStore,
    handle_atlas_run_worker_crash,
    reconcile_stale_in_flight_runs_once,
    runs,
)
from prism_api.durable_atlas_store import DurableAtlasRunStore
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasModelProviderName,
    AtlasPlanState,
    AtlasRunEventType,
    AtlasRunRequest,
    AtlasStepState,
)

# --- AtlasRunAdmission: concurrency, saturation, crash containment -----------------


def test_admission_runs_work_up_to_the_configured_concurrency() -> None:
    admission = AtlasRunAdmission(max_concurrent_runs=3, max_queued_runs=0)
    started = threading.Event()
    release = threading.Event()
    entered = []

    def slow(run_id: str) -> None:
        entered.append(run_id)
        if len(entered) == 3:
            started.set()
        release.wait(timeout=5)

    try:
        for i in range(3):
            assert admission.try_reserve()
            admission.dispatch(f"run_{i}", slow)
        assert started.wait(timeout=2), "all 3 concurrent slots should run in parallel"
        assert admission.snapshot().in_flight == 3
        assert admission.snapshot().available == 0
    finally:
        release.set()
        admission.shutdown(wait=True)


def test_admission_rejects_reservation_once_saturated_and_frees_on_completion() -> None:
    admission = AtlasRunAdmission(max_concurrent_runs=1, max_queued_runs=1)
    release = threading.Event()

    def blocking(run_id: str) -> None:
        release.wait(timeout=5)

    try:
        assert admission.try_reserve()
        admission.dispatch("run_a", blocking)
        assert admission.try_reserve()  # fills the queued slot
        admission.dispatch("run_b", blocking)

        # capacity (1 concurrent + 1 queued) is now fully consumed
        assert admission.try_reserve() is False
        snapshot = admission.snapshot()
        assert snapshot.saturated is True
        assert snapshot.available == 0
    finally:
        release.set()
        admission.shutdown(wait=True)

    # after work drains, a fresh reservation must succeed again
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and admission.snapshot().in_flight != 0:
        time.sleep(0.01)
    assert admission.snapshot().in_flight == 0


def test_release_without_dispatch_returns_the_reservation() -> None:
    admission = AtlasRunAdmission(max_concurrent_runs=1, max_queued_runs=0)
    assert admission.try_reserve()
    assert admission.try_reserve() is False  # capacity is exhausted
    admission.release_without_dispatch()
    assert admission.try_reserve() is True  # the give-back is visible immediately
    admission.release_without_dispatch()


def test_dispatch_failure_releases_the_reserved_capacity() -> None:
    admission = AtlasRunAdmission(max_concurrent_runs=1, max_queued_runs=0)
    admission.shutdown(wait=True)
    assert admission.try_reserve()
    with pytest.raises(RuntimeError):
        admission.dispatch("cannot-dispatch", lambda run_id: None)
    assert admission.snapshot().in_flight == 0
    assert admission.try_reserve()
    admission.release_without_dispatch()


def test_admission_crash_containment_invokes_the_callback_and_releases_capacity() -> None:
    seen: list[tuple[str, BaseException]] = []
    done = threading.Event()

    def on_crash(run_id: str, error: BaseException) -> None:
        seen.append((run_id, error))
        done.set()

    admission = AtlasRunAdmission(max_concurrent_runs=1, max_queued_runs=0, on_worker_crash=on_crash)

    def boom(run_id: str) -> None:
        raise RuntimeError("simulated unexpected worker crash")

    try:
        assert admission.try_reserve()
        admission.dispatch("crashy", boom)
        assert done.wait(timeout=2)
        assert seen and seen[0][0] == "crashy"
        assert isinstance(seen[0][1], RuntimeError)
        # capacity must be released even though the target raised
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and admission.snapshot().in_flight != 0:
            time.sleep(0.01)
        assert admission.snapshot().in_flight == 0
        assert admission.try_reserve() is True
    finally:
        admission.shutdown(wait=True)


def test_admission_crash_handler_itself_raising_does_not_leak_the_reservation() -> None:
    # Defensive: even a broken callback must not prevent the finally-block
    # release.
    admission = AtlasRunAdmission(
        max_concurrent_runs=1, max_queued_runs=0, on_worker_crash=lambda *a: 1 / 0
    )

    def boom(run_id: str) -> None:
        raise RuntimeError("boom")

    try:
        assert admission.try_reserve()
        admission.dispatch("crashy", boom)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and admission.snapshot().in_flight != 0:
            time.sleep(0.01)
        assert admission.snapshot().in_flight == 0
    finally:
        admission.shutdown(wait=True)


def test_invalid_capacity_configuration_fails_closed() -> None:
    with pytest.raises(ValueError):
        AtlasRunAdmission(max_concurrent_runs=0)
    with pytest.raises(ValueError):
        AtlasRunAdmission(max_concurrent_runs=1, max_queued_runs=-1)


# --- HTTP-level: saturation and crash containment through the real route -----------


def test_start_run_returns_503_when_admission_is_saturated(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas as atlas_routes

    class _AlwaysSaturated:
        def try_reserve(self) -> bool:
            return False

    monkeypatch.setattr(atlas_routes, "run_admission", _AlwaysSaturated())
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("unknown.csv", b"a,b\n1,2\n", "text/csv")},
    )
    dataset_id = response.json()["dataset_id"]

    response = client.post(
        "/api/v1/atlas/runs",
        json={"dataset_id": dataset_id, "objective": "Understand this dataset."},
    )

    assert response.status_code == 503


def test_start_run_never_creates_a_durable_run_when_saturated(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas as atlas_routes

    class _AlwaysSaturated:
        def try_reserve(self) -> bool:
            return False

    before = set(runs.list_recent_run_ids(limit=1000))
    monkeypatch.setattr(atlas_routes, "run_admission", _AlwaysSaturated())
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("unknown.csv", b"a,b\n1,2\n", "text/csv")},
    )
    dataset_id = response.json()["dataset_id"]

    client.post(
        "/api/v1/atlas/runs",
        json={"dataset_id": dataset_id, "objective": "Understand this dataset."},
    )

    after = set(runs.list_recent_run_ids(limit=1000))
    assert after == before  # no orphaned run record left behind


def test_worker_crash_during_a_real_dispatched_run_durably_fails_it(monkeypatch, tmp_path, caplog) -> None:  # type: ignore[no-untyped-def]
    # End-to-end proof of the concrete harm this closes: an unexpected
    # exception inside execute() (not an HTTPException) must not leave the
    # run stuck RUNNING forever.
    url = f"sqlite:///{(tmp_path / 'crash.sqlite').as_posix()}"
    store = AtlasRunStore(DurableAtlasRunStore(url))
    run = store.create(
        AtlasRunRequest(dataset_id="does-not-exist-anywhere", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )

    def exploding_execute(run_id: str) -> None:
        # Simulate a bug: something other than HTTPException escapes.
        raise KeyError("secret-bearing unexpected defect must not reach durable state")

    # handle_atlas_run_worker_crash closes over the module-level `runs`
    # singleton; point it at this test's isolated store.
    monkeypatch.setattr("prism_api.atlas_runtime.runs", store)
    from prism_api.atlas_run_admission import AtlasRunAdmission as _Admission

    admission = _Admission(
        max_concurrent_runs=1, max_queued_runs=0, on_worker_crash=handle_atlas_run_worker_crash
    )
    try:
        assert admission.try_reserve()
        admission.dispatch(run.run_id, exploding_execute)
        deadline = time.monotonic() + 2
        terminal = None
        while time.monotonic() < deadline:
            terminal = store.get(run.run_id)
            if terminal.plan.state is AtlasPlanState.FAILED:
                break
            time.sleep(0.01)
        assert terminal is not None and terminal.plan.state is AtlasPlanState.FAILED
        failure_events = [e for e in terminal.events if e.type is AtlasRunEventType.RUN_FAILED]
        assert failure_events and failure_events[0].payload.get("reason") == "worker_crashed"
        assert "secret-bearing" not in str(failure_events[0].payload)
        assert "secret-bearing" not in (terminal.uncertainty or "")
        assert "secret-bearing" not in caplog.text
    finally:
        admission.shutdown(wait=True)


def test_worker_crash_handler_never_clobbers_an_already_terminal_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{(tmp_path / 'terminal.sqlite').as_posix()}"
    store = AtlasRunStore(DurableAtlasRunStore(url))
    run = store.create(
        AtlasRunRequest(dataset_id="ds", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )
    # Force it to a genuine terminal COMPLETED state without ever executing.
    store.update(
        run.model_copy(update={"plan": run.plan.model_copy(update={"state": AtlasPlanState.COMPLETED})})
    )

    import prism_api.atlas_runtime as atlas_runtime_module

    original_runs = atlas_runtime_module.runs
    atlas_runtime_module.runs = store
    try:
        handle_atlas_run_worker_crash(run.run_id, RuntimeError("late/spurious crash report"))
    finally:
        atlas_runtime_module.runs = original_runs

    terminal = store.get(run.run_id)
    assert terminal.plan.state is AtlasPlanState.COMPLETED  # untouched
    assert not [e for e in terminal.events if e.type is AtlasRunEventType.RUN_FAILED]


def test_atomic_failure_transition_refuses_a_completed_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = AtlasRunStore(DurableAtlasRunStore(f"sqlite:///{(tmp_path / 'atomic.sqlite').as_posix()}"))
    run = store.create(
        AtlasRunRequest(dataset_id="ds", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )
    store.update(
        run.model_copy(update={"plan": run.plan.model_copy(update={"state": AtlasPlanState.COMPLETED})})
    )

    changed = store.fail_if_in_flight(
        run.run_id,
        reason="late_worker_crash",
        detail="A stale callback must lose to the terminal state.",
    )

    terminal = store.get(run.run_id)
    assert changed is False
    assert terminal.plan.state is AtlasPlanState.COMPLETED
    assert not [event for event in terminal.events if event.type is AtlasRunEventType.RUN_FAILED]


# --- Restart reconciliation: idempotency and no fabricated completion --------------


def test_reconciliation_marks_stale_draft_and_running_runs_failed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{(tmp_path / 'stale.sqlite').as_posix()}"
    store = AtlasRunStore(DurableAtlasRunStore(url))
    draft_run = store.create(
        AtlasRunRequest(dataset_id="ds-draft", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )
    running_run = store.create(
        AtlasRunRequest(dataset_id="ds-running", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )
    running_run = store.update(
        running_run.model_copy(
            update={"plan": running_run.plan.model_copy(update={"state": AtlasPlanState.RUNNING})}
        )
    )
    assert draft_run.plan.state is AtlasPlanState.DRAFT
    assert running_run.plan.state is AtlasPlanState.RUNNING

    reconciled = store.reconcile_stale_in_flight_runs()

    assert reconciled == 2
    for run_id in (draft_run.run_id, running_run.run_id):
        terminal = store.get(run_id)
        assert terminal.plan.state is AtlasPlanState.FAILED
        reasons = [
            e.payload.get("reason")
            for e in terminal.events
            if e.type is AtlasRunEventType.RUN_FAILED
        ]
        assert "stale_in_flight_after_restart" in reasons


def test_reconciliation_is_idempotent_and_never_double_reports(tmp_path) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{(tmp_path / 'idempotent.sqlite').as_posix()}"
    store = AtlasRunStore(DurableAtlasRunStore(url))
    run = store.create(
        AtlasRunRequest(dataset_id="ds", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )

    first = store.reconcile_stale_in_flight_runs()
    second = store.reconcile_stale_in_flight_runs()

    assert first == 1
    assert second == 0  # already terminal -- nothing left to reconcile
    terminal = store.get(run.run_id)
    failure_events = [e for e in terminal.events if e.type is AtlasRunEventType.RUN_FAILED]
    assert len(failure_events) == 1  # never double-appended


def test_reconciliation_never_touches_a_legitimately_completed_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{(tmp_path / 'completed.sqlite').as_posix()}"
    store = AtlasRunStore(DurableAtlasRunStore(url))
    run = store.create(
        AtlasRunRequest(dataset_id="ds", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )
    store.update(
        run.model_copy(
            update={
                "plan": run.plan.model_copy(
                    update={
                        "state": AtlasPlanState.COMPLETED,
                        "steps": [s.model_copy(update={"state": AtlasStepState.COMPLETED}) for s in run.plan.steps],
                    }
                ),
                "answer": "A real, completed answer.",
            }
        )
    )

    reconciled = store.reconcile_stale_in_flight_runs()

    assert reconciled == 0
    terminal = store.get(run.run_id)
    assert terminal.plan.state is AtlasPlanState.COMPLETED
    assert terminal.answer == "A real, completed answer."
    assert not [e for e in terminal.events if e.type is AtlasRunEventType.RUN_FAILED]


def test_reconcile_stale_in_flight_runs_once_only_runs_a_single_time() -> None:
    import prism_api.atlas_runtime as atlas_runtime_module

    calls: list[int] = []
    original = atlas_runtime_module.runs.reconcile_stale_in_flight_runs

    def counting() -> int:
        calls.append(1)
        return original()

    atlas_runtime_module.runs.reconcile_stale_in_flight_runs = counting  # type: ignore[method-assign]
    try:
        atlas_runtime_module._startup_reconciliation_done = False
        reconcile_stale_in_flight_runs_once()
        reconcile_stale_in_flight_runs_once()
        reconcile_stale_in_flight_runs_once()
        assert len(calls) == 1
    finally:
        atlas_runtime_module.runs.reconcile_stale_in_flight_runs = original  # type: ignore[method-assign]
        atlas_runtime_module._startup_reconciliation_done = True


# --- Race regression: concurrent submits at the exact capacity boundary ------------


def test_concurrent_submits_never_exceed_configured_capacity() -> None:
    admission = AtlasRunAdmission(max_concurrent_runs=2, max_queued_runs=2)  # capacity 4
    accepted = []
    rejected = []
    lock = threading.Lock()
    release = threading.Event()
    barrier = threading.Barrier(10)

    def worker(run_id: str) -> None:
        release.wait(timeout=5)

    def attempt(i: str) -> None:
        barrier.wait(timeout=5)
        ok = admission.try_reserve()
        with lock:
            (accepted if ok else rejected).append(i)
        if ok:
            admission.dispatch(i, worker)

    threads = [threading.Thread(target=attempt, args=(f"run_{i}",)) for i in range(10)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        # exactly capacity (4) admitted, the rest cleanly rejected -- no more,
        # no fewer, regardless of thread interleaving
        assert len(accepted) == 4
        assert len(rejected) == 6
        assert len(set(accepted) | set(rejected)) == 10
    finally:
        release.set()
        admission.shutdown(wait=True)
