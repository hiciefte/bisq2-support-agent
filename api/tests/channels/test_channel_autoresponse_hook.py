"""Tests for channel auto-response policy gateway hook."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.channels.gateway import ChannelGateway
from app.channels.hooks.channel_autoresponse_hook import (
    ChannelAIGenerationPolicyHook,
    ChannelAutoResponsePolicyHook,
)
from app.channels.hooks.escalation_hook import EscalationPostHook


class _PolicyServiceDualStub:
    def __init__(self, enabled: bool, generation_enabled: bool) -> None:
        self.enabled = enabled
        self.generation_enabled = generation_enabled

    def get_policy(self, channel_id: str):
        return type(
            "Policy",
            (),
            {
                "enabled": self.enabled,
                "generation_enabled": self.generation_enabled,
            },
        )()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generation_hook_blocks_when_generation_disabled(
    sample_incoming_message,
    mock_rag_service,
):
    gateway = ChannelGateway(rag_service=mock_rag_service)
    gateway.register_pre_hook(
        ChannelAIGenerationPolicyHook(
            policy_service=_PolicyServiceDualStub(
                enabled=False,
                generation_enabled=False,
            )
        )
    )

    result = await gateway.process_message(sample_incoming_message)

    assert result.error_code.value == "SERVICE_UNAVAILABLE"
    assert "generation disabled" in result.error_message.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_autoresponse_hook_forces_queue_when_channel_disabled(
    sample_incoming_message,
    mock_rag_service,
):
    async def rag_query(*args, **kwargs):
        return {
            "answer": "Immediate answer",
            "sources": [],
            "response_time": 0.1,
            "requires_human": False,
            "routing_action": "auto_send",
        }

    mock_rag_service.query = AsyncMock(side_effect=rag_query)

    gateway = ChannelGateway(rag_service=mock_rag_service)
    gateway.register_post_hook(
        ChannelAutoResponsePolicyHook(
            policy_service=_PolicyServiceDualStub(
                enabled=False,
                generation_enabled=True,
            )
        )
    )

    result = await gateway.process_message(sample_incoming_message)

    assert result.requires_human is True
    assert result.metadata.routing_action == "queue_medium"
    assert (
        result.metadata.routing_reason
        == "Channel auto-response disabled by admin policy."
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_autoresponse_hook_passes_when_channel_enabled(
    sample_incoming_message,
    mock_rag_service,
):
    async def rag_query(*args, **kwargs):
        return {
            "answer": "Immediate answer",
            "sources": [],
            "response_time": 0.1,
            "requires_human": False,
            "routing_action": "auto_send",
        }

    mock_rag_service.query = AsyncMock(side_effect=rag_query)

    gateway = ChannelGateway(rag_service=mock_rag_service)
    gateway.register_post_hook(
        ChannelAutoResponsePolicyHook(
            policy_service=_PolicyServiceDualStub(
                enabled=True,
                generation_enabled=True,
            )
        )
    )

    result = await gateway.process_message(sample_incoming_message)

    assert result.requires_human is False
    assert result.metadata.routing_action == "auto_send"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_autoresponse_hook_runs_before_escalation_hook_and_creates_escalation(
    sample_incoming_message,
    mock_rag_service,
):
    async def rag_query(*args, **kwargs):
        return {
            "answer": "Draft answer",
            "sources": [],
            "response_time": 0.1,
            "requires_human": False,
            "routing_action": "auto_send",
        }

    mock_rag_service.query = AsyncMock(side_effect=rag_query)

    mock_escalation_service = AsyncMock()
    mock_escalation_service.create_escalation = AsyncMock(
        return_value=type("Esc", (), {"id": 404})()
    )

    gateway = ChannelGateway(rag_service=mock_rag_service)
    gateway.register_post_hook(
        ChannelAutoResponsePolicyHook(
            policy_service=_PolicyServiceDualStub(
                enabled=False,
                generation_enabled=True,
            )
        )
    )
    gateway.register_post_hook(
        EscalationPostHook(
            escalation_service=mock_escalation_service,
            channel_registry=None,
            settings=type("S", (), {"ESCALATION_ENABLED": True})(),
        )
    )

    info = gateway.get_hook_info()
    names = [hook["name"] for hook in info["post_hooks"]]
    assert names.index("channel_autoresponse_policy") < names.index("escalation")

    result = await gateway.process_message(sample_incoming_message)

    assert result.requires_human is True
    assert "forwarded to our support team" in result.answer.lower()
    assert "#404" in result.answer
    assert mock_escalation_service.create_escalation.call_count == 1
    create_arg = mock_escalation_service.create_escalation.call_args.args[0]
    assert create_arg.routing_action == "queue_medium"
