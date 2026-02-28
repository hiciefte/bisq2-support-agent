"""Web Channel Plugin.

Wraps existing web chat functionality into channel plugin architecture.
"""

from typing import Any, Set

from app.channels.base import ChannelBase
from app.channels.escalation_localization import render_escalation_notice
from app.channels.models import ChannelCapability, ChannelType, OutgoingMessage
from app.channels.registry import register_channel


@register_channel("web")
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

    def get_delivery_target(self, metadata: dict[str, Any]) -> str:
        """Web has no push delivery — responses are polled from DB."""
        return ""

    def format_escalation_message(
        self,
        username: str,
        escalation_id: int,
        support_handle: str,
        language_code: str | None = None,
    ) -> str:
        """Format escalation message for web chat UI."""
        return render_escalation_notice(
            channel_id=self.channel_id,
            escalation_id=escalation_id,
            support_handle=support_handle,
            language_code=language_code,
        )

    # handle_incoming() inherited from ChannelBase
    ENABLED_FLAG = "WEB_CHANNEL_ENABLED"
    ENABLED_DEFAULT = True
