"""Matrix Channel Plugin.

Wraps existing Matrix integration into channel plugin architecture.
"""

import uuid
from typing import Set

from app.channels.base import ChannelBase
from app.channels.models import (ChannelCapability, ChannelType, DocumentReference,
                                 IncomingMessage, OutgoingMessage, ResponseMetadata)


class MatrixChannel(ChannelBase):
    """Matrix protocol channel for federated chat.

    This plugin wraps the existing Matrix integration to work with
    the channel plugin architecture. The Matrix channel:
    - Maintains persistent connection to Matrix homeserver
    - Receives messages from configured rooms
    - Sends responses back to Matrix rooms

    Example:
        runtime = ChannelRuntime(settings=settings, rag_service=rag)
        channel = MatrixChannel(runtime)
        await channel.start()

        # Channel will receive messages via callbacks
        # handle_incoming is called when new messages arrive
    """

    @property
    def channel_id(self) -> str:
        """Return channel identifier."""
        return "matrix"

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        """Return supported capabilities."""
        return {
            ChannelCapability.TEXT_MESSAGES,
            ChannelCapability.CHAT_HISTORY,
            ChannelCapability.PERSISTENT_CONNECTION,
            ChannelCapability.RECEIVE_MESSAGES,
            ChannelCapability.SEND_RESPONSES,
        }

    async def start(self) -> None:
        """Start the Matrix channel.

        Connects to Matrix homeserver and starts syncing.
        """
        self._logger.info("Starting Matrix channel")

        # Delegate to connection method
        if hasattr(self, "_connect_to_homeserver"):
            await self._connect_to_homeserver()

        self._is_connected = True
        self._logger.info("Matrix channel started")

    async def stop(self) -> None:
        """Stop the Matrix channel.

        Disconnects from homeserver gracefully.
        """
        self._logger.info("Stopping Matrix channel")

        # Delegate to disconnection method
        if hasattr(self, "_disconnect_from_homeserver"):
            await self._disconnect_from_homeserver()

        self._is_connected = False
        self._logger.info("Matrix channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send response to Matrix room.

        Args:
            target: Room ID (e.g., !roomid:matrix.org).
            message: Response message to send.

        Returns:
            True on success, False on failure.
        """
        self._logger.debug(f"Sending message to Matrix room {target}")

        # Delegate to room send method
        if hasattr(self, "_send_to_room"):
            return await self._send_to_room(target, message.answer)

        # Default implementation
        return True

    async def handle_incoming(self, message: IncomingMessage) -> OutgoingMessage:
        """Handle incoming message from Matrix room.

        Delegates to RAG service and builds response.

        Args:
            message: Incoming message from Matrix.

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
            channel=ChannelType.MATRIX,
            answer=rag_response.get("answer", ""),
            sources=sources,
            user=message.user,
            metadata=metadata,
            suggested_questions=rag_response.get("suggested_questions"),
            requires_human=rag_response.get("requires_human", False),
        )

    async def join_room(self, room_id: str) -> bool:
        """Join a Matrix room.

        Args:
            room_id: Matrix room ID to join.

        Returns:
            True on success, False on failure.
        """
        self._logger.info(f"Joining Matrix room {room_id}")

        if hasattr(self, "_join_matrix_room"):
            return await self._join_matrix_room(room_id)

        return True

    async def leave_room(self, room_id: str) -> bool:
        """Leave a Matrix room.

        Args:
            room_id: Matrix room ID to leave.

        Returns:
            True on success, False on failure.
        """
        self._logger.info(f"Leaving Matrix room {room_id}")

        if hasattr(self, "_leave_matrix_room"):
            return await self._leave_matrix_room(room_id)

        return True
