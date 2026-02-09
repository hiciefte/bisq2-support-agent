"""Bisq2 Channel Plugin.

Wraps existing Bisq2 API integration into channel plugin architecture.
"""

import hashlib
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Set

from app.channels.base import ChannelBase
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    UserContext,
)


class Bisq2Channel(ChannelBase):
    """Bisq2 native support chat channel.

    This plugin wraps the existing bisq_api.py functionality to integrate
    with the channel plugin architecture. The Bisq2 channel:
    - Polls Bisq2 API for new support conversations
    - Sends responses via REST API
    - Receives reactions via WebSocket subscription
    - Processes incoming questions through the RAG service

    Example:
        runtime = ChannelRuntime(settings=settings, rag_service=rag)
        channel = Bisq2Channel(runtime)
        await channel.start()

        # Poll for new messages
        messages = await channel.poll_conversations()
        for message in messages:
            response = await channel.handle_incoming(message)
    """

    _last_poll_since: Optional[datetime]
    _seen_message_ids: set[str]
    _seen_message_order: Deque[str]
    _max_seen_message_ids: int

    @property
    def channel_id(self) -> str:
        """Return channel identifier."""
        return "bisq2"

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        """Return supported capabilities."""
        return {
            ChannelCapability.RECEIVE_MESSAGES,
            ChannelCapability.POLL_CONVERSATIONS,
            ChannelCapability.SEND_RESPONSES,
            ChannelCapability.REACTIONS,
        }

    @property
    def channel_type(self) -> ChannelType:
        """Return channel type for outgoing messages."""
        return ChannelType.BISQ2

    async def start(self) -> None:
        """Start the Bisq2 channel.

        Verifies connectivity to Bisq2 API. If Bisq2API is not registered
        in the runtime, the channel will start in degraded mode (polling
        will return empty results).
        """
        self._logger.info("Starting Bisq2 channel")

        # Verify Bisq2API is available in runtime
        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if not bisq_api:
            self._logger.warning(
                "Bisq2API not registered in runtime. "
                "Channel will start but polling will be unavailable."
            )
            self._is_connected = False
            return

        # Verify API connectivity by attempting to setup the session
        try:
            await bisq_api.setup()
            self._is_connected = True
            self._logger.info("Bisq2 channel started - API connection verified")
        except Exception as e:
            self._logger.exception(f"Failed to connect to Bisq2 API: {e}")
            self._is_connected = False

        # Wire reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("bisq2_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.start_listening()
                self._logger.info("Bisq2 reaction handler started")
            except Exception:
                self._logger.exception("Failed to start Bisq2 reaction handler")

    async def stop(self) -> None:
        """Stop the Bisq2 channel."""
        self._logger.info("Stopping Bisq2 channel")

        # Stop reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("bisq2_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.stop_listening()
                self._logger.info("Bisq2 reaction handler stopped")
            except Exception:
                self._logger.debug(
                    "Error stopping Bisq2 reaction handler", exc_info=True
                )

        self._is_connected = False
        self._logger.info("Bisq2 channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send response back to Bisq2 conversation via REST API.

        Args:
            target: Conversation ID in Bisq2 system.
            message: Response message to send.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if not bisq_api:
            self._logger.warning(
                "Bisq2API not registered in runtime, cannot send message"
            )
            return False

        try:
            citation = getattr(message, "original_question", None)
            response = await bisq_api.send_support_message(
                channel_id=target,
                text=message.answer,
                citation=citation,
            )

            external_message_id = response.get("messageId")
            if not external_message_id:
                self._logger.warning(
                    "Bisq2 API send_support_message returned no messageId"
                )
                return False

            # Track sent message for reaction correlation
            tracker = self.runtime.resolve_optional("sent_message_tracker")
            if tracker:
                tracker.track(
                    channel_id="bisq2",
                    external_message_id=external_message_id,
                    internal_message_id=getattr(message, "message_id", ""),
                    question=getattr(message, "original_question", "") or "",
                    answer=message.answer,
                    user_id=getattr(getattr(message, "user", None), "user_id", ""),
                    sources=[],
                )

            self._logger.info(
                "Sent message to Bisq2 conversation %s (messageId=%s)",
                target,
                external_message_id,
            )
            return True

        except Exception:
            self._logger.exception(
                "Failed to send message to Bisq2 conversation %s", target
            )
            return False

    # handle_incoming() inherited from ChannelBase

    async def poll_conversations(self) -> List[IncomingMessage]:
        """Poll Bisq2 API for new support conversations.

        Delegates to Bisq2API.export_chat_messages() to fetch new conversations,
        then transforms them into IncomingMessage format.

        Returns:
            List of new incoming messages from Bisq2.
        """
        self._logger.debug("Polling Bisq2 API for new conversations")

        # Get Bisq2API from runtime services
        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if not bisq_api:
            self._logger.warning("Bisq2API not registered in runtime, cannot poll")
            return []

        try:
            # Export messages from Bisq2 API
            result = await bisq_api.export_chat_messages(since=self._last_poll_since)
            if "messages" not in result:
                self._logger.warning(
                    "Bisq2 API export response missing 'messages'; skipping poll cycle"
                )
                return []
            messages = result.get("messages", [])

            export_timestamp = self._extract_export_timestamp(result)
            if export_timestamp is None:
                export_timestamp = datetime.now(timezone.utc)

            if not messages:
                self._last_poll_since = export_timestamp
                return []

            # Filter already processed messages to avoid duplicates on polling.
            new_messages = []
            for msg in messages:
                message_id = self._derive_message_id(msg)
                if message_id in self._seen_message_ids:
                    continue
                msg_with_id = dict(msg)
                msg_with_id["messageId"] = message_id
                new_messages.append(msg_with_id)

            # Transform to IncomingMessage format
            incoming_messages = []
            for msg in new_messages:
                incoming = self._transform_bisq_message(msg)
                if incoming:
                    incoming_messages.append(incoming)
                    self._mark_seen(incoming.message_id)

            self._logger.info(
                f"Polled {len(incoming_messages)} messages from Bisq2 API"
            )
            self._last_poll_since = export_timestamp
            return incoming_messages

        except Exception:
            self._logger.exception("Error polling Bisq2 API")
            return []

    def _transform_bisq_message(self, msg: Dict[str, Any]) -> Optional[IncomingMessage]:
        """Transform a Bisq2 API message to IncomingMessage format.

        Args:
            msg: Raw message from Bisq2 API.

        Returns:
            IncomingMessage or None if transformation fails.
        """
        try:
            message_id = str(msg.get("messageId", "")).strip()
            if not message_id:
                message_id = self._derive_message_id(msg)
            author = msg.get("author", "unknown")
            text = msg.get("message", "")

            if not text:
                return None

            return IncomingMessage(
                message_id=message_id,
                channel=ChannelType.BISQ2,
                question=text,
                user=UserContext(
                    user_id=author,
                    session_id=None,
                    channel_user_id=author,
                    auth_token=None,
                ),
                channel_metadata={
                    "conversation_id": msg.get("conversationId", ""),
                    "date": msg.get("date", ""),
                    "citation": str(msg.get("citation")) if msg.get("citation") else "",
                },
                channel_signature=None,
            )
        except Exception as e:
            self._logger.warning(f"Failed to transform Bisq2 message: {e}")
            return None

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._last_poll_since = None
        self._seen_message_ids = set()
        self._seen_message_order = deque()
        self._max_seen_message_ids = 10000

    def _derive_message_id(self, msg: Dict[str, Any]) -> str:
        """Derive a stable message ID when API messageId is missing."""
        message_id = str(msg.get("messageId", "")).strip()
        if message_id:
            return message_id

        stable_payload = {
            "conversationId": msg.get("conversationId", ""),
            "author": msg.get("author", ""),
            "message": msg.get("message", ""),
            "date": msg.get("date", ""),
        }
        payload = json.dumps(stable_payload, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"derived-{digest}"

    def _mark_seen(self, message_id: str) -> None:
        """Track seen message IDs with bounded memory usage."""
        if message_id in self._seen_message_ids:
            return

        self._seen_message_ids.add(message_id)
        self._seen_message_order.append(message_id)

        while len(self._seen_message_order) > self._max_seen_message_ids:
            oldest = self._seen_message_order.popleft()
            self._seen_message_ids.discard(oldest)

    def _extract_export_timestamp(self, result: Dict[str, Any]) -> Optional[datetime]:
        """Extract export timestamp from Bisq API payload."""
        export_date = result.get("exportDate")
        if not isinstance(export_date, str) or not export_date.strip():
            return None

        try:
            parsed = datetime.fromisoformat(export_date.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
