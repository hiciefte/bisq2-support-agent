"""In-process event fan-out for user-facing escalation updates."""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator, DefaultDict, Set

from app.models.escalation import Escalation


class EscalationEventBroker:
    """Publish latest escalation state to subscribers for one message ID."""

    def __init__(self) -> None:
        self._subscribers: DefaultDict[str, Set[asyncio.Queue[Escalation]]] = (
            defaultdict(set)
        )
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def subscribe(
        self, message_id: str
    ) -> AsyncIterator[asyncio.Queue[Escalation]]:
        queue: asyncio.Queue[Escalation] = asyncio.Queue(maxsize=1)
        async with self._lock:
            self._subscribers[message_id].add(queue)

        try:
            yield queue
        finally:
            async with self._lock:
                queues = self._subscribers.get(message_id)
                if not queues:
                    return
                queues.discard(queue)
                if not queues:
                    self._subscribers.pop(message_id, None)

    async def publish(self, escalation: Escalation) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(escalation.message_id, set()))

        for queue in queues:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(escalation)
