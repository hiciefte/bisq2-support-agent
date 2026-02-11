"""Tests for EscalationPostHook integration and ordering."""

from unittest.mock import AsyncMock

import pytest


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

    async def rag_query(*args, **kwargs):
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
