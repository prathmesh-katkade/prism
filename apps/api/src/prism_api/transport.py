from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Optional

from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field


class ServerSentEvent(BaseModel):
    """Typed event envelope shared by future server event producers."""

    model_config = ConfigDict(extra="forbid")

    event: str = Field(min_length=1)
    data: dict[str, Any]
    id: Optional[str] = None

    def encode(self) -> str:
        lines = [f"event: {self.event}"]
        if self.id is not None:
            lines.append(f"id: {self.id}")
        lines.append(f"data: {json.dumps(self.data, separators=(',', ':'))}")
        return "\n".join(lines) + "\n\n"


async def phase_1_event_stream() -> AsyncIterator[str]:
    """A finite discovery event proves the SSE transport without feature events."""
    yield ServerSentEvent(
        event="platform.ready",
        data={"contractVersion": "v1", "phase": 1},
    ).encode()


def sse_response(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
