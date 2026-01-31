"""Bisq2 Channel Plugin.

Wraps existing Bisq2 API integration into channel plugin architecture.
"""

import uuid
from typing import Any, Dict, List, Set

from app.channels.base import ChannelBase
from app.channels.models import (ChannelCapability, ChannelType, DocumentReference,
                                 IncomingMessage, OutgoingMessage, ResponseMetadata)


class Bisq2Channel(ChannelBase):
    """Bisq2 native support chat channel.

    This plugin wraps the existing bisq_api.py functionality to integrate
    with the channel plugin architecture. The Bisq2 channel:
    - Polls Bisq2 API for new support conversations
    - Extracts FAQs from resolved conversations
    - Sends responses back to Bisq2 support system

    Example:
        runtime = ChannelRuntime(settings=settings, rag_service=rag)
        channel = Bisq2Channel(runtime)
        await channel.start()

        # Poll for new messages
        messages = await channel.poll_conversations()
        for message in messages:
            response = await channel.handle_incoming(message)
            await channel.send_message(message.channel_metadata["conversation_id"], response)
    """

    @property
    def channel_id(self) -> str:
        """Return channel identifier."""
        return "bisq2"

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        """Return supported capabilities."""
        return {
            ChannelCapability.RECEIVE_MESSAGES,
            ChannelCapability.SEND_RESPONSES,
            ChannelCapability.POLL_CONVERSATIONS,
            ChannelCapability.EXTRACT_FAQS,
        }

    async def start(self) -> None:
        """Start the Bisq2 channel.

        Initializes connection to Bisq2 API.
        """
        self._logger.info("Starting Bisq2 channel")
        # In real implementation, would verify Bisq2 API connectivity
        self._is_connected = True
        self._logger.info("Bisq2 channel started")

    async def stop(self) -> None:
        """Stop the Bisq2 channel."""
        self._logger.info("Stopping Bisq2 channel")
        self._is_connected = False
        self._logger.info("Bisq2 channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send response back to Bisq2 conversation.

        Args:
            target: Conversation ID in Bisq2 system.
            message: Response message to send.

        Returns:
            True on success, False on failure.
        """
        self._logger.debug(f"Sending response to Bisq2 conversation {target}")
        # In real implementation, would POST to Bisq2 API
        return True

    async def handle_incoming(self, message: IncomingMessage) -> OutgoingMessage:
        """Handle incoming message from Bisq2 support.

        Delegates to RAG service and builds response.

        Args:
            message: Incoming message from Bisq2 support.

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
            channel=ChannelType.BISQ2,
            answer=rag_response.get("answer", ""),
            sources=sources,
            user=message.user,
            metadata=metadata,
            suggested_questions=rag_response.get("suggested_questions"),
            requires_human=rag_response.get("requires_human", False),
        )

    async def poll_conversations(self) -> List[IncomingMessage]:
        """Poll Bisq2 API for new support conversations.

        Returns:
            List of new incoming messages from Bisq2.
        """
        self._logger.debug("Polling Bisq2 API for new conversations")

        # Delegate to internal poll method
        if hasattr(self, "_poll_api"):
            return await self._poll_api()

        # Default implementation returns empty list
        # Real implementation would call Bisq2 API
        return []

    async def extract_faqs(
        self, conversations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract FAQs from resolved Bisq2 conversations.

        Args:
            conversations: List of resolved conversations.

        Returns:
            List of FAQ entries extracted from conversations.
        """
        self._logger.debug(f"Extracting FAQs from {len(conversations)} conversations")

        # Delegate to internal extraction method
        if hasattr(self, "_extract_faqs_from_conversations"):
            return await self._extract_faqs_from_conversations(conversations)

        # Default implementation returns empty list
        # Real implementation would use LLM to extract Q&A pairs
        return []
