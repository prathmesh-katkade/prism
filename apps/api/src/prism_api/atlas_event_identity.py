"""Ordered identities for rapid append-only writes in one Atlas server process."""

from __future__ import annotations

import threading
import time
import uuid

_lock = threading.Lock()
_last_tick = 0


def ordered_event_id(prefix: str) -> str:
    """Preserve generation order even when the Windows wall clock repeats.

    ``time_ns`` expresses units, not clock resolution. A UUID suffix provides
    uniqueness but cannot order events sharing a clock tick. Keep the existing
    identifier format and advance the numeric portion under a lock. This is a
    process-local tie-breaker, not a distributed transaction sequence.
    """
    global _last_tick
    with _lock:
        _last_tick = max(time.time_ns(), _last_tick + 1)
        tick = _last_tick
    return f"{prefix}_{tick:020d}_{uuid.uuid4().hex}"
