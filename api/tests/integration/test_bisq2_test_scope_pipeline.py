"""Integration coverage for the Bisq production-test ingress boundary."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_out_of_scope_bisq_message_never_reaches_review_or_delivery() -> None:
    """A blocked sender stops before every downstream processing boundary."""
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
    from app.channels.runtime import ChannelRuntime
    from app.channels.services.live_polling_service import LivePollingService

    now = datetime.now(UTC)
    blocked_message_time = now + timedelta(seconds=30)
    fresh_export_date = (now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    settings = SimpleNamespace(
        BISQ2_ALLOWED_CHANNEL_IDS=["channel-allowed"],
        BISQ2_ALLOWED_SENDER_PROFILE_IDS=["profile-allowed"],
        BISQ2_CHATOPS_CHANNEL_IDS=[],
        BISQ2_STAFF_NOTIFICATION_TARGET="",
    )
    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(
            side_effect=[
                {
                    "exportDate": fresh_export_date,
                    "messages": [],
                },
                {
                    "exportDate": fresh_export_date,
                    "messages": [
                        {
                            "messageId": "message-blocked",
                            "channelId": "channel-allowed",
                            "senderUserProfileId": "profile-blocked",
                            "author": "Blocked fixture",
                            "message": "Should this reach the review queue?",
                            "timestamp": int(blocked_message_time.timestamp() * 1000),
                        }
                    ],
                },
            ]
        ),
        send_support_message=AsyncMock(),
    )
    question_prefilter = MagicMock()
    chatops_adapter = SimpleNamespace(handle_message=AsyncMock())
    arbitration_service = SimpleNamespace(record_staff_activity=AsyncMock())
    listener_stop = asyncio.Event()

    async def listen_forever() -> None:
        await listener_stop.wait()

    websocket_client = SimpleNamespace(
        connect=AsyncMock(),
        subscribe=AsyncMock(
            return_value={
                "type": "SubscriptionResponse",
                "requestId": "scope-pipeline-fixture",
                "payload": "[]",
                "errorMessage": None,
            }
        ),
        listen_forever=listen_forever,
        close=AsyncMock(),
        on_event=MagicMock(),
        off_event=MagicMock(),
        on_subscription_snapshot=MagicMock(),
        off_subscription_snapshot=MagicMock(),
        has_active_subscription=MagicMock(return_value=True),
        is_connected=True,
        is_listening=True,
    )
    scope = resolve_bisq2_test_scope(settings)
    reaction_handler = SimpleNamespace(
        _test_scope=scope,
        start_listening=AsyncMock(),
        stop_listening=AsyncMock(),
        is_listening=True,
    )
    dependencies = {
        "bisq2_api": bisq_api,
        "bisq2_websocket_client": websocket_client,
        "bisq2_reaction_handler": reaction_handler,
        "question_prefilter": question_prefilter,
        "bisq2_chatops_adapter": chatops_adapter,
        "arbitration_service": arbitration_service,
    }
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(side_effect=dependencies.get)
    channel = Bisq2Channel(runtime)

    launch_control = SimpleNamespace(authorize_autonomous_delivery=MagicMock())
    escalation_service = SimpleNamespace(create_escalation=AsyncMock())
    service = LivePollingService(
        channel=channel,
        channel_id="bisq2",
        launch_control_service=launch_control,
        escalation_service=escalation_service,
    )
    service.orchestrator.process_incoming = AsyncMock()

    try:
        with patch(
            "app.channels.services.live_polling_service.is_generation_enabled",
            return_value=True,
        ):
            processed = await service.run_once()
    finally:
        listener_stop.set()
        await channel.stop()

    assert processed == 0
    assert channel.test_scope_rebaseline_complete is True
    assert bisq_api.export_chat_messages.await_count == 2
    assert bisq_api.export_chat_messages.await_args_list[0].kwargs == {"since": None}
    assert bisq_api.export_chat_messages.await_args_list[1].kwargs["since"] is not None
    question_prefilter.evaluate_text.assert_not_called()
    chatops_adapter.handle_message.assert_not_awaited()
    arbitration_service.record_staff_activity.assert_not_awaited()
    service.orchestrator.process_incoming.assert_not_awaited()
    launch_control.authorize_autonomous_delivery.assert_not_called()
    escalation_service.create_escalation.assert_not_awaited()
    bisq_api.send_support_message.assert_not_awaited()
    assert "message-blocked" not in channel._message_cache_by_id
    assert "message-blocked" not in channel._seen_message_ids
