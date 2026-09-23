"""Context mode cannot enter the legacy answer/arbitration dispatch path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.inbound_orchestrator import InboundMessageOrchestrator
from app.channels.models import ChannelType, IncomingMessage, UserContext


@pytest.mark.asyncio
@pytest.mark.parametrize("arbitration_state", ["missing", "zero_delay", "overflow"])
@pytest.mark.parametrize("context_available", [True, False])
async def test_context_never_falls_back_to_answer(arbitration_state, context_available):
    context = SimpleNamespace(process=AsyncMock(return_value=False))
    arbitration = None if arbitration_state == "missing" else MagicMock()
    services = {
        "matrix_context_runtime": context if context_available else None,
        "arbitration_service": arbitration,
    }
    runtime = SimpleNamespace(resolve_optional=services.get)
    channel = SimpleNamespace(runtime=runtime, handle_incoming=AsyncMock())
    policy = SimpleNamespace(
        response_kind="public_context",
        generation_enabled=True,
        enabled=False,
        delivery_audience="staff_room",
        ai_response_mode="hitl",
        first_response_delay_seconds=0,
    )
    dispatcher = SimpleNamespace(dispatch=AsyncMock())
    service = SimpleNamespace(get_policy=lambda _: policy)
    incoming = IncomingMessage(
        message_id="$question",
        channel=ChannelType.MATRIX,
        question="How does Bisq work?",
        user=UserContext(user_id="@user:example.org"),
        channel_metadata={"room_id": "!support:example.org"},
    )
    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="matrix",
        dispatcher=dispatcher,
        autoresponse_policy_service=service,
    )
    assert await orchestrator.process_incoming(incoming) is False
    channel.handle_incoming.assert_not_awaited()
    dispatcher.dispatch.assert_not_awaited()
    if arbitration is not None:
        arbitration.enqueue.assert_not_called()
    if context_available:
        context.process.assert_awaited_once_with(incoming, channel)
