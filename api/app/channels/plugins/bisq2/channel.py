"""Bisq2 Channel Plugin.

Wraps existing Bisq2 API integration into channel plugin architecture.
"""

import uuid
from typing import Any, Dict, List, Optional, Set

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
    - Processes incoming questions through the RAG service

    Note: This is a polling-only channel. The Bisq2 API only supports
    exporting conversations (read-only). FAQ extraction from resolved
    conversations is handled by the training pipeline (Bisq2SyncService),
    not by this channel plugin.

    Example:
        runtime = ChannelRuntime(settings=settings, rag_service=rag)
        channel = Bisq2Channel(runtime)
        await channel.start()

        # Poll for new messages
        messages = await channel.poll_conversations()
        for message in messages:
            response = await channel.handle_incoming(message)
    """

    @property
    def channel_id(self) -> str:
        """Return channel identifier."""
        return "bisq2"

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        """Return supported capabilities.

        Note: Bisq2 API is read-only (export/polling only), so SEND_RESPONSES
        is not supported. FAQ extraction is handled by the training pipeline.
        """
        return {
            ChannelCapability.RECEIVE_MESSAGES,
            ChannelCapability.POLL_CONVERSATIONS,
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
            self._logger.error(f"Failed to connect to Bisq2 API: {e}")
            self._is_connected = False

    async def stop(self) -> None:
        """Stop the Bisq2 channel."""
        self._logger.info("Stopping Bisq2 channel")
        self._is_connected = False
        self._logger.info("Bisq2 channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send response back to Bisq2 conversation.

        Note: The Bisq2 API is read-only (export endpoint only). Sending
        responses back to Bisq2 support system is not supported. This method
        always returns False.

        Args:
            target: Conversation ID in Bisq2 system.
            message: Response message to send.

        Returns:
            False - Bisq2 API does not support sending messages.
        """
        self._logger.warning(
            f"send_message called for Bisq2 conversation {target}, "
            "but Bisq2 API does not support sending responses"
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
            result = await bisq_api.export_chat_messages()
            messages = result.get("messages", [])

            if not messages:
                return []

            # Transform to IncomingMessage format
            incoming_messages = []
            for msg in messages:
                incoming = self._transform_bisq_message(msg)
                if incoming:
                    incoming_messages.append(incoming)

            self._logger.info(
                f"Polled {len(incoming_messages)} messages from Bisq2 API"
            )
            return incoming_messages

        except Exception as e:
            self._logger.error(f"Error polling Bisq2 API: {e}")
            return []

    def _transform_bisq_message(self, msg: Dict[str, Any]) -> Optional[IncomingMessage]:
        """Transform a Bisq2 API message to IncomingMessage format.

        Args:
            msg: Raw message from Bisq2 API.

        Returns:
            IncomingMessage or None if transformation fails.
        """
        try:
            message_id = msg.get("messageId", str(uuid.uuid4()))
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
