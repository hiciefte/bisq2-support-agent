"""Tests for Bisq2 ChatOps transport adapter."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.chatops import ChatOpsResult
from app.channels.plugins.bisq2.chatops_adapter import Bisq2ChatOpsAdapter
from app.channels.staff import StaffResolver


def _runtime(*, staff_resolver: MagicMock | None = None) -> tuple[MagicMock, MagicMock]:
    runtime = MagicMock()
    runtime.settings = SimpleNamespace(
        BISQ2_ALLOWED_CHANNEL_IDS=["support.staff"],
        BISQ2_ALLOWED_SENDER_PROFILE_IDS=["staff-001"],
        BISQ2_CHATOPS_CHANNEL_IDS=["support.staff"],
        BISQ2_STAFF_NOTIFICATION_TARGET="",
    )
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
async def test_disabled_adapter_has_no_parse_dispatch_or_transport_side_effects() -> (
    None
):
    staff_resolver = MagicMock()
    staff_resolver.is_staff.return_value = True
    runtime, bisq_api = _runtime(staff_resolver=staff_resolver)
    parser = MagicMock()
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    adapter = Bisq2ChatOpsAdapter(
        runtime=runtime,
        enabled=False,
        allowed_channel_ids={"support.staff"},
        parser=parser,
        dispatcher=dispatcher,
    )

    handled = await adapter.handle_message(
        {
            "messageId": "msg-1",
            "channelId": "support.staff",
            "senderUserProfileId": "staff-001",
            "message": "!case claim 12",
        }
    )

    assert handled is False
    parser.parse.assert_not_called()
    dispatcher.dispatch.assert_not_awaited()
    bisq_api.send_support_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_message_rejects_unapproved_profile_before_dispatch() -> None:
    runtime, bisq_api = _runtime(staff_resolver=MagicMock())
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
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
            "senderUserProfileId": "staff-blocked",
            "message": "!case claim 12",
        }
    )

    assert handled is False
    dispatcher.dispatch.assert_not_awaited()
    bisq_api.send_support_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_case_colliding_allowed_profile_is_not_bisq_staff() -> None:
    runtime = MagicMock()
    runtime.settings = SimpleNamespace(
        BISQ2_ALLOWED_CHANNEL_IDS=["support.staff"],
        BISQ2_ALLOWED_SENDER_PROFILE_IDS=["Profile-X", "profile-x"],
        BISQ2_CHATOPS_CHANNEL_IDS=["support.staff"],
        BISQ2_STAFF_PROFILE_IDS=["Profile-X"],
        BISQ2_STAFF_NOTIFICATION_TARGET="",
    )
    resolver = StaffResolver(["Profile-X"], case_sensitive=True)
    bisq_api = SimpleNamespace(send_support_message=AsyncMock())
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    dependencies = {
        "staff_resolver:bisq2": resolver,
        "bisq2_api": bisq_api,
    }
    runtime.resolve_optional = MagicMock(side_effect=dependencies.get)
    adapter = Bisq2ChatOpsAdapter(
        runtime=runtime,
        enabled=True,
        allowed_channel_ids={"support.staff"},
        dispatcher=dispatcher,
    )

    handled = await adapter.handle_message(
        {
            "messageId": "msg-case-collision",
            "channelId": "support.staff",
            "conversationId": "support.staff",
            "senderUserProfileId": "profile-x",
            "message": "!case claim 12",
        }
    )

    assert handled is True
    dispatcher.dispatch.assert_not_awaited()
    bisq_api.send_support_message.assert_awaited_once()


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
        origin_sender_profile_id="staff-001",
        citation_author_user_profile_id="staff-001",
        citation_message_id="msg-1",
    )


@pytest.mark.asyncio
async def test_handle_message_replies_with_failure_notice_on_dispatch_error(
    caplog,
) -> None:
    staff_resolver = MagicMock()
    staff_resolver.is_staff.return_value = True
    runtime, bisq_api = _runtime(staff_resolver=staff_resolver)
    dispatcher = MagicMock()
    sensitive_values = ("private-endpoint", "sentinel-secret", "staff-001")
    sensitive_detail = " ".join(sensitive_values)
    dispatcher.dispatch = AsyncMock(side_effect=RuntimeError(sensitive_detail))
    adapter = Bisq2ChatOpsAdapter(
        runtime=runtime,
        enabled=True,
        allowed_channel_ids={"support.staff"},
        dispatcher=dispatcher,
    )

    with caplog.at_level(logging.WARNING):
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
    bisq_api.send_support_message.assert_awaited_once_with(
        channel_id="support.staff",
        text="Command failed to execute.",
        citation="!case claim 12",
        origin_sender_profile_id="staff-001",
        citation_author_user_profile_id="staff-001",
        citation_message_id="msg-1",
    )
    for sensitive_value in sensitive_values:
        assert sensitive_value not in caplog.text
