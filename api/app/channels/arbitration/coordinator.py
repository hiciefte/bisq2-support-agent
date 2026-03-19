"""Group-channel human-first arbitration coordinator."""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.channels.models import (
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
)
from app.channels.policy import (
    get_acknowledgment_message_template,
    get_acknowledgment_mode,
    get_acknowledgment_reaction_key,
    get_ai_response_mode,
    get_dispatch_failure_message_template,
    get_escalation_user_notice_template,
    get_first_response_delay_seconds,
    get_hitl_approval_timeout_seconds,
    get_staff_active_cooldown_seconds,
    get_timer_jitter_max_seconds,
)
from app.channels.response_dispatcher import ChannelResponseDispatcher

logger = logging.getLogger(__name__)


@dataclass
class _ThreadEntry:
    thread_id: str
    channel_id: str
    room_or_conversation_id: str
    first_incoming: IncomingMessage
    latest_incoming: IncomingMessage
    accumulated_texts: list[str] = field(default_factory=list)
    generation: int = 0
    state: str = "waiting_window"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    timer_fired_at: float | None = None
    prepared_response: Any | None = None
    timer_task: asyncio.Task[None] | None = None
    hitl_task: asyncio.Task[None] | None = None
    on_release: Callable[[IncomingMessage], Awaitable[Any]] | None = None
    on_dispatch: Callable[[IncomingMessage, Any], Awaitable[bool]] | None = None
    channel: Any | None = None

    def build_incoming(self, max_accumulated_chars: int) -> IncomingMessage:
        """Create one synthetic IncomingMessage from accumulated user messages."""
        texts = [text for text in self.accumulated_texts if text.strip()]
        question = "\n---\n".join(texts) if texts else self.latest_incoming.question
        if len(question) > max_accumulated_chars:
            question = question[-max_accumulated_chars:]

        return self.latest_incoming.model_copy(
            update={
                "message_id": self.first_incoming.message_id,
                "question": question,
                "channel_metadata": dict(self.first_incoming.channel_metadata),
                "user": self.first_incoming.user,
            }
        )


