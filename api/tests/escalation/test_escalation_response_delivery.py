"""Tests for ResponseDelivery service.

Tests the routing and delivery of staff responses to the correct channel adapter.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import ChannelType, OutgoingMessage
from app.models.escalation import Escalation, EscalationPriority, EscalationStatus


def _make_escalation(channel="web", **overrides):
    """Create test escalation with sensible defaults."""
    defaults = dict(
        id=42,
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel=channel,
        user_id="user_123",
        question="How do I restore my wallet?",
        ai_draft_answer="Based on docs...",
        confidence_score=0.42,
        routing_action="needs_human",
        status=EscalationStatus.RESPONDED,
        priority=EscalationPriority.NORMAL,
        created_at=datetime.now(timezone.utc),
        staff_answer="You can restore by...",
        channel_metadata=None,
    )
    defaults.update(overrides)
    return Escalation(**defaults)


class TestResponseDeliveryWeb:
    """Test web channel delivery behavior."""

    @pytest.mark.asyncio
    async def test_web_delivery_returns_true(self):
        """Web channel returns True immediately (uses polling, not push)."""
        from app.services.escalation.response_delivery import ResponseDelivery

        registry = MagicMock()
        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(channel="web")

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is True

    @pytest.mark.asyncio
    async def test_web_delivery_does_not_call_channel(self):
        """Web channel skips adapter lookup (no push needed)."""
        from app.services.escalation.response_delivery import ResponseDelivery

        registry = MagicMock()
        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(channel="web")

        await delivery.deliver(escalation, "Staff answer here")

        registry.get.assert_not_called()


class TestResponseDeliveryMatrix:
    """Test Matrix channel delivery behavior."""

    @pytest.mark.asyncio
    async def test_matrix_delivery_sends_to_room(self):
        """Matrix delivery calls send_message on adapter."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="!abc:matrix.org")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix", channel_metadata={"room_id": "!abc:matrix.org"}
        )

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is True
        registry.get.assert_called_once_with("matrix")
        adapter.get_delivery_target.assert_called_once()
        adapter.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_matrix_delivery_extracts_room_id(self):
        """Matrix delivery passes channel_metadata to get_delivery_target."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="!abc:matrix.org")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix", channel_metadata={"room_id": "!abc:matrix.org"}
        )

        await delivery.deliver(escalation, "Staff answer here")

        adapter.get_delivery_target.assert_called_once_with(
            {"room_id": "!abc:matrix.org"}
        )

    @pytest.mark.asyncio
    async def test_matrix_delivery_failure_returns_false(self):
        """Matrix delivery returns False when send_message fails."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="!abc:matrix.org")
        adapter.send_message = AsyncMock(return_value=False)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix", channel_metadata={"room_id": "!abc:matrix.org"}
        )

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is False


class TestResponseDeliveryBisq2:
    """Test Bisq2 channel delivery behavior."""

    @pytest.mark.asyncio
    async def test_bisq2_delivery_sends_to_chat(self):
        """Bisq2 delivery calls send_message with conversation_id."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="conv-123")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="bisq2", channel_metadata={"conversation_id": "conv-123"}
        )

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is True
        adapter.get_delivery_target.assert_called_once_with(
            {"conversation_id": "conv-123"}
        )

    @pytest.mark.asyncio
    async def test_bisq2_delivery_failure_returns_false(self):
        """Bisq2 delivery returns False when send_message fails."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="conv-123")
        adapter.send_message = AsyncMock(return_value=False)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="bisq2", channel_metadata={"conversation_id": "conv-123"}
        )

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is False


class TestResponseDeliveryUnknownChannel:
    """Test handling of unknown/unsupported channels."""

    @pytest.mark.asyncio
    async def test_unknown_channel_returns_false(self):
        """Unknown channel returns False (adapter not found)."""
        from app.services.escalation.response_delivery import ResponseDelivery

        registry = MagicMock()
        registry.get.return_value = None

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(channel="discord")

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is False


class TestResponseDeliveryAdapterContract:
    """Test that delivery correctly uses the adapter contract."""

    @pytest.mark.asyncio
    async def test_delivery_uses_get_delivery_target(self):
        """Delivery calls get_delivery_target to extract target from metadata."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="target-id")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix", channel_metadata={"room_id": "!room:server"}
        )

        await delivery.deliver(escalation, "Staff answer here")

        adapter.get_delivery_target.assert_called_once_with({"room_id": "!room:server"})

    @pytest.mark.asyncio
    async def test_delivery_passes_outgoing_message_to_adapter(self):
        """Delivery builds OutgoingMessage and passes to send_message."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="target-id")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix",
            channel_metadata={"room_id": "!room:server"},
            message_id="msg-001",
            user_id="user-456",
            question="How do I backup?",
        )

        await delivery.deliver(escalation, "You can backup by...")

        adapter.send_message.assert_called_once()
        call_args = adapter.send_message.call_args
        target, outgoing_msg = call_args[0]

        assert target == "target-id"
        assert isinstance(outgoing_msg, OutgoingMessage)
        assert outgoing_msg.message_id == "escalation-42"
        assert outgoing_msg.channel == ChannelType.MATRIX
        assert outgoing_msg.answer == "You can backup by..."
        assert outgoing_msg.user.user_id == "user-456"
        assert outgoing_msg.in_reply_to == "msg-001"
        assert outgoing_msg.original_question == "How do I backup?"
        assert outgoing_msg.metadata.rag_strategy == "escalation"
        assert outgoing_msg.metadata.model_name == "staff"
