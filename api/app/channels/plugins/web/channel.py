"""Web Channel Plugin.

Wraps existing web chat functionality into channel plugin architecture.
"""

import uuid
from typing import Set

from app.channels.base import ChannelBase
from app.channels.models import (ChannelCapability, ChannelType, DocumentReference,
                                 IncomingMessage, OutgoingMessage, ResponseMetadata)


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

    async def handle_incoming(self, message: IncomingMessage) -> OutgoingMessage:
        """Handle incoming message from web chat.

        Delegates to RAG service and builds response.

        Args:
            message: Incoming message from web interface.

        Returns:
            OutgoingMessage with RAG response.
        """
        import time

        start_time = time.time()

        # Build chat history for RAG service
        chat_history = None
        if message.chat_history:
            chat_history = [
                {"role": msg.role, "content": msg.content}
                for msg in message.chat_history
            ]

        # Query RAG service
        rag_response = await self.runtime.rag_service.query(
            question=message.question,
            chat_history=chat_history,
        )

        # Build sources from RAG response
        sources = []
        for source in rag_response.get("sources", []):
            sources.append(
                DocumentReference(
                    document_id=source.get("document_id", str(uuid.uuid4())),
                    title=source.get("title", "Unknown"),
                    url=source.get("url"),
                    relevance_score=source.get("relevance_score", 0.5),
                    category=source.get("category"),
                )
            )

        # Build metadata
        processing_time = (time.time() - start_time) * 1000
        metadata = ResponseMetadata(
            processing_time_ms=processing_time,
            rag_strategy=rag_response.get("rag_strategy", "retrieval"),
            model_name=rag_response.get("model_name", "unknown"),
            tokens_used=rag_response.get("tokens_used"),
            confidence_score=rag_response.get("confidence_score"),
            hooks_executed=[],
        )

        return OutgoingMessage(
            message_id=str(uuid.uuid4()),
            in_reply_to=message.message_id,
            channel=ChannelType.WEB,
            answer=rag_response.get("answer", ""),
            sources=sources,
            user=message.user,
            metadata=metadata,
            suggested_questions=rag_response.get("suggested_questions"),
            requires_human=rag_response.get("requires_human", False),
        )
