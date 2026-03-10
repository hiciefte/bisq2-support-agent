"""Shared inbound message orchestration for push and polling channels."""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone
from typing import Any

from app.channels.coordination import CoordinationStore
from app.channels.events import (
    CanonicalInboundEvent,
    dedup_key,
    thread_lock_key,
    thread_state_key,
)
from app.channels.policy import (
    apply_autosend_policy,
    is_autosend_enabled,
)

logger = logging.getLogger(__name__)
_MISSING = object()


class InboundMessageOrchestrator:
    """Process inbound messages through one shared, idempotent pipeline."""

    def __init__(
        self,
        *,
        channel: Any,
        channel_id: str,
        dispatcher: Any,
        autoresponse_policy_service: Any | None = None,
        coordination_store: CoordinationStore | None = None,
        dedup_ttl_seconds: float = 3600.0,
        lock_ttl_seconds: float = 15.0,
        thread_state_ttl_seconds: float = 900.0,
    ) -> None:
        self.channel = channel
        self.channel_id = str(channel_id or getattr(channel, "channel_id", "")).strip()
        self.dispatcher = dispatcher
        self.autoresponse_policy_service = autoresponse_policy_service
        self.coordination_store = self._normalize_coordination_store(coordination_store)
        self.dedup_ttl_seconds = max(1.0, float(dedup_ttl_seconds))
        self.lock_ttl_seconds = max(0.1, float(lock_ttl_seconds))
        self.thread_state_ttl_seconds = max(1.0, float(thread_state_ttl_seconds))

    async def process_incoming(self, incoming: Any) -> bool:
        if await self._consume_feedback_followup(incoming):
            return True

        if self.channel is None:
            return False

        canonical = CanonicalInboundEvent.from_incoming(self.channel_id, incoming)

        lock_key = thread_lock_key(canonical.channel_id, canonical.thread_id)
        lock_token = await self._acquire_lock(lock_key)
        if self.coordination_store is not None and lock_token is None:
            logger.debug(
                "Skipping inbound event while thread is locked channel=%s thread=%s event=%s",
                self.channel_id,
                canonical.thread_id,
                canonical.event_id,
            )
            return False

        try:
            if not await self._reserve_dedup(canonical):
                logger.debug(
                    "Skipping duplicate inbound event channel=%s event=%s",
                    self.channel_id,
                    canonical.event_id,
                )
                return False
            arbitration = self._resolve_arbitration_service()
            if arbitration is not None:
                thread_id, room_or_conversation_id = self._derive_arbitration_keys(
                    canonical=canonical,
                    incoming=incoming,
                )

                async def _on_release(queued_incoming: Any) -> Any:
                    response = await self.channel.handle_incoming(queued_incoming)
                    autosend_enabled = is_autosend_enabled(
                        self.autoresponse_policy_service,
                        self.channel_id,
                    )
                    return apply_autosend_policy(response, autosend_enabled)

                async def _on_dispatch(queued_incoming: Any, response: Any) -> bool:
                    return bool(await self.dispatcher.dispatch(queued_incoming, response))

                enqueue_result = arbitration.enqueue(
                    incoming=incoming,
                    thread_id=thread_id,
                    room_or_conversation_id=room_or_conversation_id,
                    on_release=_on_release,
                    on_dispatch=_on_dispatch,
                    channel=self.channel,
                )
                if inspect.isawaitable(enqueue_result):
                    sent = bool(await enqueue_result)
                else:
                    sent = bool(enqueue_result)
            else:
                response = await self.channel.handle_incoming(incoming)
                autosend_enabled = is_autosend_enabled(
                    self.autoresponse_policy_service,
                    self.channel_id,
                )
                response = apply_autosend_policy(response, autosend_enabled)
                sent = bool(await self.dispatcher.dispatch(incoming, response))
            await self._update_thread_state(canonical)
            return sent
        except Exception:
            logger.exception(
                "Inbound orchestration failed for channel=%s event=%s",
                self.channel_id,
                canonical.event_id,
            )
            return False
        finally:
            await self._release_lock(lock_key, lock_token)

    async def _consume_feedback_followup(self, incoming: Any) -> bool:
        runtime = getattr(self.channel, "runtime", None)
        if runtime is None:
            return False

        resolve_optional = getattr(runtime, "resolve_optional", None)
        if not callable(resolve_optional):
            return False
        try:
            coordinator = resolve_optional("feedback_followup_coordinator")
        except Exception:
            logger.debug(
                "Failed to resolve feedback_followup_coordinator for channel=%s",
                self.channel_id,
                exc_info=True,
            )
            return False
        if coordinator is None:
            return False

        consume = getattr(coordinator, "consume_if_pending", None)
        if (
            inspect.getattr_static(coordinator, "consume_if_pending", _MISSING)
            is _MISSING
        ):
            return False
        if not callable(consume):
            return False

        try:
            result = consume(incoming=incoming, channel=self.channel)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception:
            logger.exception(
                "Failed while consuming feedback follow-up for channel=%s message_id=%s",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
            )
            return False

    async def _reserve_dedup(self, canonical: CanonicalInboundEvent) -> bool:
        if self.coordination_store is None:
            return True
        key = dedup_key(canonical.channel_id, canonical.event_id)
        result: Any = self.coordination_store.reserve_dedup(
            key,
            ttl_seconds=self.dedup_ttl_seconds,
        )
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    async def _acquire_lock(self, key: str) -> str | None:
        if self.coordination_store is None:
            return "no-lock"
        result: Any = self.coordination_store.acquire_lock(
            key,
            ttl_seconds=self.lock_ttl_seconds,
        )
        if inspect.isawaitable(result):
            result = await result
        return str(result) if result else None

    async def _release_lock(self, key: str, token: str | None) -> None:
        if self.coordination_store is None or token is None:
            return
        result = self.coordination_store.release_lock(key, token)
        if inspect.isawaitable(result):
            await result

    async def _update_thread_state(self, canonical: CanonicalInboundEvent) -> None:
        if self.coordination_store is None:
            return

        key = thread_state_key(canonical.channel_id, canonical.thread_id)
        state = {
            "last_event_id": canonical.event_id,
            "last_user_id": canonical.user_id,
            "last_processed_at": datetime.now(timezone.utc).isoformat(),
        }
        result = self.coordination_store.set_thread_state(
            key,
            state,
            ttl_seconds=self.thread_state_ttl_seconds,
        )
        if inspect.isawaitable(result):
            await result

    def _resolve_arbitration_service(self) -> Any | None:
        runtime = getattr(self.channel, "runtime", None)
        resolve_optional = getattr(runtime, "resolve_optional", None) if runtime else None
        if not callable(resolve_optional):
            return None
        try:
            arbitration = resolve_optional("arbitration_service")
        except Exception:
            logger.debug(
                "Failed resolving arbitration_service for channel=%s",
                self.channel_id,
                exc_info=True,
            )
            return None
        if arbitration is None:
            return None
        required = ("enqueue", "record_staff_activity")
        for attr in required:
            if inspect.getattr_static(arbitration, attr, _MISSING) is _MISSING:
                return None
        return arbitration

    def _derive_arbitration_keys(
        self,
        *,
        canonical: CanonicalInboundEvent,
        incoming: Any,
    ) -> tuple[str | tuple[str, str], str]:
        metadata = getattr(incoming, "channel_metadata", {}) or {}
        room_or_conversation_id = (
            str(metadata.get("room_id", "") or "").strip()
            or str(metadata.get("conversation_id", "") or "").strip()
            or str(metadata.get("channel_id", "") or "").strip()
            or canonical.thread_id
        )
        user_id = str(getattr(getattr(incoming, "user", None), "user_id", "") or "").strip()
        if room_or_conversation_id and user_id:
            return (room_or_conversation_id, user_id), room_or_conversation_id
        return canonical.thread_id, room_or_conversation_id or canonical.thread_id

    @staticmethod
    def _normalize_coordination_store(store: Any) -> CoordinationStore | None:
        if store is None:
            return None
        required = (
            "reserve_dedup",
            "acquire_lock",
            "release_lock",
            "get_thread_state",
            "set_thread_state",
        )
        for attr in required:
            if inspect.getattr_static(store, attr, _MISSING) is _MISSING:
                return None
        return store
