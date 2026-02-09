"""Tests for ChannelBase handle_incoming implementation.

TDD tests for the extracted common handle_incoming logic in base class.
"""

import uuid
from typing import ClassVar, Set
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.base import ChannelBase
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    ChatMessage,
    DocumentReference,
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)

# =============================================================================
# Test Channel Implementation
# =============================================================================


class ConcreteTestChannel(ChannelBase):
    """Concrete channel for testing base class handle_incoming."""

    REQUIRED_PACKAGES: ClassVar[tuple[str, ...]] = ()

    @property
    def channel_id(self) -> str:
        return "test"

    @property
    def channel_type(self) -> ChannelType:
        """Return the channel type for OutgoingMessage."""
        return ChannelType.WEB

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        return {ChannelCapability.TEXT_MESSAGES}

    async def start(self) -> None:
        self._is_connected = True

    async def stop(self) -> None:
        self._is_connected = False

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        return True


# =============================================================================
# Tests for handle_incoming Base Implementation
# =============================================================================


class TestChannelBaseHandleIncoming:
    """Test handle_incoming default implementation in base class."""

    @pytest.fixture
    def mock_runtime(self):
        """Create mock runtime with RAG service."""
        runtime = MagicMock()
        runtime.rag_service = AsyncMock()
        runtime.rag_service.query = AsyncMock(
            return_value={
                "answer": "Test answer",
                "sources": [
                    {
                        "document_id": "doc1",
                        "title": "Test Doc",
                        "url": "https://example.com",
                        "relevance_score": 0.9,
                        "category": "general",
                    }
                ],
                "rag_strategy": "retrieval",
                "model_name": "gpt-4",
                "tokens_used": 100,
                "confidence": 0.95,
                "suggested_questions": ["Follow up?"],
                "requires_human": False,
            }
        )
        return runtime

    @pytest.fixture
    def incoming_message(self):
        """Create test incoming message."""
        return IncomingMessage(
            message_id="test-msg-1",
            channel=ChannelType.WEB,
            question="What is Bisq?",
            user=UserContext(user_id="test-user"),
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_calls_rag_service(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming delegates to RAG service."""
        channel = ConcreteTestChannel(mock_runtime)

        await channel.handle_incoming(incoming_message)

        mock_runtime.rag_service.query.assert_called_once_with(
            question="What is Bisq?",
            chat_history=None,
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_returns_outgoing_message(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming returns OutgoingMessage."""
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert isinstance(result, OutgoingMessage)
        assert result.answer == "Test answer"
        assert result.in_reply_to == "test-msg-1"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_uses_channel_type(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming uses channel's channel_type property."""
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert result.channel == ChannelType.WEB

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_builds_sources(self, mock_runtime, incoming_message):
        """handle_incoming correctly builds DocumentReference sources."""
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert len(result.sources) == 1
        source = result.sources[0]
        assert isinstance(source, DocumentReference)
        assert source.document_id == "doc1"
        assert source.title == "Test Doc"
        assert source.url == "https://example.com"
        assert source.relevance_score == 0.9
        assert source.category == "general"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_builds_metadata(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming correctly builds ResponseMetadata."""
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert isinstance(result.metadata, ResponseMetadata)
        assert result.metadata.rag_strategy == "retrieval"
        assert result.metadata.model_name == "gpt-4"
        assert result.metadata.tokens_used == 100
        assert result.metadata.confidence_score == 0.95
        assert result.metadata.processing_time_ms > 0

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_with_chat_history(self, mock_runtime):
        """handle_incoming passes chat history to RAG service."""
        channel = ConcreteTestChannel(mock_runtime)

        message = IncomingMessage(
            message_id="test-msg-2",
            channel=ChannelType.WEB,
            question="Follow up question",
            user=UserContext(user_id="test-user"),
            chat_history=[
                ChatMessage(role="user", content="First question"),
                ChatMessage(role="assistant", content="First answer"),
            ],
        )

        await channel.handle_incoming(message)

        mock_runtime.rag_service.query.assert_called_once_with(
            question="Follow up question",
            chat_history=[
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
            ],
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_passes_through_suggested_questions(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming includes suggested_questions from RAG response."""
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert result.suggested_questions == ["Follow up?"]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_passes_through_requires_human(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming includes requires_human from RAG response."""
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert result.requires_human is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_preserves_user_context(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming preserves user context in response."""
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert result.user == incoming_message.user

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_generates_message_id(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming generates unique message_id for response."""
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        # Should be a valid UUID
        uuid.UUID(result.message_id)  # Raises if invalid

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_handles_empty_sources(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming handles RAG response with no sources."""
        mock_runtime.rag_service.query.return_value = {
            "answer": "No sources found",
            "sources": [],
        }
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert result.sources == []
        assert result.answer == "No sources found"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_handle_incoming_handles_source_without_optional_fields(
        self, mock_runtime, incoming_message
    ):
        """handle_incoming handles sources with missing optional fields."""
        mock_runtime.rag_service.query.return_value = {
            "answer": "Answer",
            "sources": [
                {
                    # No document_id, url, relevance_score, category
                    "title": "Minimal Source",
                }
            ],
        }
        channel = ConcreteTestChannel(mock_runtime)

        result = await channel.handle_incoming(incoming_message)

        assert len(result.sources) == 1
        source = result.sources[0]
        assert source.title == "Minimal Source"
        # Should have defaults
        assert source.document_id is not None  # Generated UUID
        assert source.relevance_score == 0.5  # Default


class TestChannelTypeProperty:
    """Test channel_type property for different channels."""

    @pytest.mark.unit
    def test_channel_type_abstract_by_default(self):
        """Channels must implement channel_type property."""
        with pytest.raises(TypeError, match="abstract"):
            ChannelBase(runtime=MagicMock())
