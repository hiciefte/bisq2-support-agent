"""Tests for Bisq2 ChatOps transport adapter."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.chatops import ChatOpsResult
from app.channels.plugins.bisq2.chatops_adapter import Bisq2ChatOpsAdapter


def _runtime(*, staff_resolver: MagicMock | None = None) -> tuple[MagicMock, MagicMock]:
    runtime = MagicMock()
    bisq_api = MagicMock()
    bisq_api.send_support_message = AsyncMock()

    def resolve_optional(name: str):
        if name == "bisq2_api":
            return bisq_api
        if name == "staff_resolver":
            return staff_resolver
        if name == "escalation_service":
            return MagicMock()
        if name == "arbitration_service":
            return None
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
    return runtime, bisq_api


@pytest.mark.asyncio
async def test_handle_message_returns_false_for_non_chatops_text() -> None:
    runtime, bisq_api = _runtime(staff_resolver=MagicMock())
    adapter = Bisq2ChatOpsAdapter(
        runtime=runtime,
        enabled=True,
        allowed_channel_ids={"support.staff"},
    )

    handled = await adapter.handle_message(
        {
            "messageId": "msg-1",
            "channelId": "support.staff",
            "conversationId": "support.staff",
            "senderUserProfileId": "staff-001",
            "message": "plain text",
        }
    )

    assert handled is False
    bisq_api.send_support_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_message_replies_with_dispatch_result() -> None:
    staff_resolver = MagicMock()
    staff_resolver.is_staff.return_value = True
    runtime, bisq_api = _runtime(staff_resolver=staff_resolver)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value=ChatOpsResult(
            handled=True,
            ok=True,
            message="Claimed case #12.",
            command_name="claim",
            case_id=12,
        )
    )
    adapter = Bisq2ChatOpsAdapter(
        runtime=runtime,
        enabled=True,
        allowed_channel_ids={"support.staff"},
        dispatcher=dispatcher,
    )

    handled = await adapter.handle_message(
        {
            "messageId": "msg-1",
            "channelId": "support.staff",
            "conversationId": "support.staff",
            "senderUserProfileId": "staff-001",
            "message": "!case claim 12",
        }
    )

    assert handled is True
    dispatcher.dispatch.assert_awaited_once()
    bisq_api.send_support_message.assert_awaited_once_with(
        channel_id="support.staff",
        text="Claimed case #12.",
        citation="!case claim 12",
    )
