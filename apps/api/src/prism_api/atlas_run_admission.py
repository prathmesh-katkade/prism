"""Bounded admission boundary for Atlas run execution.

Before this wave, ``POST /api/v1/atlas/runs`` spawned one unbounded
``daemon=True`` thread per accepted run with no admission control at all --
any number of concurrent runs could be started, and any exception escaping
``execute()`` other than ``HTTPException`` (a bug, an unexpected library
error, a resource exhaustion error) left the run durably stuck at RUNNING
forever: no terminal state, no RUN_FAILED event, and no visible failure
anywhere. This module is the small, directly testable boundary that
replaces that.

Two separate concerns, both handled here:

1. **Admission** -- ``try_reserve()``/``release_without_dispatch()``/
   ``dispatch()`` bound how much work may be in flight (running or queued)
   at once via a fixed-size ``ThreadPoolExecutor`` behind a bounded
   semaphore. Admission is a synchronous, non-blocking, O(1) decision at
   request time -- a saturated boundary is rejected immediately, never
   silently queued without limit.
2. **Crash containment** -- every dispatched unit of work is wrapped so that
   *any* exception it raises (not just the ones its own code already
   handles) is caught, logged, and reported through an injected callback
   before the admission slot is released. The caller (``atlas_runtime.py``)
   supplies that callback to durably mark the run FAILED; this module has no
   Atlas-specific knowledge and stays independently testable.

Trade-off, stated plainly: ``ThreadPoolExecutor`` workers are not daemon
threads (the standard library does not support that), unlike the
``threading.Thread(daemon=True)`` this replaces. A worker stuck forever
could therefore delay process exit where the old code would not have. This
is an accepted trade-off for gaining a bounded, testable admission boundary
and guaranteed crash containment; every code path Atlas actually runs today
completes in well under the platform's own step/sandbox timeouts.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger("prism_api.atlas_run_admission")

DEFAULT_MAX_CONCURRENT_RUNS = 8
DEFAULT_MAX_QUEUED_RUNS = 32


@dataclass(frozen=True)
class AdmissionSnapshot:
    """A point-in-time, inspectable view of the admission boundary's state."""

    max_concurrent_runs: int
    max_queued_runs: int
    in_flight: int

    @property
    def capacity(self) -> int:
        return self.max_concurrent_runs + self.max_queued_runs

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.in_flight)

    @property
    def saturated(self) -> bool:
        return self.available == 0


class AtlasRunAdmission:
    """A fixed-size worker pool behind a bounded, non-blocking admission gate.

    A reservation obtained from ``try_reserve()`` MUST be resolved exactly
    once, either by ``dispatch()`` (hands it real work) or
    ``release_without_dispatch()`` (the reservation was never used -- e.g.
    the caller failed to durably create the run record after reserving
    capacity for it).
    """

    def __init__(
        self,
        *,
        max_concurrent_runs: int = DEFAULT_MAX_CONCURRENT_RUNS,
        max_queued_runs: int = DEFAULT_MAX_QUEUED_RUNS,
        on_worker_crash: Optional[Callable[[str, BaseException], None]] = None,
        thread_name_prefix: str = "atlas-run",
    ) -> None:
        if max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be at least 1.")
        if max_queued_runs < 0:
            raise ValueError("max_queued_runs must not be negative.")
        self._max_concurrent_runs = max_concurrent_runs
        self._max_queued_runs = max_queued_runs
        self._admission = threading.BoundedSemaphore(max_concurrent_runs + max_queued_runs)
        self._lock = threading.Lock()
        self._in_flight = 0
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_runs, thread_name_prefix=thread_name_prefix
        )
        self._on_worker_crash = on_worker_crash

    def try_reserve(self) -> bool:
        """Attempt to admit one unit of work. Non-blocking; returns False when saturated."""
        admitted = self._admission.acquire(blocking=False)
        if admitted:
            with self._lock:
                self._in_flight += 1
        return admitted

    def release_without_dispatch(self) -> None:
        """Give back a reservation that will never be dispatched."""
        with self._lock:
            self._in_flight -= 1
        self._admission.release()

    def dispatch(self, run_id: str, target: Callable[[str], None]) -> None:
        """Hand a previously reserved slot real work. Consumes the reservation
        exactly once it finishes (success, handled failure, or crash)."""
        try:
            self._executor.submit(self._run, run_id, target)
        except BaseException:
            self.release_without_dispatch()
            raise

    def _run(self, run_id: str, target: Callable[[str], None]) -> None:
        try:
            target(run_id)
        except BaseException as error:  # noqa: BLE001 -- this is the last line of defense
            # target() (Atlas's execute()) already durably handles the
            # exceptions it knows about (HTTPException). Anything else
            # reaching here is exactly the "worker crashed" case this module
            # exists to contain: the admission slot must still be released,
            # and the run must never be left silently RUNNING.
            # The exception message may contain row values, generated code, or
            # provider detail. Keep logs useful without copying that untrusted
            # text into operational output; the durable callback records a
            # generic user-facing failure tied to the run ID.
            logger.error(
                "atlas_run_worker_crashed run_id=%s error_type=%s",
                run_id,
                type(error).__name__,
            )
            if self._on_worker_crash is not None:
                try:
                    self._on_worker_crash(run_id, error)
                except Exception:
                    logger.exception("atlas_run_crash_handler_failed run_id=%s", run_id)
        finally:
            with self._lock:
                self._in_flight -= 1
            self._admission.release()

    def snapshot(self) -> AdmissionSnapshot:
        with self._lock:
            in_flight = self._in_flight
        return AdmissionSnapshot(
            max_concurrent_runs=self._max_concurrent_runs,
            max_queued_runs=self._max_queued_runs,
            in_flight=in_flight,
        )

    def shutdown(self, *, wait: bool = False) -> None:
        # Already-admitted queued work must run so its finally block releases
        # capacity and records a terminal result. Cancelling futures that have
        # not started would skip that boundary entirely.
        self._executor.shutdown(wait=wait, cancel_futures=False)
