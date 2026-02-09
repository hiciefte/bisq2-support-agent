"""Integration tests for Gateway routing.

Tests end-to-end message flow through the channel gateway.
"""

from typing import Optional
from unittest.mock import AsyncMock

import pytest
from app.channels.gateway import ChannelGateway
from app.channels.hooks import (
    BasePostProcessingHook,
    BasePreProcessingHook,
    HookPriority,
)
from app.channels.models import (
    ChannelType,
    ChatMessage,
    ErrorCode,
    GatewayError,
    IncomingMessage,
    OutgoingMessage,
    UserContext,
)


@pytest.fixture
def integrated_gateway(mock_rag_service):
    """Gateway with real hook execution."""
    return ChannelGateway(rag_service=mock_rag_service)


class TestEndToEndMessageFlow:
    """Test complete message flow."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_web_question_to_rag_response(
        self, integrated_gateway, mock_rag_service
    ):
        """Web chat → Gateway → RAG → Response."""
        message = IncomingMessage(
            message_id="integration-001",
            channel=ChannelType.WEB,
            question="How do I backup my wallet?",
            user=UserContext(user_id="test-user"),
        )

        result = await integrated_gateway.process_message(message)

        assert isinstance(result, OutgoingMessage)
        assert result.channel == ChannelType.WEB
        assert result.in_reply_to == message.message_id
        mock_rag_service.query.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_chat_history_passed_to_rag(
        self, integrated_gateway, mock_rag_service
    ):
        """Chat history preserved through flow."""
        message = IncomingMessage(
            message_id="integration-002",
            channel=ChannelType.WEB,
            question="What about Bisq 2?",
            user=UserContext(user_id="test-user"),
            chat_history=[
                ChatMessage(role="user", content="How do I backup?"),
                ChatMessage(role="assistant", content="You can backup by..."),
            ],
        )

        await integrated_gateway.process_message(message)

        call_args = mock_rag_service.query.call_args
        assert call_args is not None
        # Chat history should have been converted and passed
        kwargs = call_args.kwargs
        assert "chat_history" in kwargs
        assert len(kwargs["chat_history"]) == 2

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_hooks_execute_in_correct_order(
        self, integrated_gateway, sample_incoming_message
    ):
        """Pre → RAG → Post execution order."""
        execution_order = []

        class TrackingPreHook(BasePreProcessingHook):
            async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
                execution_order.append("pre")
                return None

        class TrackingPostHook(BasePostProcessingHook):
            async def execute(
                self, incoming: IncomingMessage, outgoing: OutgoingMessage
            ) -> Optional[GatewayError]:
                execution_order.append("post")
                return None

        # Capture RAG call timing
        original_query = integrated_gateway.rag_service.query

        async def tracked_query(*args, **kwargs):
            execution_order.append("rag")
            return await original_query(*args, **kwargs)

        integrated_gateway.rag_service.query = AsyncMock(side_effect=tracked_query)
        integrated_gateway.register_pre_hook(TrackingPreHook(name="tracker_pre"))
        integrated_gateway.register_post_hook(TrackingPostHook(name="tracker_post"))

        await integrated_gateway.process_message(sample_incoming_message)

        assert execution_order == ["pre", "rag", "post"]

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_error_propagation_through_gateway(
        self, integrated_gateway, mock_rag_service
    ):
        """Errors correctly propagated."""
        # Make RAG fail
        mock_rag_service.query = AsyncMock(side_effect=RuntimeError("RAG failure"))

        message = IncomingMessage(
            message_id="integration-003",
            channel=ChannelType.WEB,
            question="Test question",
            user=UserContext(user_id="test-user"),
        )

        result = await integrated_gateway.process_message(message)

        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.RAG_SERVICE_ERROR

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_pre_hook_blocking_prevents_rag_call(
        self, integrated_gateway, sample_incoming_message, mock_rag_service
    ):
        """Pre-hook blocking error prevents RAG execution."""

        class BlockingPreHook(BasePreProcessingHook):
            async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
                return GatewayError(
                    error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
                    error_message="Rate limit hit",
                )

        integrated_gateway.register_pre_hook(
            BlockingPreHook(name="blocker", priority=HookPriority.HIGH)
        )

        result = await integrated_gateway.process_message(sample_incoming_message)

        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.RATE_LIMIT_EXCEEDED
        mock_rag_service.query.assert_not_called()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_multiple_channels_same_gateway(self, integrated_gateway):
        """Gateway handles different channel types."""
        web_message = IncomingMessage(
            message_id="web-001",
            channel=ChannelType.WEB,
            question="Web question",
            user=UserContext(user_id="web-user"),
        )

        matrix_message = IncomingMessage(
            message_id="matrix-001",
            channel=ChannelType.MATRIX,
            question="Matrix question",
            user=UserContext(user_id="matrix-user"),
        )

        bisq_message = IncomingMessage(
            message_id="bisq-001",
            channel=ChannelType.BISQ2,
            question="Bisq question",
            user=UserContext(user_id="bisq-user"),
        )

        web_result = await integrated_gateway.process_message(web_message)
        matrix_result = await integrated_gateway.process_message(matrix_message)
        bisq_result = await integrated_gateway.process_message(bisq_message)

        assert isinstance(web_result, OutgoingMessage)
        assert web_result.channel == ChannelType.WEB

        assert isinstance(matrix_result, OutgoingMessage)
        assert matrix_result.channel == ChannelType.MATRIX

        assert isinstance(bisq_result, OutgoingMessage)
        assert bisq_result.channel == ChannelType.BISQ2
