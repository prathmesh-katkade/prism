from __future__ import annotations

import time
from threading import Event

from prism_api.sql_jobs import QueryJobRuntime


def test_query_job_runtime_cancels_an_in_flight_job() -> None:
    runtime = QueryJobRuntime()
    started = Event()
    released = Event()

    def work(job) -> None:  # type: ignore[no-untyped-def]
        started.set()
        job.cancelled.wait(1)
        released.set()

    job = runtime.start("cancel-test", 1_000, work)
    assert started.wait(1)
    assert runtime.cancel("cancel-test")
    assert released.wait(1)
    assert job.cancelled.is_set()


def test_query_job_runtime_marks_timeout() -> None:
    runtime = QueryJobRuntime()
    started = Event()
    released = Event()

    def work(job) -> None:  # type: ignore[no-untyped-def]
        started.set()
        job.timed_out.wait(1)
        released.set()

    job = runtime.start("timeout-test", 10, work)
    assert started.wait(1)
    assert released.wait(1)
    time.sleep(0.01)
    assert job.timed_out.is_set()
