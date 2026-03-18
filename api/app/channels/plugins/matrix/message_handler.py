"""Matrix push message listener using nio callbacks + sync loop."""

from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from app.channels.inbound_orchestrator import InboundMessageOrchestrator
from app.channels.models import ChannelType, IncomingMessage, UserContext
from app.channels.plugins.matrix.room_filter import normalize_room_ids
from app.channels.policy import is_generation_enabled
from app.channels.response_dispatcher import ChannelResponseDispatcher


class _MissingNioEvent:
    """Sentinel event type used when nio is not installed."""


RoomMessageTextType: Any = _MissingNioEvent
MegolmEventType: Any = _MissingNioEvent

try:
    from nio import MegolmEvent as _NioMegolmEvent
    from nio import RoomMessageText as _NioRoomMessageText
except ImportError:  # pragma: no cover - exercised in environments without nio
    pass
else:
    RoomMessageTextType = _NioRoomMessageText
    MegolmEventType = _NioMegolmEvent

# Backward-compatible exported symbols used by tests and callers.
RoomMessageText = RoomMessageTextType
MegolmEvent = MegolmEventType


logger = logging.getLogger(__name__)
_MISSING = object()


class MatrixMessageHandler:
    """Listen for Matrix room messages via event callbacks."""

    def __init__(
        self,
        client: Any,
        connection_manager: Any,
        channel: Any | None = None,
        autoresponse_policy_service: Any | None = None,
        allowed_room_ids: Any | None = None,
        staff_command_room_ids: Any | None = None,
        channel_id: str = "matrix",
        sync_timeout_ms: int = 30000,
        trust_monitor_service: Any | None = None,
    ) -> None:
        self.client = client
        self.connection_manager = connection_manager
        self.channel = channel
        self.autoresponse_policy_service = autoresponse_policy_service
        self.channel_id = str(channel_id or "matrix").strip().lower() or "matrix"
        self.allowed_room_ids = normalize_room_ids(allowed_room_ids)
        if staff_command_room_ids is None:
            self.staff_command_room_ids = self.allowed_room_ids
        else:
            self.staff_command_room_ids = normalize_room_ids(staff_command_room_ids)
        self.sync_timeout_ms = sync_timeout_ms
        self._sync_task: asyncio.Task[Any] | None = None
        self.trust_monitor_service = trust_monitor_service
        self._callback_registered = False
        self._dispatcher: ChannelResponseDispatcher | None = None
        self._orchestrator: InboundMessageOrchestrator | None = None

    async def start(self) -> None:
        """Register message callback and start sync loop."""
        if not self._callback_registered:
            self.client.add_event_callback(self._on_message, RoomMessageText)
            if MegolmEvent is not RoomMessageText:
                self.client.add_event_callback(self._on_message, MegolmEvent)
            self._callback_registered = True

        if self._sync_task is None or self._sync_task.done():
            self._sync_task = asyncio.create_task(
                self.connection_manager.sync_forever(timeout=self.sync_timeout_ms)
            )
        logger.info("Matrix message handler started")

    async def stop(self) -> None:
        """Stop sync loop and remove callback."""
        if hasattr(self.connection_manager, "stop_sync"):
            self.connection_manager.stop_sync()

        if self._sync_task is not None:
            self._sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._sync_task
            self._sync_task = None

        if self._callback_registered and hasattr(self.client, "remove_event_callback"):
            self.client.remove_event_callback(self._on_message)
            self._callback_registered = False
        logger.info("Matrix message handler stopped")

    async def _on_message(self, room: Any, event: Any) -> None:
        """Process Matrix message events through the standard channel pipeline."""
        channel = self.channel
        if channel is None:
            logger.debug("Skipping Matrix message because channel is not attached")
            return

        room_id = str(getattr(room, "room_id", "") or "").strip()
        allowed_staff_rooms = self.staff_command_room_ids
        if not room_id or (
            room_id not in self.allowed_room_ids and room_id not in allowed_staff_rooms
        ):
            logger.debug(
                "Ignoring Matrix message from unsupported room room_id=%s",
                room_id or "<empty>",
            )
            return

        effective_event = await self._resolve_event(event)
        if effective_event is None:
            return

        incoming = self._to_incoming_message(room, effective_event)
        if incoming is None:
            return

        sender_id = str(
            getattr(getattr(incoming, "user", None), "user_id", "") or ""
        ).strip()
        if self._is_self_sender(sender_id):
            return
        await self._record_trust_event(
            room_id=room_id, event=effective_event, sender_id=sender_id, room=room
        )
        if not is_generation_enabled(self.autoresponse_policy_service, self.channel_id):
            return
        if self._is_staff_sender(room=room, event=effective_event, sender_id=sender_id):
            await self._record_staff_activity(room_id=room_id, staff_id=sender_id)
            await self._maybe_handle_staff_command(
                room_id=room_id,
                event=effective_event,
                sender_id=sender_id,
            )
            return
        if room_id not in self.allowed_room_ids:
            return

        orchestrator = self._get_orchestrator()
        if orchestrator is None:
            return

        await orchestrator.process_incoming(incoming)

    async def _resolve_event(self, event: Any) -> Any | None:
        if not self._is_encrypted_event(event):
            return event

        decrypt_event = getattr(self.client, "decrypt_event", None)
        if not callable(decrypt_event):
            logger.debug(
                "Skipping Matrix encrypted event because decrypt_event is unavailable"
            )
            return None

        try:
            decrypted = decrypt_event(event)
        except Exception:
            logger.debug(
                "Failed to decrypt Matrix event_id=%s",
                getattr(event, "event_id", "<unknown>"),
                exc_info=True,
            )
            await self._request_room_key(event)
            return None

        if decrypted is None:
            logger.debug(
                "Skipping Matrix encrypted event because decryption returned no payload"
            )
            await self._request_room_key(event)
            return None

        return decrypted

    async def _request_room_key(self, event: Any) -> None:
        request_room_key = getattr(self.client, "request_room_key", None)
        if not callable(request_room_key):
            return

        try:
            await request_room_key(event)
        except Exception:
            logger.debug(
                "Failed requesting Matrix room key for event_id=%s",
                getattr(event, "event_id", "<unknown>"),
                exc_info=True,
            )

    @staticmethod
    def _is_encrypted_event(event: Any) -> bool:
        if isinstance(event, MegolmEvent):
            return True
        return event.__class__.__name__ == "MegolmEvent"

    def _get_dispatcher(self) -> ChannelResponseDispatcher | None:
        if self.channel is None:
            return None
        if self._dispatcher is None or self._dispatcher.channel is not self.channel:
            self._dispatcher = ChannelResponseDispatcher(
                channel=self.channel,
                channel_id=self.channel_id,
            )
        return self._dispatcher

    def _get_orchestrator(self) -> InboundMessageOrchestrator | None:
        channel = self.channel
        dispatcher = self._get_dispatcher()
        if channel is None or dispatcher is None:
            return None
        if self._orchestrator is None or self._orchestrator.channel is not channel:
            self._orchestrator = InboundMessageOrchestrator(
                channel=channel,
                channel_id=self.channel_id,
                dispatcher=dispatcher,
                autoresponse_policy_service=self.autoresponse_policy_service,
                coordination_store=self._resolve_coordination_store(channel),
            )
        return self._orchestrator

    @staticmethod
    def _resolve_coordination_store(channel: Any) -> Any | None:
        runtime = getattr(channel, "runtime", None)
        if runtime is None:
            return None
        resolve_optional = getattr(runtime, "resolve_optional", None)
        if not callable(resolve_optional):
            return None
        try:
            candidate = resolve_optional("channel_coordination_store")
        except Exception:
            logger.debug(
                "Failed to resolve channel_coordination_store from runtime",
                exc_info=True,
            )
            return None
        if candidate is None:
            return None
        required = (
            "reserve_dedup",
            "acquire_lock",
            "release_lock",
            "get_thread_state",
            "set_thread_state",
        )
        for attr in required:
            if inspect.getattr_static(candidate, attr, _MISSING) is _MISSING:
                return None
        return candidate

    def _is_self_sender(self, sender_id: str) -> bool:
        normalized = str(sender_id or "").strip()
        if not normalized:
            return True

        own_user_id = str(getattr(self.client, "user_id", "") or "").strip()
        return bool(own_user_id and normalized == own_user_id)

    def _is_staff_sender(self, *, room: Any, event: Any, sender_id: str) -> bool:
        channel = self.channel
        runtime = getattr(channel, "runtime", None) if channel is not None else None
        resolver = self._resolve_staff_resolver(runtime)
        if resolver is None:
            return False

        is_staff = getattr(resolver, "is_staff", None)
        if not callable(is_staff):
            return False

        candidates: list[str] = []
        for raw in (
            sender_id,
            getattr(event, "sender", None),
            self._resolve_sender_display_name(room=room, sender_id=sender_id),
        ):
            normalized = str(raw or "").strip()
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        try:
            return any(bool(is_staff(candidate)) for candidate in candidates)
        except Exception:
            logger.debug(
                "Failed staff sender check for Matrix sender=%s",
                sender_id,
                exc_info=True,
            )
            return False

    def _resolve_staff_resolver(self, runtime: Any) -> Any | None:
        if runtime is None:
            return None
        resolve_optional = getattr(runtime, "resolve_optional", None)
        if not callable(resolve_optional):
            return None
        try:
            return resolve_optional("staff_resolver")
        except Exception:
            logger.debug("Failed resolving Matrix staff_resolver", exc_info=True)
            return None

    @staticmethod
    def _resolve_sender_display_name(*, room: Any, sender_id: str) -> str:
        room_resolver = getattr(room, "user_name", None)
        if not callable(room_resolver):
            return ""
        try:
            resolved = room_resolver(sender_id)
        except Exception:
            return ""
        return resolved if isinstance(resolved, str) else ""

    async def _record_trust_event(
        self, *, room_id: str, event: Any, sender_id: str, room: Any
    ) -> None:
        service = self.trust_monitor_service
        if service is None:
            channel = self.channel
            runtime = getattr(channel, "runtime", None) if channel is not None else None
            resolve_optional = (
                getattr(runtime, "resolve_optional", None) if runtime else None
            )
            if callable(resolve_optional):
                try:
                    service = resolve_optional("trust_monitor_service")
                except Exception:
                    logger.debug(
                        "Failed resolving trust_monitor_service for room_id=%s",
                        room_id,
                        exc_info=True,
                    )
                    return
        if service is None:
            return
        try:
            from app.channels.trust_monitor.events import TrustEvent
            from app.channels.trust_monitor.models import TrustEventType

            reply_to_event_id = self._extract_reply_to_event_id(event)
            event_type = (
                TrustEventType.MESSAGE_REPLIED
                if reply_to_event_id
                else TrustEventType.MESSAGE_SENT
            )
            timestamp_ms = getattr(event, "server_timestamp", None) or 0
            occurred_at = (
                datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                if timestamp_ms
                else datetime.now(timezone.utc)
            )
            service.ingest_event(
                TrustEvent(
                    channel_id=self.channel_id,
                    space_id=room_id,
                    actor_id=sender_id,
                    actor_display_name=self._resolve_sender_display_name(
                        room=room,
                        sender_id=sender_id,
                    ),
                    event_type=event_type,
                    occurred_at=occurred_at,
                    external_event_id=str(getattr(event, "event_id", "") or ""),
                    target_message_id=reply_to_event_id
                    or str(getattr(event, "event_id", "") or ""),
                    metadata={"body_length": len(self._extract_event_text(event))},
                )
            )
        except Exception:
            logger.debug(
                "Failed recording Matrix trust-monitor event room_id=%s sender_id=%s",
                room_id,
                sender_id,
                exc_info=True,
            )

    async def _record_staff_activity(self, *, room_id: str, staff_id: str) -> None:
        channel = self.channel
        runtime = getattr(channel, "runtime", None) if channel is not None else None
        resolve_optional = (
            getattr(runtime, "resolve_optional", None) if runtime else None
        )
        if not callable(resolve_optional):
            return
        arbitration = resolve_optional("arbitration_service")
        if arbitration is None:
            return
        record_staff_activity = getattr(arbitration, "record_staff_activity", None)
        if not callable(record_staff_activity):
            return
        try:
            maybe_result = record_staff_activity(
                room_or_conversation_id=room_id,
                staff_id=staff_id,
            )
            if inspect.isawaitable(maybe_result):
                await maybe_result
        except Exception:
            logger.debug(
                "Failed recording Matrix staff activity room_id=%s staff_id=%s",
                room_id,
                staff_id,
                exc_info=True,
            )

    async def _maybe_handle_staff_command(
        self,
        *,
        room_id: str,
        event: Any,
        sender_id: str,
    ) -> bool:
        if room_id not in self.staff_command_room_ids:
            return False
        runtime = (
            getattr(self.channel, "runtime", None) if self.channel is not None else None
        )
        resolve_optional = (
            getattr(runtime, "resolve_optional", None) if runtime else None
        )
        if not callable(resolve_optional):
            return False
        command_handler = resolve_optional("matrix_reaction_handler")
        handle_staff_command = (
            getattr(command_handler, "handle_staff_command", None)
            if command_handler is not None
            else None
        )
        if not callable(handle_staff_command):
            return False
        reply_to_event_id = self._extract_reply_to_event_id(event)
        command_text = self._extract_event_text(event)
        try:
            return bool(
                await handle_staff_command(
                    room_id=room_id,
                    reply_to_event_id=reply_to_event_id,
                    command_text=command_text,
                    sender=sender_id,
                )
            )
        except Exception:
            logger.debug(
                "Failed processing Matrix staff command room_id=%s sender=%s",
                room_id,
                sender_id,
                exc_info=True,
            )
            return False

    @staticmethod
    def _extract_reply_to_event_id(event: Any) -> str:
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return ""
        content = source.get("content")
        if not isinstance(content, dict):
            return ""
        relates_to = content.get("m.relates_to")
        if not isinstance(relates_to, dict):
            return ""
        in_reply_to = relates_to.get("m.in_reply_to")
        if isinstance(in_reply_to, dict):
            event_id = str(in_reply_to.get("event_id", "") or "").strip()
            if event_id:
                return event_id
        event_id = str(relates_to.get("event_id", "") or "").strip()
        return event_id

    @staticmethod
    def _extract_event_text(event: Any) -> str:
        body = getattr(event, "body", "")
        if isinstance(body, str):
            return body
        source = getattr(event, "source", None)
        if isinstance(source, dict):
            content = source.get("content")
            if isinstance(content, dict):
                text = content.get("body", "")
                if isinstance(text, str):
                    return text
        return ""

    def _to_incoming_message(self, room: Any, event: Any) -> IncomingMessage | None:
        room_id = getattr(room, "room_id", "")
        sender = getattr(event, "sender", "")
        message_id = getattr(event, "event_id", "")
        text = self._extract_event_text(event).strip()

        if not isinstance(room_id, str) or not room_id.strip():
            return None
        if not isinstance(sender, str) or not sender.strip():
            return None
        if not isinstance(message_id, str) or not message_id.strip():
            return None
        if not text:
            return None

        return IncomingMessage(
            message_id=message_id.strip(),
            channel=ChannelType.MATRIX,
            question=text,
            user=UserContext(
                user_id=sender.strip(),
                session_id=None,
                channel_user_id=sender.strip(),
                auth_token=None,
            ),
            channel_metadata={"room_id": room_id.strip()},
            channel_signature=None,
        )
