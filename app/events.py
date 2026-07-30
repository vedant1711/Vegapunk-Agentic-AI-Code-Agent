"""Event bus for streaming pipeline events to the frontend via SSE."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """A single event emitted by a pipeline step."""
    timestamp: float
    step: str            # short functional name, e.g. "Router"
    message: str
    level: str           # "info" | "success" | "warning" | "error"
    task_id: str
    event_type: str = "log"           # "log" | "step_start" | "step_end" | "run_end"
    duration_ms: int | None = None    # populated on step_end and run_end
    step_status: str | None = None    # populated on step_end: "success" | "warning" | "error"


def _is_terminal(event: AgentEvent) -> bool:
    """Whether an event marks the end of a run."""
    if event.event_type == "run_end":
        return True
    msg = event.message
    return (
        msg.startswith("Run finished")
        or msg.startswith("Task failed")
        or "finished" in msg.lower()
    )


class EventBus:
    """In-memory event bus. Broadcasts pipeline events to SSE subscribers."""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._history: dict[str, list[AgentEvent]] = {}

    def _publish(self, event: AgentEvent) -> None:
        self._history.setdefault(event.task_id, []).append(event)
        for queue in self._subscribers.get(event.task_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def emit(self, task_id: str, step: str, message: str, level: str = "info") -> None:
        """Emit a log line from a step."""
        self._publish(AgentEvent(
            timestamp=time.time(),
            step=step,
            message=message,
            level=level,
            task_id=task_id,
        ))

    def step_start(self, task_id: str, step: str) -> None:
        """Mark the beginning of a pipeline step."""
        self._publish(AgentEvent(
            timestamp=time.time(),
            step=step,
            message=f"{step} started",
            level="info",
            task_id=task_id,
            event_type="step_start",
        ))

    def step_end(
        self,
        task_id: str,
        step: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        """Mark the completion of a pipeline step with its final status."""
        level = status if status in ("success", "warning", "error") else "info"
        self._publish(AgentEvent(
            timestamp=time.time(),
            step=step,
            message=f"{step} {status}",
            level=level,
            task_id=task_id,
            event_type="step_end",
            duration_ms=int(duration_seconds * 1000),
            step_status=status,
        ))

    def run_end(
        self,
        task_id: str,
        message: str,
        level: str = "success",
        duration_seconds: float | None = None,
    ) -> None:
        """Signal the run has finished (success or failure)."""
        self._publish(AgentEvent(
            timestamp=time.time(),
            step="System",
            message=message,
            level=level,
            task_id=task_id,
            event_type="run_end",
            duration_ms=int(duration_seconds * 1000) if duration_seconds is not None else None,
        ))

    async def subscribe(self, task_id: str) -> AsyncIterator[AgentEvent]:
        """Subscribe to events for a task. Yields events as they arrive."""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(task_id, []).append(queue)

        try:
            # Replay history first. If the run already finished before this
            # subscriber connected, exit right after replay so the client
            # does not hang waiting on an empty queue.
            history_finished = False
            for event in list(self._history.get(task_id, [])):
                yield event
                if _is_terminal(event):
                    history_finished = True
            if history_finished:
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event
                    if _is_terminal(event):
                        break
                except TimeoutError:
                    yield AgentEvent(
                        timestamp=time.time(),
                        step="System",
                        message="keepalive",
                        level="info",
                        task_id=task_id,
                    )
        finally:
            queues = self._subscribers.get(task_id)
            if queues and queue in queues:
                queues.remove(queue)
                if not queues:
                    del self._subscribers[task_id]

    def get_history(self, task_id: str) -> list[AgentEvent]:
        return self._history.get(task_id, [])

    def clear(self, task_id: str) -> None:
        self._history.pop(task_id, None)


event_bus = EventBus()
