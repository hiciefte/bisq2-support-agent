"""Tests for EscalationPostHook gateway behavior."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.hooks import HookPriority
from app.channels.hooks.escalation_hook import EscalationPostHook
from app.channels.models import (
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)
from app.models.escalation import Escalation, EscalationPriority, EscalationStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_incoming(**overrides) -> IncomingMessage:
    defaults = dict(
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel=ChannelType.WEB,
        question="How do I restore my wallet?",
        user=UserContext(user_id="user_123"),
        channel_metadata={},
    )
    defaults.update(overrides)
    return IncomingMessage(**defaults)


def _make_outgoing(
    requires_human: bool = False, routing_action: str | None = None, **overrides
) -> OutgoingMessage:
    if routing_action is None:
        routing_action = "needs_human" if requires_human else "auto_send"
    defaults = dict(
        message_id="out-001",
        in_reply_to="550e8400-e29b-41d4-a716-446655440000",
        channel=ChannelType.WEB,
        answer="Based on the documentation...",
        user=UserContext(user_id="user_123"),
        metadata=ResponseMetadata(
            processing_time_ms=100.0,
            rag_strategy="retrieval",
            model_name="gpt-4o",
            confidence_score=0.42,
            routing_action=routing_action,
        ),
        original_question="How do I restore my wallet?",
        requires_human=requires_human,
    )
    defaults.update(overrides)
    return OutgoingMessage(**defaults)


def _make_escalation(**overrides) -> Escalation:
    defaults = dict(
        id=42,
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel="web",
        user_id="user_123",
        question="How do I restore my wallet?",
        ai_draft_answer="Based on the documentation...",
        confidence_score=0.42,
        routing_action="needs_human",
        status=EscalationStatus.PENDING,
        priority=EscalationPriority.NORMAL,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Escalation(**defaults)


@pytest.fixture
def mock_escalation_service():
    svc = MagicMock()
    svc.create_escalation = AsyncMock(return_value=_make_escalation())
    return svc


@pytest.fixture
def mock_channel_registry():
    """Registry with a mock web channel adapter."""
    registry = MagicMock()
    adapter = MagicMock()
    adapter.format_escalation_message.return_value = (
        "Your question has been forwarded to our support team. "
        "A staff member will review and respond shortly. "
        "(Reference: #42)"
    )
    registry.get.return_value = adapter
    return registry


@pytest.fixture
def hook(mock_escalation_service, mock_channel_registry):
    return EscalationPostHook(
        escalation_service=mock_escalation_service,
        channel_registry=mock_channel_registry,
    )


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------


class TestEscalationPostHookExecution:
    """Test hook behavior in gateway pipeline."""

    @pytest.mark.asyncio
    async def test_pass_through_when_auto_send(self, hook, mock_escalation_service):
        """auto_send responses pass through without escalation."""
        incoming = _make_incoming()
        outgoing = _make_outgoing(requires_human=False, routing_action="auto_send")

        result = await hook.execute(incoming, outgoing)

        assert result is None
        mock_escalation_service.create_escalation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_escalation_when_requires_human(
        self, hook, mock_escalation_service
    ):
        """requires_human=True -> escalation created."""
        incoming = _make_incoming()
        outgoing = _make_outgoing(requires_human=True)

        result = await hook.execute(incoming, outgoing)

        assert result is None
        mock_escalation_service.create_escalation.assert_awaited_once()
        assert outgoing.requires_human is True

    @pytest.mark.asyncio
    async def test_creates_escalation_for_queue_medium_without_requires_human(
        self, hook, mock_escalation_service
    ):
        """queue_medium should escalate even when requires_human is False."""
        incoming = _make_incoming()
        outgoing = _make_outgoing(
            requires_human=False,
            routing_action="queue_medium",
        )

        result = await hook.execute(incoming, outgoing)

        assert result is None
        mock_escalation_service.create_escalation.assert_awaited_once()
        assert outgoing.requires_human is True

    @pytest.mark.asyncio
    async def test_replaces_answer_with_escalation_message(
        self, hook, mock_channel_registry
    ):
        """outgoing.answer replaced with channel-appropriate message."""
        incoming = _make_incoming()
        outgoing = _make_outgoing(requires_human=True)
        original_answer = outgoing.answer

        await hook.execute(incoming, outgoing)

        assert outgoing.answer != original_answer
        assert "#42" in outgoing.answer

    @pytest.mark.asyncio
    async def test_uses_channel_adapter_message_formatter(
        self, hook, mock_channel_registry
    ):
        """Hook uses adapter.format_escalation_message(), not channel if/elif."""
        incoming = _make_incoming()
        outgoing = _make_outgoing(requires_human=True)

        await hook.execute(incoming, outgoing)

        adapter = mock_channel_registry.get.return_value
        adapter.format_escalation_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_original_language_to_adapter_formatter(
        self, hook, mock_channel_registry
    ):
        """Detected user language is forwarded for localized escalation notices."""
        incoming = _make_incoming()
        outgoing = _make_outgoing(requires_human=True)
        outgoing.metadata.original_language = "de"

        await hook.execute(incoming, outgoing)

        adapter = mock_channel_registry.get.return_value
        adapter.format_escalation_message.assert_called_once_with(
            username="user_123",
            escalation_id=42,
            support_handle="support",
            language_code="de",
        )

    @pytest.mark.asyncio
    async def test_web_channel_message_format(self, hook):
        """Web channel gets polling-appropriate message."""
        incoming = _make_incoming(channel=ChannelType.WEB)
        outgoing = _make_outgoing(requires_human=True, channel=ChannelType.WEB)

        await hook.execute(incoming, outgoing)

        assert "support team" in outgoing.answer.lower() or "#42" in outgoing.answer

    @pytest.mark.asyncio
    async def test_matrix_channel_message_format(
        self, mock_escalation_service, mock_channel_registry
    ):
        """Matrix channel gets @mention message."""
        adapter = MagicMock()
        adapter.format_escalation_message.return_value = (
            "Hello TestUser! I need human help. @support can you help?"
        )
        mock_channel_registry.get.return_value = adapter

        hook = EscalationPostHook(
            escalation_service=mock_escalation_service,
            channel_registry=mock_channel_registry,
        )
        incoming = _make_incoming(channel=ChannelType.MATRIX)
        outgoing = _make_outgoing(requires_human=True, channel=ChannelType.MATRIX)

        await hook.execute(incoming, outgoing)

        assert "@support" in outgoing.answer

    @pytest.mark.asyncio
    async def test_bisq2_channel_message_format(
        self, mock_escalation_service, mock_channel_registry
    ):
        """Bisq2 channel gets @mention message."""
        adapter = MagicMock()
        adapter.format_escalation_message.return_value = (
            "Hello TestUser! I need human help. @support can you help?"
        )
        mock_channel_registry.get.return_value = adapter

        hook = EscalationPostHook(
            escalation_service=mock_escalation_service,
            channel_registry=mock_channel_registry,
        )
        incoming = _make_incoming(channel=ChannelType.BISQ2)
        outgoing = _make_outgoing(requires_human=True, channel=ChannelType.BISQ2)

        await hook.execute(incoming, outgoing)

        assert "@support" in outgoing.answer


# ---------------------------------------------------------------------------
# Priority tests
# ---------------------------------------------------------------------------


class TestEscalationPostHookPriority:
    """Test hook ordering."""

    def test_hook_priority_is_normal(self, hook):
        """Priority is HookPriority.NORMAL (200)."""
        assert hook.priority == HookPriority.NORMAL

    def test_hook_name_is_escalation(self, hook):
        """Name is 'escalation'."""
        assert hook.name == "escalation"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestEscalationPostHookErrorHandling:
    """Test error resilience."""

    @pytest.mark.asyncio
    async def test_service_failure_does_not_block_response(
        self, mock_escalation_service, mock_channel_registry
    ):
        """If create_escalation fails, original answer still sent."""
        mock_escalation_service.create_escalation.side_effect = Exception("DB down")
        hook = EscalationPostHook(
            escalation_service=mock_escalation_service,
            channel_registry=mock_channel_registry,
        )
        incoming = _make_incoming()
        outgoing = _make_outgoing(requires_human=True)
        original_answer = outgoing.answer

        result = await hook.execute(incoming, outgoing)

        # Should not block the pipeline
        assert result is None
        # Answer should be unchanged (escalation failed)
        assert outgoing.answer == original_answer

    @pytest.mark.asyncio
    async def test_adapter_not_found_falls_back_to_generic_message(
        self, mock_escalation_service, mock_channel_registry
    ):
        """Missing adapter falls back to a generic message."""
        mock_channel_registry.get.return_value = None
        hook = EscalationPostHook(
            escalation_service=mock_escalation_service,
            channel_registry=mock_channel_registry,
        )
        incoming = _make_incoming()
        outgoing = _make_outgoing(requires_human=True)

        result = await hook.execute(incoming, outgoing)

        assert result is None
        # Should have a generic fallback message
        assert "support" in outgoing.answer.lower() or "#42" in outgoing.answer