class ArbitrationCoordinator:
    """Coordinates delayed-first-response arbitration for group channels."""

    def __init__(
        self,
        *,
        policy_service: Any | None = None,
        escalation_service: Any | None = None,
        staff_assist_service: Any | None = None,
        max_concurrent_threads: int = 500,
        max_accumulated_messages: int = 10,
        max_accumulated_chars: int = 3600,
        dispatch_retry_delay_seconds: float = 5.0,
    ) -> None:
        self.policy_service = policy_service
        self.escalation_service = escalation_service
        self.staff_assist_service = staff_assist_service
        self.max_concurrent_threads = max(1, int(max_concurrent_threads))
        self.max_accumulated_messages = max(1, int(max_accumulated_messages))
        self.max_accumulated_chars = max(256, int(max_accumulated_chars))
        self.dispatch_retry_delay_seconds = max(
            0.0, float(dispatch_retry_delay_seconds)
        )

        self._threads: dict[str, _ThreadEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_staff_activity_by_room: dict[str, float] = {}

    def has_active_thread(self, thread_id: str | tuple[str, str]) -> bool:
        normalized = self._normalize_thread_id("", thread_id)
        return normalized in self._threads

    async def enqueue(
        self,
        *,
        incoming: IncomingMessage,
        thread_id: str | tuple[str, str],
        room_or_conversation_id: str,
        on_release: Callable[[IncomingMessage], Awaitable[Any]],
        on_dispatch: Callable[[IncomingMessage, Any], Awaitable[bool]],
        channel: Any | None = None,
    ) -> bool:
        """Queue a message for arbitration or dispatch immediately when eligible."""
        channel_id = (
            str(getattr(incoming.channel, "value", incoming.channel) or "")
            .strip()
            .lower()
        )
        normalized_thread = self._normalize_thread_id(channel_id, thread_id)
        normalized_room = (
            str(room_or_conversation_id or "").strip() or normalized_thread
        )
        delay_seconds = get_first_response_delay_seconds(
            self.policy_service, channel_id
        )

        if delay_seconds <= 0:
            response = await on_release(incoming)
            return bool(await on_dispatch(incoming, response))

        if (
            normalized_thread not in self._threads
            and len(self._threads) >= self.max_concurrent_threads
        ):
            logger.warning(
                "Arbitration overflow for channel=%s thread=%s; falling back to immediate dispatch",
                channel_id,
                normalized_thread,
            )
            response = await on_release(incoming)
            return bool(await on_dispatch(incoming, response))

        lock = self._lock_for(normalized_thread)
        should_acknowledge = False
        delay_with_jitter = float(delay_seconds)
        async with lock:
            if self._is_staff_recently_active(normalized_room, channel_id):
                logger.info(
                    "Suppressing arbitration enqueue due to recent staff activity channel=%s room=%s thread=%s",
                    channel_id,
                    normalized_room,
                    normalized_thread,
                )
                return False

            entry = self._threads.get(normalized_thread)
            if entry is None:
                entry = _ThreadEntry(
                    thread_id=normalized_thread,
                    channel_id=channel_id,
                    room_or_conversation_id=normalized_room,
                    first_incoming=incoming,
                    latest_incoming=incoming,
                    accumulated_texts=[str(incoming.question or "").strip()],
                    on_release=on_release,
                    on_dispatch=on_dispatch,
                    channel=channel,
                )
                self._threads[normalized_thread] = entry
                should_acknowledge = True
            else:
                entry.latest_incoming = incoming
                entry.updated_at = time.time()
                entry.state = "waiting_window"
                entry.prepared_response = None
                self._cancel_task(entry.hitl_task)
                entry.hitl_task = None
                text = str(incoming.question or "").strip()
                if text:
                    entry.accumulated_texts.append(text)
                    if len(entry.accumulated_texts) > self.max_accumulated_messages:
                        entry.accumulated_texts = entry.accumulated_texts[
                            -self.max_accumulated_messages :
                        ]

            entry.generation += 1
            self._cancel_task(entry.timer_task)
            delay_with_jitter = self._compute_wait_delay_seconds(
                channel_id=channel_id,
                base_delay_seconds=delay_seconds,
            )
            entry.timer_task = asyncio.create_task(
                self._run_wait_timer(
                    thread_id=normalized_thread,
                    generation=entry.generation,
                    delay_seconds=delay_with_jitter,
                )
            )

        if should_acknowledge:
            await self._send_acknowledgment(
                channel=channel,
                incoming=incoming,
                channel_id=channel_id,
            )
        await self._publish_staff_assist(entry, incoming=incoming, response=None)
        return False

    async def record_staff_activity(
        self,
        *,
        room_or_conversation_id: str,
        staff_id: str,
    ) -> None:
        """Record trusted staff activity and defer pending AI sends for that room."""
        normalized_room = str(room_or_conversation_id or "").strip()
        normalized_staff = str(staff_id or "").strip()
        if not normalized_room or not normalized_staff:
            return

        self._last_staff_activity_by_room[normalized_room] = time.time()
        candidate_threads = [
            thread_id
            for thread_id, entry in self._threads.items()
            if entry.room_or_conversation_id == normalized_room
        ]
        for thread_id in candidate_threads:
            lock = self._lock_for(thread_id)
            async with lock:
                entry = self._threads.get(thread_id)
                if entry is None or entry.room_or_conversation_id != normalized_room:
                    continue
                self._cancel_task(entry.hitl_task)
                entry.hitl_task = None
                self._defer_thread_due_to_room_activity(entry)
                await self._publish_staff_assist(
                    entry,
                    incoming=entry.latest_incoming,
                    response=entry.prepared_response,
                )

    async def cancel_for_chatops_send(self, thread_id: str | tuple[str, str]) -> bool:
        """Cancel a pending arbitration timer to avoid double-send."""
        normalized = self._normalize_thread_id("", thread_id)
        lock = self._lock_for(normalized)
        async with lock:
            entry = self._threads.get(normalized)
            if entry is None:
                return False
            self._cancel_task(entry.timer_task)
            self._cancel_task(entry.hitl_task)
            entry.timer_task = None
            entry.hitl_task = None
            entry.state = "chatops_sent"
            self._clear_thread(normalized)
            return True

    async def shutdown(self, timeout_seconds: float = 10.0) -> int:
        """Cancel all pending timers and clear in-memory state."""
        pending_tasks: list[asyncio.Task[None]] = []
        for entry in list(self._threads.values()):
            if entry.timer_task is not None:
                self._cancel_task(entry.timer_task)
                pending_tasks.append(entry.timer_task)
            if entry.hitl_task is not None:
                self._cancel_task(entry.hitl_task)
                pending_tasks.append(entry.hitl_task)
        self._threads.clear()
        self._locks.clear()

        if pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=max(0.1, float(timeout_seconds)),
                )
            except Exception:
                logger.debug("Arbitration shutdown wait interrupted", exc_info=True)
        return len(pending_tasks)

    async def _run_wait_timer(
        self,
        *,
        thread_id: str,
        generation: int,
        delay_seconds: float,
    ) -> None:
        try:
            await asyncio.sleep(max(0.0, float(delay_seconds)))
            await self._on_wait_timer_elapsed(
                thread_id=thread_id, generation=generation
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._cleanup_failed_thread(
                thread_id=thread_id, generation=generation
            )
            logger.exception("Arbitration wait timer failed for thread=%s", thread_id)

    async def _on_wait_timer_elapsed(self, *, thread_id: str, generation: int) -> None:
        lock = self._lock_for(thread_id)
        async with lock:
            entry = self._threads.get(thread_id)
            if entry is None or entry.generation != generation:
                return
            if self._is_staff_recently_active(
                entry.room_or_conversation_id, entry.channel_id
            ):
                self._defer_thread_due_to_room_activity(entry)
                await self._publish_staff_assist(
                    entry,
                    incoming=entry.latest_incoming,
                    response=entry.prepared_response,
                )
                return
            entry.state = "ai_eligible"
            entry.timer_fired_at = time.time()
            merged_incoming = entry.build_incoming(self.max_accumulated_chars)
            on_release = entry.on_release
            on_dispatch = entry.on_dispatch
            channel = entry.channel
            channel_id = entry.channel_id

        if on_release is None or on_dispatch is None:
            logger.warning("Missing arbitration callbacks for thread=%s", thread_id)
            async with lock:
                self._clear_thread(thread_id)
            return

        response = await on_release(merged_incoming)
        mode = get_ai_response_mode(self.policy_service, channel_id)
        if mode == "autonomous":
            async with lock:
                entry = self._threads.get(thread_id)
                if entry is not None and entry.generation == generation:
                    if self._is_staff_recently_active(
                        entry.room_or_conversation_id,
                        entry.channel_id,
                    ):
                        self._defer_thread_due_to_room_activity(entry)
                        await self._publish_staff_assist(
                            entry,
                            incoming=merged_incoming,
                            response=response,
                        )
                        return

            dispatch_sent = await self._dispatch_with_retry(
                incoming=merged_incoming,
                response=response,
                on_dispatch=on_dispatch,
                channel=channel,
                channel_id=channel_id,
            )
            async with lock:
                entry = self._threads.get(thread_id)
                if entry is not None and entry.generation == generation:
                    entry.state = (
                        "ai_sent" if dispatch_sent else "dispatch_failed_escalated"
                    )
                    await self._publish_staff_assist(
                        entry,
                        incoming=merged_incoming,
                        response=response,
                    )
                    self._clear_thread(thread_id)
            return

        async with lock:
            entry = self._threads.get(thread_id)
            if entry is None or entry.generation != generation:
                return
            entry.prepared_response = response
            entry.state = "hitl_waiting_for_approval"
            await self._publish_staff_assist(
                entry,
                incoming=merged_incoming,
                response=response,
            )
            timeout_seconds = get_hitl_approval_timeout_seconds(
                self.policy_service,
                channel_id,
            )
            entry.hitl_task = asyncio.create_task(
                self._run_hitl_timeout(
                    thread_id=thread_id,
                    generation=generation,
                    timeout_seconds=timeout_seconds,
                    incoming=merged_incoming,
                    response=response,
                    channel=channel,
                )
            )

    def _defer_thread_due_to_room_activity(self, entry: _ThreadEntry) -> None:
        """Move an entry into deferred state and schedule cooldown recheck."""
        self._cancel_task(entry.timer_task)
        entry.timer_task = None
        entry.state = "deferred_by_room_activity"
        cooldown_seconds = get_staff_active_cooldown_seconds(
            self.policy_service,
            entry.channel_id,
        )
        entry.timer_task = asyncio.create_task(
            self._run_deferred_timer(
                thread_id=entry.thread_id,
                generation=entry.generation,
                delay_seconds=max(1.0, float(cooldown_seconds)),
            )
        )

    async def _run_deferred_timer(
        self,
        *,
        thread_id: str,
        generation: int,
        delay_seconds: float,
    ) -> None:
        try:
            await asyncio.sleep(max(0.0, float(delay_seconds)))
            await self._on_deferred_timer_elapsed(
                thread_id=thread_id, generation=generation
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._cleanup_failed_thread(
                thread_id=thread_id, generation=generation
            )
            logger.exception(
                "Arbitration deferred timer failed for thread=%s", thread_id
            )

    async def _on_deferred_timer_elapsed(
        self, *, thread_id: str, generation: int
    ) -> None:
        lock = self._lock_for(thread_id)
        async with lock:
            entry = self._threads.get(thread_id)
            if entry is None or entry.generation != generation:
                return
            if self._is_staff_recently_active(
                entry.room_or_conversation_id, entry.channel_id
            ):
                self._defer_thread_due_to_room_activity(entry)
                await self._publish_staff_assist(
                    entry,
                    incoming=entry.latest_incoming,
                    response=entry.prepared_response,
                )
                return

        await self._on_wait_timer_elapsed(thread_id=thread_id, generation=generation)

    async def _dispatch_with_retry(
        self,
        *,
        incoming: IncomingMessage,
        response: Any,
        on_dispatch: Callable[[IncomingMessage, Any], Awaitable[bool]],
        channel: Any | None,
        channel_id: str,
    ) -> bool:
        first_sent = bool(await on_dispatch(incoming, response))
        if first_sent:
            return True
        await asyncio.sleep(self.dispatch_retry_delay_seconds)
        second_sent = bool(await on_dispatch(incoming, response))
        if second_sent:
            return True
        await self._create_escalation(incoming=incoming, response=response)
        await self._send_dispatch_failure_notice(
            channel=channel,
            incoming=incoming,
            channel_id=channel_id,
        )
        return False

    async def _run_hitl_timeout(
        self,
        *,
        thread_id: str,
        generation: int,
        timeout_seconds: int,
        incoming: IncomingMessage,
        response: Any,
        channel: Any | None,
    ) -> None:
        try:
            await asyncio.sleep(max(0, int(timeout_seconds)))
            await self._on_hitl_timeout(
                thread_id=thread_id,
                generation=generation,
                incoming=incoming,
                response=response,
                channel=channel,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._cleanup_failed_thread(
                thread_id=thread_id, generation=generation
            )
            logger.exception("HITL timeout handler failed for thread=%s", thread_id)

    async def _on_hitl_timeout(
        self,
        *,
        thread_id: str,
        generation: int,
        incoming: IncomingMessage,
        response: Any,
        channel: Any | None,
    ) -> None:
        lock = self._lock_for(thread_id)
        async with lock:
            entry = self._threads.get(thread_id)
            if entry is None or entry.generation != generation:
                return
            entry.state = "hitl_timeout_escalated"

        dispatcher = ChannelResponseDispatcher(
            channel=channel,
            channel_id=str(getattr(incoming.channel, "value", incoming.channel) or ""),
            escalation_service=self.escalation_service,
        )
        escalation = await dispatcher.create_escalation_for_review(incoming, response)
        if escalation is not None:
            await dispatcher.notify_review_queued(incoming, response, escalation)
        else:
            await self._send_hitl_timeout_notice(channel=channel, incoming=incoming)

        async with lock:
            entry = self._threads.get(thread_id)
            if entry is not None and entry.generation == generation:
                await self._publish_staff_assist(
                    entry,
                    incoming=incoming,
                    response=response,
                )
                self._clear_thread(thread_id)

    async def _create_escalation(
        self,
        *,
        incoming: IncomingMessage,
        response: Any,
    ) -> Any | None:
        if self.escalation_service is None:
            return None
        dispatcher = ChannelResponseDispatcher(
            channel=None,
            channel_id=str(getattr(incoming.channel, "value", incoming.channel) or ""),
            escalation_service=self.escalation_service,
        )
        return await dispatcher.create_escalation_for_review(incoming, response)

    async def _send_hitl_timeout_notice(
        self,
        *,
        channel: Any | None,
        incoming: IncomingMessage,
    ) -> None:
        if channel is None:
            return
        get_delivery_target = getattr(channel, "get_delivery_target", None)
        send_message = getattr(channel, "send_message", None)
        if not callable(get_delivery_target) or not callable(send_message):
            return

        metadata = getattr(incoming, "channel_metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        target = str(get_delivery_target(metadata) or "").strip()
        if not target:
            return

        metadata = ResponseMetadata(
            processing_time_ms=0.0,
            rag_strategy="arbitration",
            model_name="arbitration",
            confidence_score=0.0,
            routing_action="needs_human",
            routing_reason="hitl_timeout",
            version_confidence=None,
        )
        notice = OutgoingMessage(
            message_id=f"hitl-timeout-{uuid.uuid4()}",
            in_reply_to=incoming.message_id,
            channel=incoming.channel,
            answer=get_escalation_user_notice_template(
                self.policy_service,
                str(getattr(incoming.channel, "value", incoming.channel) or ""),
            ),
            sources=[],
            user=incoming.user,
            metadata=metadata,
            original_question=incoming.question,
            requires_human=True,
        )
        try:
            result = send_message(target, notice)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "Failed sending HITL timeout notice for channel=%s message_id=%s",
                getattr(incoming.channel, "value", incoming.channel),
                incoming.message_id,
            )

    async def _send_dispatch_failure_notice(
        self,
        *,
        channel: Any | None,
        incoming: IncomingMessage,
        channel_id: str,
    ) -> None:
        if channel is None:
            return
        get_delivery_target = getattr(channel, "get_delivery_target", None)
        send_message = getattr(channel, "send_message", None)
        if not callable(get_delivery_target) or not callable(send_message):
            return

        metadata = getattr(incoming, "channel_metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        target = str(get_delivery_target(metadata) or "").strip()
        if not target:
            return
        notice = OutgoingMessage(
            message_id=f"dispatch-failure-{uuid.uuid4()}",
            in_reply_to=incoming.message_id,
            channel=incoming.channel,
            answer=get_dispatch_failure_message_template(
                self.policy_service, channel_id
            ),
            sources=[],
            user=incoming.user,
            metadata=ResponseMetadata(
                processing_time_ms=0.0,
                rag_strategy="arbitration",
                model_name="arbitration",
                confidence_score=0.0,
                routing_action="needs_human",
                routing_reason="dispatch_failure",
                version_confidence=None,
            ),
            original_question=incoming.question,
            requires_human=True,
        )
        try:
            result = send_message(target, notice)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "Failed sending dispatch failure notice for channel=%s message_id=%s",
                channel_id,
                incoming.message_id,
            )

    async def _send_acknowledgment(
        self,
        *,
        channel: Any | None,
        incoming: IncomingMessage,
        channel_id: str,
    ) -> None:
        if channel is None:
            return
        mode = get_acknowledgment_mode(self.policy_service, channel_id)
        if mode == "none":
            return

        get_delivery_target = getattr(channel, "get_delivery_target", None)
        if not callable(get_delivery_target):
            return
        metadata = getattr(incoming, "channel_metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        target = str(get_delivery_target(metadata) or "").strip()
        if not target:
            return

        if mode == "reaction":
            send_reaction = getattr(channel, "send_reaction", None)
            if callable(send_reaction):
                try:
                    sent = send_reaction(
                        target,
                        str(incoming.message_id),
                        get_acknowledgment_reaction_key(
                            self.policy_service, channel_id
                        ),
                    )
                    if inspect.isawaitable(sent):
                        sent = await sent
                    if sent:
                        return
                except Exception:
                    logger.debug(
                        "Acknowledgment reaction failed for channel=%s message_id=%s",
                        channel_id,
                        incoming.message_id,
                        exc_info=True,
                    )
            mode = "message"

        if mode != "message":
            return
        send_message = getattr(channel, "send_message", None)
        if not callable(send_message):
            return
        notice = OutgoingMessage(
            message_id=f"ack-{uuid.uuid4()}",
            in_reply_to=incoming.message_id,
            channel=incoming.channel,
            answer=get_acknowledgment_message_template(self.policy_service, channel_id),
            sources=[],
            user=incoming.user,
            metadata=ResponseMetadata(
                processing_time_ms=0.0,
                rag_strategy="arbitration",
                model_name="arbitration",
                confidence_score=0.0,
                routing_action="acknowledgment",
                routing_reason="waiting_window",
                version_confidence=None,
            ),
            original_question=incoming.question,
            requires_human=False,
        )
        try:
            result = send_message(target, notice)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.debug(
                "Acknowledgment message failed for channel=%s message_id=%s",
                channel_id,
                incoming.message_id,
                exc_info=True,
            )

    def _compute_wait_delay_seconds(
        self, *, channel_id: str, base_delay_seconds: int
    ) -> float:
        jitter_max = max(
            0, get_timer_jitter_max_seconds(self.policy_service, channel_id)
        )
        if jitter_max <= 0:
            return float(base_delay_seconds)
        jitter = random.uniform(-(jitter_max / 2.0), jitter_max / 2.0)
        return max(0.0, float(base_delay_seconds) + jitter)

    async def _publish_staff_assist(
        self,
        entry: _ThreadEntry,
        *,
        incoming: IncomingMessage,
        response: Any | None,
    ) -> None:
        if self.staff_assist_service is None:
            return
        publish = getattr(self.staff_assist_service, "publish", None)
        if not callable(publish):
            return
        case_id = f"{entry.channel_id}:{entry.thread_id}"
        result = publish(
            channel_id=entry.channel_id,
            thread_id=entry.thread_id,
            room_or_conversation_id=entry.room_or_conversation_id,
            case_id=case_id,
            state=entry.state,
            incoming=incoming,
            response=response,
        )
        if inspect.isawaitable(result):
            await result

    def _clear_thread(self, thread_id: str) -> None:
        entry = self._threads.pop(thread_id, None)
        self._locks.pop(thread_id, None)
        if entry is None:
            return
        self._cancel_task(entry.timer_task)
        self._cancel_task(entry.hitl_task)
        if self.staff_assist_service is not None:
            clear_fn = getattr(self.staff_assist_service, "clear_thread", None)
            if callable(clear_fn):
                try:
                    clear_fn(thread_id, entry.channel_id)
                except Exception:
                    logger.debug(
                        "Failed clearing staff-assist payload for thread=%s",
                        thread_id,
                        exc_info=True,
                    )

    async def _cleanup_failed_thread(self, *, thread_id: str, generation: int) -> None:
        lock = self._lock_for(thread_id)
        async with lock:
            entry = self._threads.get(thread_id)
            if entry is None or entry.generation != generation:
                return
            self._clear_thread(thread_id)

    def _is_staff_recently_active(
        self, room_or_conversation_id: str, channel_id: str
    ) -> bool:
        last = self._last_staff_activity_by_room.get(
            str(room_or_conversation_id or "").strip()
        )
        if last is None:
            return False
        cooldown = get_staff_active_cooldown_seconds(self.policy_service, channel_id)
        if cooldown <= 0:
            return False
        return (time.time() - float(last)) <= float(cooldown)

    def _lock_for(self, thread_id: str) -> asyncio.Lock:
        lock = self._locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[thread_id] = lock
        return lock

    @staticmethod
    def _cancel_task(task: asyncio.Task[None] | None) -> None:
        if task is None or task.done():
            return
        task.cancel()

    @staticmethod
    def _normalize_thread_id(channel_id: str, thread_id: str | tuple[str, str]) -> str:
        if isinstance(thread_id, tuple):
            left = str(thread_id[0] if len(thread_id) > 0 else "").strip()
            right = str(thread_id[1] if len(thread_id) > 1 else "").strip()
            if left and right:
                return f"{left}::{right}"
            return left or right or "unknown-thread"
        normalized = str(thread_id or "").strip()
        if normalized:
            return normalized
        return f"{channel_id or 'unknown'}::unknown-thread"
