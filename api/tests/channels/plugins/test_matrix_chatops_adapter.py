"""Tests for Matrix ChatOps transport adapter."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.chatops import ChatOpsResult
from app.channels.plugins.matrix.chatops_adapter import MatrixChatOpsAdapter


def _runtime(*, staff_resolver: MagicMock | None = None) -> tuple[MagicMock, MagicMock]:
    runtime = MagicMock()
    runtime.settings = MagicMock(MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES=True)
    matrix_client = MagicMock()
    matrix_client.room_send = AsyncMock()

    def resolve_optional(name: str):
        if name == "matrix_client":
            return matrix_client
        if name == "staff_resolver":
            return staff_resolver
        if name == "escalation_service":
            return MagicMock()
        if name == "arbitration_service":
            return None
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
    return runtime, matrix_client


@pytest.mark.asyncio
async def test_handle_event_returns_false_for_non_chatops_message() -> None:
    runtime, matrix_client = _runtime(staff_resolver=MagicMock())
    adapter = MatrixChatOpsAdapter(
        runtime=runtime,
        enabled=True,
        allowed_room_ids={"!staff:server"},
    )

    handled = await adapter.handle_event(
        room_id="!staff:server",
        event_id="$event",
        sender="@staff:server",
        text="plain message",
    )

    assert handled is False
    matrix_client.room_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_event_replies_with_dispatch_result() -> None:
    staff_resolver = MagicMock()
    staff_resolver.is_staff.return_value = True
    runtime, matrix_client = _runtime(staff_resolver=staff_resolver)
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
    adapter = MatrixChatOpsAdapter(
        runtime=runtime,
        enabled=True,
        allowed_room_ids={"!staff:server"},
        dispatcher=dispatcher,
    )

    handled = await adapter.handle_event(
        room_id="!staff:server",
        event_id="$event",
        sender="@staff:server",
        text="!case claim 12",
    )

    assert handled is True
    dispatcher.dispatch.assert_awaited_once()
    matrix_client.room_send.assert_awaited_once()
    sent_content = matrix_client.room_send.await_args.kwargs["content"]
    assert sent_content["body"] == "Claimed case #12."
    assert sent_content["m.relates_to"]["event_id"] == "$event"
