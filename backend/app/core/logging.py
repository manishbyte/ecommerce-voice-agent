"""Logging setup and the real-time agent execution event bus.

Events are emitted by the graph nodes / tools / voice layer, persisted to
`conversation_events`, and fanned out to any subscribed WebSocket session.
Summaries are intentionally short and safe: no prompts, keys or chain-of-thought.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from app.core.security import sanitize_for_log
from app.database.base import utcnow

log = logging.getLogger("events")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, conversation_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs[conversation_id].add(q)
        return q

    def unsubscribe(self, conversation_id: str, q: asyncio.Queue) -> None:
        self._subs[conversation_id].discard(q)
        if not self._subs[conversation_id]:
            self._subs.pop(conversation_id, None)

    def publish(self, conversation_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(conversation_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer: drop rather than block the agent
                pass


bus = EventBus()


async def emit_event(conversation_id: str | None, event_type: str, *, agent: str | None = None,
                     status: str = "ok", summary: str = "", data: dict | None = None) -> dict:
    event = {
        "type": event_type, "agent": agent, "status": status,
        "summary": sanitize_for_log(summary, 240), "data": data or {},
        "conversation_id": conversation_id, "timestamp": utcnow().isoformat(),
    }
    if not conversation_id:
        return event
    bus.publish(conversation_id, event)
    try:  # persistence must never break a customer turn
        import uuid

        from app.database.connection import get_sessionmaker
        from app.models.conversation import ConversationEvent

        async with get_sessionmaker()() as s:
            s.add(ConversationEvent(conversation_pk=uuid.UUID(conversation_id), event_type=event_type,
                                    agent=agent, status=status, summary=event["summary"], data=event["data"]))
            await s.commit()
    except Exception as exc:  # noqa: BLE001
        log.debug("event persistence skipped: %s", exc)
    return event
