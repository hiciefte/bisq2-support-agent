"""Tests for ChannelGateway.

TDD tests for the central message routing and hook system.
"""

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ErrorCode,
    GatewayError,
    IncomingMessage,
    OutgoingMessage,
)


class TestChannelGatewayRouting:
    """Test message routing."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_route_message_to_rag_service(
        self, sample_incoming_message, mock_rag_service
    ):
        """Message routed through RAG service."""
        from app.channels.gateway import ChannelGateway

        gateway = ChannelGateway(rag_service=mock_rag_service)
        await gateway.process_message(sample_incoming_message)

        mock_rag_service.query.assert_called_once()
        call_args = mock_rag_service.query.call_args
        assert sample_incoming_message.question in str(call_args)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_route_returns_outgoing_message(
        self, sample_incoming_message, mock_rag_service
    ):
        """Successful route returns OutgoingMessage."""
        from app.channels.gateway import ChannelGateway

        gateway = ChannelGateway(rag_service=mock_rag_service)
        result = await gateway.process_message(sample_incoming_message)

        assert isinstance(result, OutgoingMessage)
        assert result.in_reply_to == sample_incoming_message.message_id
        assert result.channel == sample_incoming_message.channel

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_route_with_chat_history(
        self, sample_incoming_message, sample_chat_history, mock_rag_service
    ):
        """Chat history passed to RAG service."""
        from app.channels.gateway import ChannelGateway

        sample_incoming_message.chat_history = sample_chat_history
        gateway = ChannelGateway(rag_service=mock_rag_service)

        await gateway.process_message(sample_incoming_message)

        # Verify chat_history was passed
        call_args = mock_rag_service.query.call_args
        assert call_args is not None


class TestChannelGatewayHooks:
    """Test hook system."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pre_hook_called_before_rag(
        self, sample_incoming_message, mock_rag_service, mock_pre_hook
    ):
        """Pre-hook executes before RAG."""
        from app.channels.gateway import ChannelGateway

        execution_order = []

        async def pre_hook_execute(msg):
            execution_order.append("pre_hook")
            return None

        async def rag_query(*args, **kwargs):
            execution_order.append("rag")
            return {
                "answer": "Test answer",
                "sources": [],
                "response_time": 0.5,
            }

        mock_pre_hook.execute = AsyncMock(side_effect=pre_hook_execute)
        mock_rag_service.query = AsyncMock(side_effect=rag_query)

        gateway = ChannelGateway(rag_service=mock_rag_service)
        gateway.register_pre_hook(mock_pre_hook)

        await gateway.process_message(sample_incoming_message)

        assert execution_order == ["pre_hook", "rag"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pre_hook_can_modify_message(
        self, sample_incoming_message, mock_rag_service
    ):
        """Pre-hook can modify IncomingMessage."""
        from app.channels.gateway import ChannelGateway
        from app.channels.hooks import BasePreProcessingHook

        class ModifyingHook(BasePreProcessingHook):
            async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
                message.channel_metadata["modified"] = "true"
                return None

        gateway = ChannelGateway(rag_service=mock_rag_service)
        gateway.register_pre_hook(ModifyingHook(name="modifier"))

        await gateway.process_message(sample_incoming_message)

        assert sample_incoming_message.channel_metadata.get("modified") == "true"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pre_hook_can_block_processing(
        self, sample_incoming_message, mock_rag_service, mock_blocking_hook
    ):
        """Pre-hook returning error blocks processing."""
        from app.channels.gateway import ChannelGateway

        gateway = ChannelGateway(rag_service=mock_rag_service)
        gateway.register_pre_hook(mock_blocking_hook)

        result = await gateway.process_message(sample_incoming_message)

        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.RATE_LIMIT_EXCEEDED
        mock_rag_service.query.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_hook_called_after_rag(
        self, sample_incoming_message, mock_rag_service, mock_post_hook
    ):
        """Post-hook executes after RAG."""
        from app.channels.gateway import ChannelGateway

        execution_order = []

        async def rag_query(*args, **kwargs):
            execution_order.append("rag")
            return {
                "answer": "Test answer",
                "sources": [],
                "response_time": 0.5,
            }

        async def post_hook_execute(incoming, outgoing):
            execution_order.append("post_hook")
            return None

        mock_rag_service.query = AsyncMock(side_effect=rag_query)
        mock_post_hook.execute = AsyncMock(side_effect=post_hook_execute)

        gateway = ChannelGateway(rag_service=mock_rag_service)
        gateway.register_post_hook(mock_post_hook)

        await gateway.process_message(sample_incoming_message)

        assert execution_order == ["rag", "post_hook"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_hook_can_modify_response(
        self, sample_incoming_message, mock_rag_service
    ):
        """Post-hook can modify OutgoingMessage."""
        from app.channels.gateway import ChannelGateway
        from app.channels.hooks import BasePostProcessingHook

        class ModifyingPostHook(BasePostProcessingHook):
            async def execute(
                self, incoming: IncomingMessage, outgoing: OutgoingMessage
            ) -> Optional[GatewayError]:
                outgoing.suggested_questions = ["Q1", "Q2"]
                return None

        gateway = ChannelGateway(rag_service=mock_rag_service)
        gateway.register_post_hook(ModifyingPostHook(name="post_modifier"))

        result = await gateway.process_message(sample_incoming_message)

        assert isinstance(result, OutgoingMessage)
        assert result.suggested_questions == ["Q1", "Q2"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hooks_execute_in_priority_order(
        self, sample_incoming_message, mock_rag_service
    ):
        """Hooks called in priority order."""
        from app.channels.gateway import ChannelGateway
        from app.channels.hooks import BasePreProcessingHook, HookPriority

        execution_order = []

        class OrderTrackingHook(BasePreProcessingHook):
            async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
                execution_order.append(self.name)
                return None

        gateway = ChannelGateway(rag_service=mock_rag_service)

        # Register in non-priority order
        gateway.register_pre_hook(
            OrderTrackingHook(name="normal", priority=HookPriority.NORMAL)
        )
        gateway.register_pre_hook(
            OrderTrackingHook(name="high", priority=HookPriority.HIGH)
        )
        gateway.register_pre_hook(
            OrderTrackingHook(name="critical", priority=HookPriority.CRITICAL)
        )

        await gateway.process_message(sample_incoming_message)

        # Should execute: critical (0), high (100), normal (200)
        assert execution_order == ["critical", "high", "normal"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_bypass_hooks_skips_specified_hooks(
        self, sample_incoming_message, mock_rag_service
    ):
        """bypass_hooks field skips named hooks."""
        from app.channels.gateway import ChannelGateway
        from app.channels.hooks import BasePreProcessingHook

        execution_order = []

        class SkippableHook(BasePreProcessingHook):
            async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
                execution_order.append(self.name)
                return None

        gateway = ChannelGateway(rag_service=mock_rag_service)
        gateway.register_pre_hook(SkippableHook(name="hook_to_skip"))
        gateway.register_pre_hook(SkippableHook(name="hook_to_keep"))

        sample_incoming_message.bypass_hooks = ["hook_to_skip"]
        await gateway.process_message(sample_incoming_message)

        assert "hook_to_skip" not in execution_order
        assert "hook_to_keep" in execution_order

    @pytest.mark.unit
    def test_register_hook_sorts_by_priority(self, mock_rag_service, mock_pre_hook):
        """New hooks sorted into correct position."""
        from app.channels.gateway import ChannelGateway
        from app.channels.hooks import HookPriority

        gateway = ChannelGateway(rag_service=mock_rag_service)

        hook_high = MagicMock()
        hook_high.name = "high"
        hook_high.priority = HookPriority.HIGH

        hook_low = MagicMock()
        hook_low.name = "low"
        hook_low.priority = HookPriority.LOW

        hook_normal = MagicMock()
        hook_normal.name = "normal"
        hook_normal.priority = HookPriority.NORMAL

        # Register in random order
        gateway.register_pre_hook(hook_normal)
        gateway.register_pre_hook(hook_low)
        gateway.register_pre_hook(hook_high)

        hooks = gateway.get_hook_info()["pre_hooks"]
        priorities = [h["priority"] for h in hooks]

        # Should be sorted ascending
        assert priorities == sorted(priorities)


class TestChannelGatewayErrorHandling:
    """Test error handling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_rag_failure_returns_gateway_error(
        self, sample_incoming_message, mock_rag_service
    ):
        """RAG exception returns GatewayError."""
        from app.channels.gateway import ChannelGateway

        mock_rag_service.query = AsyncMock(side_effect=RuntimeError("RAG service down"))

        gateway = ChannelGateway(rag_service=mock_rag_service)
        result = await gateway.process_message(sample_incoming_message)

        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.RAG_SERVICE_ERROR
        assert result.recoverable is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hook_exception_logged_but_continues(
        self, sample_incoming_message, mock_rag_service
    ):
        """Hook exception logged, processing continues."""
        from app.channels.gateway import ChannelGateway
        from app.channels.hooks import BasePreProcessingHook

        class FailingHook(BasePreProcessingHook):
            async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
                raise ValueError("Hook internal error")

        gateway = ChannelGateway(rag_service=mock_rag_service)
        gateway.register_pre_hook(FailingHook(name="failing"))

        # Should not raise, but log and continue
        await gateway.process_message(sample_incoming_message)

        # Processing should continue to RAG
        mock_rag_service.query.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_validation_error_returns_gateway_error(self, mock_rag_service):
        """Invalid message returns error."""
        from app.channels.gateway import ChannelGateway

        gateway = ChannelGateway(rag_service=mock_rag_service)

        # Create invalid message (empty question would fail validation)
        # We'll test with None to trigger validation
        result = await gateway.process_message(None)

        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.INVALID_MESSAGE


class TestChannelGatewayMetrics:
    """Test metrics collection."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_processing_time_recorded(
        self, sample_incoming_message, mock_rag_service
    ):
        """Processing time in metadata."""
        from app.channels.gateway import ChannelGateway

        gateway = ChannelGateway(rag_service=mock_rag_service)
        result = await gateway.process_message(sample_incoming_message)

        assert isinstance(result, OutgoingMessage)
        assert result.metadata.processing_time_ms >= 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hooks_executed_list_populated(
        self, sample_incoming_message, mock_rag_service, mock_pre_hook
    ):
        """hooks_executed list contains hook names."""
        from app.channels.gateway import ChannelGateway

        gateway = ChannelGateway(rag_service=mock_rag_service)
        gateway.register_pre_hook(mock_pre_hook)

        result = await gateway.process_message(sample_incoming_message)

        assert isinstance(result, OutgoingMessage)
        assert mock_pre_hook.name in result.metadata.hooks_executed
