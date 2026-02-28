"""Matrix push message listener using nio callbacks + sync loop."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from app.channels.models import ChannelType, IncomingMessage, UserContext
from app.channels.plugins.matrix.room_filter import normalize_room_ids
from app.channels.policy import (
    apply_autosend_policy,
    is_autosend_enabled,
    is_generation_enabled,
)
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


class MatrixMessageHandler:
    """Listen for Matrix room messages via event callbacks."""

    def __init__(
        self,
        client: Any,
        connection_manager: Any,
        channel: Any | None = None,
        autoresponse_policy_service: Any | None = None,
        allowed_room_ids: Any | None = None,
        channel_id: str = "matrix",
        sync_timeout_ms: int = 30000,
    ) -> None:
        self.client = client
        self.connection_manager = connection_manager
        self.channel = channel
        self.autoresponse_policy_service = autoresponse_policy_service
        self.channel_id = str(channel_id or "matrix").strip().lower() or "matrix"
        self.allowed_room_ids = normalize_room_ids(allowed_room_ids)
        self.sync_timeout_ms = sync_timeout_ms
        self._sync_task: asyncio.Task[Any] | None = None
        self._callback_registered = False
        self._dispatcher: ChannelResponseDispatcher | None = None

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
        if not is_generation_enabled(self.autoresponse_policy_service, self.channel_id):
            return

        channel = self.channel
        if channel is None:
            logger.debug("Skipping Matrix message because channel is not attached")
            return

        room_id = str(getattr(room, "room_id", "") or "").strip()
        if not room_id or room_id not in self.allowed_room_ids:
            logger.debug(
                "Ignoring Matrix message from non-sync room room_id=%s",
                room_id or "<empty>",
            )
            return

        effective_event = await self._resolve_event(event)
        if effective_event is None:
            return

        incoming = self._to_incoming_message(room, effective_event)
        if incoming is None:
            return

        if self._should_ignore_sender(incoming.user.user_id):
            return

        if await self._consume_feedback_followup(incoming):
            return

        response = await channel.handle_incoming(incoming)
        response = apply_autosend_policy(
            response=response,
            autosend_enabled=is_autosend_enabled(
                self.autoresponse_policy_service,
                self.channel_id,
            ),
        )
        dispatcher = self._get_dispatcher()
        if dispatcher is None:
            logger.debug("Dispatcher unavailable for Matrix message handling")
            return

        await dispatcher.dispatch(incoming, response)

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

    async def _consume_feedback_followup(self, incoming: IncomingMessage) -> bool:
        channel = self.channel
        if channel is None:
            return False
        runtime = getattr(channel, "runtime", None)
        if runtime is None:
            return False
        coordinator = runtime.resolve_optional("feedback_followup_coordinator")
        if coordinator is None:
            return False
        consume = getattr(coordinator, "consume_if_pending", None)
        if not callable(consume):
            return False

        try:
            return bool(await consume(incoming=incoming, channel=channel))
        except Exception:
            logger.exception(
                "Failed consuming Matrix feedback follow-up for event=%s",
                incoming.message_id,
            )
            return False

    def _should_ignore_sender(self, sender_id: str) -> bool:
        normalized = str(sender_id or "").strip()
        if not normalized:
            return True

        own_user_id = str(getattr(self.client, "user_id", "") or "").strip()
        if own_user_id and normalized == own_user_id:
            return True

        channel = self.channel
        runtime = getattr(channel, "runtime", None) if channel is not None else None
        resolver = (
            runtime.resolve_optional("staff_resolver") if runtime is not None else None
        )
        if resolver is None:
            return False

        is_staff = getattr(resolver, "is_staff", None)
        if not callable(is_staff):
            return False

        try:
            return bool(is_staff(normalized))
        except Exception:
            logger.debug(
                "Failed staff sender check for Matrix sender=%s",
                normalized,
                exc_info=True,
            )
            return False

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
