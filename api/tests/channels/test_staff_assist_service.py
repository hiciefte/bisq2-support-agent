from types import SimpleNamespace

import pytest
from app.channels.staff_assist.service import StaffAssistService


@pytest.mark.asyncio
async def test_latest_payloads_are_scoped_by_channel_and_thread() -> None:
    service = StaffAssistService()
    incoming = SimpleNamespace(question="Need help")

    await service.publish(
        channel_id="matrix",
        thread_id="shared-thread",
        room_or_conversation_id="!room:server",
        case_id="matrix:shared-thread",
        state="waiting_window",
        incoming=incoming,
    )
    await service.publish(
        channel_id="bisq2",
        thread_id="shared-thread",
        room_or_conversation_id="support.shared",
        case_id="bisq2:shared-thread",
        state="waiting_window",
        incoming=incoming,
    )

    assert service.latest_for_thread("shared-thread", "matrix") is not None
    assert service.latest_for_thread("shared-thread", "bisq2") is not None
    assert (
        service.latest_for_thread("shared-thread", "matrix").room_or_conversation_id
        == "!room:server"
    )
    assert (
        service.latest_for_thread("shared-thread", "bisq2").room_or_conversation_id
        == "support.shared"
    )


@pytest.mark.asyncio
async def test_clear_thread_removes_only_matching_channel_entry() -> None:
    service = StaffAssistService()
    incoming = SimpleNamespace(question="Need help")

    await service.publish(
        channel_id="matrix",
        thread_id="shared-thread",
        room_or_conversation_id="!room:server",
        case_id="matrix:shared-thread",
        state="waiting_window",
        incoming=incoming,
    )
    await service.publish(
        channel_id="bisq2",
        thread_id="shared-thread",
        room_or_conversation_id="support.shared",
        case_id="bisq2:shared-thread",
        state="waiting_window",
        incoming=incoming,
    )

    service.clear_thread("shared-thread", "matrix")

    assert service.latest_for_thread("shared-thread", "matrix") is None
    assert service.latest_for_thread("shared-thread", "bisq2") is not None
