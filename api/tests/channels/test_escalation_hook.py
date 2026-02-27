"""Tests for EscalationPostHook integration and ordering."""

from unittest.mock import AsyncMock

import pytest
from app.channels.hooks.escalation_hook import EscalationPostHook
from app.channels.models import (
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_escalation_hook_runs_after_pii_filter_and_creates_escalation(
    sample_incoming_message,
    mock_rag_service,
):
    from app.channels.gateway import ChannelGateway
    from app.channels.hooks.escalation_hook import EscalationPostHook
    from app.channels.middleware.pii_filter import PIIFilterHook

    # Make the RAG service return a low-confidence / needs-human response containing PII,
    # so PII filter redacts it before the escalation hook persists ai_draft_answer.
    pii_answer = "Contact me at test@example.com"

    async def rag_query(*_args, **_kwargs):
        return {
            "answer": pii_answer,
            "sources": [],
            "response_time": 0.1,
            "requires_human": True,
        }

    mock_rag_service.query = AsyncMock(side_effect=rag_query)

    mock_escalation_service = AsyncMock()
    mock_escalation_service.create_escalation = AsyncMock(
        return_value=type("Esc", (), {"id": 123})()
    )

    gateway = ChannelGateway(rag_service=mock_rag_service)
    gateway.register_post_hook(PIIFilterHook(mode="redact"))
    gateway.register_post_hook(
        EscalationPostHook(
            escalation_service=mock_escalation_service,
            channel_registry=None,
            settings=type("S", (), {"ESCALATION_ENABLED": True})(),
        )
    )

    # Priority ordering should run PII filter (HIGH=100) before escalation (NORMAL=200).
    info = gateway.get_hook_info()
    names = [h["name"] for h in info["post_hooks"]]
    assert names.index("pii_filter") < names.index("escalation")

    result = await gateway.process_message(sample_incoming_message)

    # Escalation message should replace the draft answer.
    assert "forwarded to our support team" in result.answer.lower()
    assert "#123" in result.answer

    # Escalation should be created with a redacted draft answer.
    assert mock_escalation_service.create_escalation.call_count == 1
    create_arg = mock_escalation_service.create_escalation.call_args.args[0]
    assert "[REDACTED]" in create_arg.ai_draft_answer
    assert "test@example.com" not in create_arg.ai_draft_answer


class TestEscalationHookRoutingReason:
    """Test routing_reason flows from metadata to EscalationCreate."""

    @pytest.mark.asyncio
    async def test_routing_reason_passed_to_escalation_create(self):
        mock_esc_service = AsyncMock()
        mock_esc_service.create_escalation = AsyncMock(
            return_value=type("Esc", (), {"id": 99})()
        )
        hook = EscalationPostHook(
            escalation_service=mock_esc_service,
            channel_registry=None,
            settings=type("S", (), {"ESCALATION_ENABLED": True})(),
        )

        incoming = IncomingMessage(
            message_id="test-msg-id",
            channel=ChannelType.WEB,
            question="How do I use Bisq?",
            user=UserContext(user_id="web_anon_123"),
        )
        outgoing = OutgoingMessage(
            message_id="resp-001",
            in_reply_to="test-msg-id",
            channel=ChannelType.WEB,
            user=UserContext(user_id="web_anon_123"),
            answer="Some AI answer",
            requires_human=True,
            sources=[],
            metadata=ResponseMetadata(
                processing_time_ms=100.0,
                rag_strategy="retrieval",
                model_name="gpt-4",
                confidence_score=0.35,
                routing_action="needs_human",
                routing_reason="Low confidence (35%) \u2014 1 source found",
            ),
        )

        await hook.execute(incoming, outgoing)

        assert mock_esc_service.create_escalation.call_count == 1
        create_arg = mock_esc_service.create_escalation.call_args.args[0]
        assert create_arg.routing_reason == "Low confidence (35%) \u2014 1 source found"

    @pytest.mark.asyncio
    async def test_routing_reason_defaults_none_when_missing(self):
        mock_esc_service = AsyncMock()
        mock_esc_service.create_escalation = AsyncMock(
            return_value=type("Esc", (), {"id": 100})()
        )
        hook = EscalationPostHook(
            escalation_service=mock_esc_service,
            channel_registry=None,
            settings=type("S", (), {"ESCALATION_ENABLED": True})(),
        )

        incoming = IncomingMessage(
            message_id="test-msg-id-2",
            channel=ChannelType.WEB,
            question="Another question?",
            user=UserContext(user_id="web_anon_456"),
        )
        # Metadata without routing_reason
        outgoing = OutgoingMessage(
            message_id="resp-002",
            in_reply_to="test-msg-id-2",
            channel=ChannelType.WEB,
            user=UserContext(user_id="web_anon_456"),
            answer="Some AI answer",
            requires_human=True,
            sources=[],
            metadata=ResponseMetadata(
                processing_time_ms=50.0,
                rag_strategy="retrieval",
                model_name="gpt-4",
                confidence_score=0.40,
                routing_action="needs_human",
            ),
        )

        await hook.execute(incoming, outgoing)

        create_arg = mock_esc_service.create_escalation.call_args.args[0]
        assert create_arg.routing_reason is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_escalation_hook_creates_escalation_for_queue_medium(
    sample_incoming_message,
    mock_rag_service,
):
    from app.channels.gateway import ChannelGateway
    from app.channels.hooks.escalation_hook import EscalationPostHook

    async def rag_query(*_args, **_kwargs):
        return {
            "answer": "Draft answer pending review.",
            "sources": [],
            "response_time": 0.1,
            "requires_human": False,
            "routing_action": "queue_medium",
        }

    mock_rag_service.query = AsyncMock(side_effect=rag_query)

    mock_escalation_service = AsyncMock()
    mock_escalation_service.create_escalation = AsyncMock(
        return_value=type("Esc", (), {"id": 321})()
    )

    gateway = ChannelGateway(rag_service=mock_rag_service)
    gateway.register_post_hook(
        EscalationPostHook(
            escalation_service=mock_escalation_service,
            channel_registry=None,
            settings=type("S", (), {"ESCALATION_ENABLED": True})(),
        )
    )

    result = await gateway.process_message(sample_incoming_message)

    assert "forwarded to our support team" in result.answer.lower()
    assert "#321" in result.answer
    assert result.requires_human is True
    assert mock_escalation_service.create_escalation.call_count == 1
    create_arg = mock_escalation_service.create_escalation.call_args.args[0]
    assert create_arg.routing_action == "queue_medium"
