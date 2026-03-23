"""Event bus for streaming agent events to the frontend via SSE."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """A single event from an agent satellite."""
    timestamp: float
    satellite: str  # e.g. "Shaka (Router)"
    message: str
    level: str  # "info", "success", "warning", "error"
    task_id: str


class EventBus:
    """In-memory event bus — broadcasts agent events to SSE subscribers."""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}  # task_id → queues
        self._history: dict[str, list[AgentEvent]] = {}  # task_id → past events

    def emit(self, task_id: str, satellite: str, message: str, level: str = "info"):
        """Emit an event for a task."""
        event = AgentEvent(
            timestamp=time.time(),
            satellite=satellite,
            message=message,
            level=level,
            task_id=task_id,
        )

        # Store in history
        if task_id not in self._history:
            self._history[task_id] = []
        self._history[task_id].append(event)

        # Broadcast to subscribers
        for queue in self._subscribers.get(task_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is too slow

    async def subscribe(self, task_id: str) -> AsyncIterator[AgentEvent]:
        """Subscribe to events for a task. Yields events as they arrive."""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=100)

        if task_id not in self._subscribers:
            self._subscribers[task_id] = []
        self._subscribers[task_id].append(queue)

        # Send history first
        for event in self._history.get(task_id, []):
            yield event

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event
                    if event.message.startswith("🏁") or "finished" in event.message.lower():
                        break  # Agent done
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield AgentEvent(
                        timestamp=time.time(),
                        satellite="System",
                        message="keepalive",
                        level="info",
                        task_id=task_id,
                    )
        finally:
            self._subscribers[task_id].remove(queue)
            if not self._subscribers[task_id]:
                del self._subscribers[task_id]

    def get_history(self, task_id: str) -> list[AgentEvent]:
        return self._history.get(task_id, [])

    def clear(self, task_id: str):
        self._history.pop(task_id, None)


# Global singleton
event_bus = EventBus()
