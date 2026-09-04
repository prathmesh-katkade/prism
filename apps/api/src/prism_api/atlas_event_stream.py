"""Durable Atlas SSE transport invariants.

The run snapshot and append-only event journal are stored separately. Writers
already append terminal events before exposing a terminal plan state, but the
transport must also fail closed: it never closes a terminal SSE stream until
the matching durable terminal event has actually been observed and emitted.

This prevents a transient read/transaction visibility race from producing a
COMPLETED/FAILED/CANCELLED API view whose SSE projection omits the event that
explains that terminal state.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Protocol

from prism_api_contracts import AtlasPlanState, AtlasRunEventType, AtlasRunResponse

from .transport import ServerSentEvent


class AtlasRunReader(Protocol):
    def get(self, run_id: str) -> AtlasRunResponse: ...


_TERMINAL_EVENT_BY_STATE = {
    AtlasPlanState.COMPLETED: AtlasRunEventType.RUN_COMPLETED,
    AtlasPlanState.FAILED: AtlasRunEventType.RUN_FAILED,
    AtlasPlanState.CANCELLED: AtlasRunEventType.RUN_CANCELLED,
}


async def durable_stream_events(run_store: AtlasRunReader, run_id: str) -> AsyncIterator[str]:
    """Stream the durable journal and close only after its terminal event.

    The terminal plan state alone is deliberately insufficient to terminate
    the generator. The matching journal event is the auditable explanation of
    that state and therefore must be visible to the client first.
    """

    yielded = 0
    while True:
        run = run_store.get(run_id)
        for event in [item for item in run.events if item.sequence > yielded]:
            yield ServerSentEvent(
                event="atlas.run",
                id=event.event_id,
                data=event.model_dump(mode="json"),
            ).encode()
            yielded = event.sequence

        terminal_event = _TERMINAL_EVENT_BY_STATE.get(run.plan.state)
        if terminal_event is not None and any(
            event.type == terminal_event and event.sequence <= yielded for event in run.events
        ):
            return

        await asyncio.sleep(0.05)
