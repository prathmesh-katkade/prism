"""Interruptible in-process Query Job Runtime for the Phase 4 SQL Lab slice."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, Lock, Timer
from typing import Callable, Optional


@dataclass
class QueryJob:
    run_id: str
    cancelled: Event = field(default_factory=Event)
    timed_out: Event = field(default_factory=Event)
    completed: Event = field(default_factory=Event)
    interrupt: Optional[Callable[[], None]] = None
    lock: Lock = field(default_factory=Lock)
    future: Optional[Future[None]] = None

    def attach_interrupt(self, interrupt: Callable[[], None]) -> bool:
        with self.lock:
            self.interrupt = interrupt
            stopped = self.cancelled.is_set() or self.timed_out.is_set()
            if stopped:
                interrupt()
            return stopped

    def request_stop(self, timed_out: bool = False) -> bool:
        if self.completed.is_set():
            return False
        (self.timed_out if timed_out else self.cancelled).set()
        with self.lock:
            if self.interrupt is not None:
                self.interrupt()
        return True


class QueryJobRuntime:
    """Small job seam that can be replaced by the future durable PRISM runtime."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="prism-sql")
        self._jobs: dict[str, QueryJob] = {}
        self._lock = Lock()

    def start(self, run_id: str, timeout_ms: int, work: Callable[[QueryJob], None]) -> QueryJob:
        job = QueryJob(run_id=run_id)
        with self._lock:
            self._jobs[run_id] = job
        timer = Timer(timeout_ms / 1000, lambda: job.request_stop(timed_out=True))

        def wrapped() -> None:
            timer.start()
            try:
                work(job)
            finally:
                timer.cancel()
                job.completed.set()

        job.future = self._executor.submit(wrapped)
        return job

    def get(self, run_id: str) -> QueryJob | None:
        with self._lock:
            return self._jobs.get(run_id)

    def cancel(self, run_id: str) -> bool:
        job = self.get(run_id)
        return False if job is None else job.request_stop()


runtime = QueryJobRuntime()
