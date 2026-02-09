"""Web Channel Plugin.

Wraps existing web chat functionality into channel plugin architecture.
"""

from typing import Set

from app.channels.base import ChannelBase
from app.channels.models import ChannelCapability, ChannelType, OutgoingMessage


class WebChannel(ChannelBase):
    """Web channel for browser-based chat interface.

    This plugin wraps the existing chat.py functionality to integrate
    with the channel plugin architecture. The web channel:
    - Receives messages via HTTP API
    - Delegates to RAG service for responses
    - Returns responses synchronously (no push needed)

    Example:
        runtime = ChannelRuntime(settings=settings, rag_service=rag)
        channel = WebChannel(runtime)
        await channel.start()

        response = await channel.handle_incoming(message)
    """

    @property
    def channel_id(self) -> str:
        """Return channel identifier."""
        return "web"

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        """Return supported capabilities."""
        return {
            ChannelCapability.TEXT_MESSAGES,
            ChannelCapability.CHAT_HISTORY,
        }

    @property
    def channel_type(self) -> ChannelType:
        """Return channel type for outgoing messages."""
        return ChannelType.WEB

    async def start(self) -> None:
        """Start the web channel.

        Web channel doesn't need active connections - it's request/response.
        """
        self._logger.info("Starting web channel")
        self._is_connected = True
        self._logger.info("Web channel started")

    async def stop(self) -> None:
        """Stop the web channel."""
        self._logger.info("Stopping web channel")
        self._is_connected = False
        self._logger.info("Web channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send message to target.

        For web channel, messages are returned synchronously via HTTP response,
        so this is essentially a no-op. The actual sending happens in the
        HTTP response flow.

        Args:
            target: Target identifier (unused for web).
            message: Message to send.

        Returns:
            True (web always "succeeds" as sending is via HTTP response).
        """
        # Web channel doesn't push - responses are returned via HTTP
        self._logger.debug(f"Web channel send_message called for {target}")
        return True

    # handle_incoming() inherited from ChannelBase
