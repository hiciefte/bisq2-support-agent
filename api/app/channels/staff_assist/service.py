"""Staff-assist payload generation and publication helpers."""

from __future__ import annotations

import inspect
import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.channels.policy import get_ai_response_mode

logger = logging.getLogger(__name__)


@dataclass
class StaffAssistPayload:
    """Snapshot payload for staff-side AI assistance."""

    case_id: str
    channel_id: str
    thread_id: str
    room_or_conversation_id: str
    state: str
    question: str
    draft_answer: str | None
    knowledge_sources: list[dict[str, Any]]
    ai_response_mode: str
    updated_at: str


class StaffAssistService:
    """Publishes Draft Assistant and Knowledge Amplifier payloads."""

    def __init__(
        self,
        *,
        policy_service: Any | None = None,
        publisher: Any | None = None,
        max_cached_threads: int = 500,
    ) -> None:
        self.policy_service = policy_service
        self.publisher = publisher
        self.max_cached_threads = max(1, int(max_cached_threads))
        self._latest_by_thread: OrderedDict[str, StaffAssistPayload] = OrderedDict()

    @staticmethod
    def _case_key(channel_id: str | None, thread_id: str) -> str:
        normalized_thread = str(thread_id or "").strip()
        normalized_channel = str(channel_id or "").strip().lower()
        if normalized_channel and normalized_thread:
            return f"{normalized_channel}:{normalized_thread}"
        return normalized_thread

    def latest_for_thread(
        self,
        thread_id: str,
        channel_id: str | None = None,
    ) -> StaffAssistPayload | None:
        """Return latest payload for a thread (primarily for tests/debug)."""
        key = self._case_key(channel_id, thread_id)
        payload = self._latest_by_thread.get(key)
        if payload is not None or channel_id is not None:
            return payload
        normalized_thread = str(thread_id or "").strip()
        for candidate in self._latest_by_thread.values():
            if candidate.thread_id == normalized_thread:
                return candidate
        return None

    async def publish(
        self,
        *,
        channel_id: str,
        thread_id: str,
        room_or_conversation_id: str,
        case_id: str,
        state: str,
        incoming: Any,
        response: Any | None = None,
    ) -> StaffAssistPayload:
        """Publish one staff-assist payload snapshot."""
        normalized_channel = str(channel_id or "").strip().lower()
        normalized_thread = str(thread_id or "").strip()
        payload = StaffAssistPayload(
            case_id=str(case_id or "").strip() or normalized_thread,
            channel_id=normalized_channel,
            thread_id=normalized_thread,
            room_or_conversation_id=str(room_or_conversation_id or "").strip(),
            state=str(state or "").strip().lower() or "waiting_window",
            question=str(getattr(incoming, "question", "") or "").strip(),
            draft_answer=self._extract_draft_answer(response),
            knowledge_sources=self._extract_sources(response),
            ai_response_mode=get_ai_response_mode(
                self.policy_service, normalized_channel
            ),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        case_key = self._case_key(normalized_channel, normalized_thread)
        self._latest_by_thread[case_key] = payload
        self._latest_by_thread.move_to_end(case_key)
        self._evict_oldest_if_needed()
        await self._publish_to_sink(payload)
        return payload

    def clear_thread(self, thread_id: str, channel_id: str | None = None) -> None:
        """Forget retained payload for a finished thread."""
        key = self._case_key(channel_id, thread_id)
        removed = self._latest_by_thread.pop(key, None)
        if removed is not None or channel_id is not None:
            return
        normalized_thread = str(thread_id or "").strip()
        for existing_key, payload in list(self._latest_by_thread.items()):
            if payload.thread_id == normalized_thread:
                self._latest_by_thread.pop(existing_key, None)

    def _evict_oldest_if_needed(self) -> None:
        while len(self._latest_by_thread) > self.max_cached_threads:
            self._latest_by_thread.popitem(last=False)

    @staticmethod
    def _extract_draft_answer(response: Any | None) -> str | None:
        if response is None:
            return None
        answer = str(getattr(response, "answer", "") or "").strip()
        return answer or None

    @staticmethod
    def _extract_sources(response: Any | None) -> list[dict[str, Any]]:
        if response is None:
            return []
        output: list[dict[str, Any]] = []
        for source in list(getattr(response, "sources", []) or []):
            if hasattr(source, "model_dump"):
                output.append(source.model_dump())
            elif isinstance(source, dict):
                output.append(dict(source))
        return output

    async def _publish_to_sink(self, payload: StaffAssistPayload) -> None:
        if self.publisher is None:
            return

        publish = getattr(self.publisher, "publish", None)
        if not callable(publish):
            return

        try:
            result = publish(payload)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "Failed to publish staff-assist payload for thread=%s",
                payload.thread_id,
            )
