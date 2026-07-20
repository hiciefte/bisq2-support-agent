"""Tests for channel feedback follow-up coordinator."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.feedback_followup import FeedbackFollowupCoordinator
from app.channels.models import ChannelType, IncomingMessage, UserContext
from app.channels.reactions import (
    ReactionEvent,
    ReactionProcessor,
    ReactionRating,
    SentMessageRecord,
    SentMessageTracker,
)
from app.services.channel_launch_control_service import ChannelLaunchControlService


class _AllowingLaunchControl:
    def authorize_autonomous_delivery(self, channel_id, message_id):
        return SimpleNamespace(allowed=True, reason="test_allowed")


ALLOWING_LAUNCH_CONTROL = _AllowingLaunchControl()


def _record() -> SentMessageRecord:
    return SentMessageRecord(
        internal_message_id="int-1",
        external_message_id="ext-1",
        channel_id="bisq2",
        question="Q",
        answer="A",
        user_id="model-safe-user",
        timestamp=datetime.now(timezone.utc),
        delivery_target="support.support",
        origin_sender_profile_id="user-1",
    )


@pytest.mark.asyncio
async def test_start_followup_sends_prompt_when_channel_registered() -> None:
    feedback_service = MagicMock()
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)

    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
        ttl_seconds=900,
    )

    started = await coordinator.start_followup(
        record=_record(),
        channel_id="bisq2",
        external_message_id="ext-1",
        reactor_id="user-1",
        reactor_identity_hash="hash-1",
    )

    assert started is True
    channel.send_message.assert_awaited_once()
    target, prompt = channel.send_message.await_args.args
    assert target == "support.support"
    assert prompt.user.user_id == "model-safe-user"
    assert prompt.user.metadata == {"bisq2_sender_profile_id": "user-1"}


@pytest.mark.asyncio
async def test_consume_if_pending_updates_feedback_and_acks() -> None:
    feedback_service = MagicMock()
    feedback_service.analyze_feedback_text = AsyncMock(return_value=["incomplete"])
    feedback_service.update_feedback_entry = AsyncMock(return_value=True)
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)

    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
        ttl_seconds=900,
    )

    await coordinator.start_followup(
        record=_record(),
        channel_id="bisq2",
        external_message_id="ext-1",
        reactor_id="user-1",
        reactor_identity_hash="hash-1",
    )

    incoming = IncomingMessage(
        message_id="m-2",
        channel=ChannelType.BISQ2,
        question="The answer missed trade limits.",
        user=UserContext(
            user_id="model-safe-user",
            channel_user_id="user-1",
            metadata={"bisq2_sender_profile_id": "user-1"},
        ),
        channel_metadata={"conversation_id": "support.support"},
        channel_signature=None,
    )

    consumed = await coordinator.consume_if_pending(incoming=incoming, channel=channel)

    assert consumed is True
    feedback_service.update_feedback_entry.assert_awaited_once()
    assert channel.send_message.await_count >= 2
    _, prompt = channel.send_message.await_args_list[0].args
    _, ack = channel.send_message.await_args_list[1].args
    assert prompt.user.metadata == {"bisq2_sender_profile_id": "user-1"}
    assert ack.user.metadata == {"bisq2_sender_profile_id": "user-1"}
    assert prompt.user.user_id == "model-safe-user"
    assert ack.user.user_id == "model-safe-user"


@pytest.mark.asyncio
async def test_bisq_prompt_carries_long_exact_profile_only_in_metadata() -> None:
    exact_profile = "profile+" + ("x" * 140) + "=="
    record = _record()
    record.origin_sender_profile_id = exact_profile
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=MagicMock(),
        channel_registry=registry,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    started = await coordinator.start_followup(
        record=record,
        channel_id="bisq2",
        external_message_id="message-1",
        reactor_id=exact_profile,
        reactor_identity_hash="safe-hash",
    )

    assert started is True
    _, prompt = channel.send_message.await_args.args
    assert prompt.user.user_id == "model-safe-user"
    assert prompt.user.metadata == {"bisq2_sender_profile_id": exact_profile}


@pytest.mark.asyncio
async def test_allowed_bisq_negative_reaction_prompts_and_acks_end_to_end() -> None:
    feedback_service = MagicMock()
    feedback_service.store_reaction_feedback = MagicMock()
    feedback_service.apply_feedback_weights_async = AsyncMock()
    feedback_service.analyze_feedback_text = AsyncMock(return_value=["incomplete"])
    feedback_service.update_feedback_entry = AsyncMock(return_value=True)
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    channel.get_delivery_target = MagicMock(return_value="Exact-Channel")
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )
    tracker = SentMessageTracker(ttl_hours=24)
    tracker.track(
        channel_id="bisq2",
        external_message_id="message-1",
        internal_message_id="internal-1",
        question="Q",
        answer="A",
        user_id="model-safe-user",
        delivery_target="Exact-Channel",
        origin_sender_profile_id="Exact-Profile",
    )
    processor = ReactionProcessor(
        tracker,
        feedback_service,
        followup_coordinator=coordinator,
    )

    result = await processor.process(
        ReactionEvent(
            channel_id="bisq2",
            external_message_id="message-1",
            reactor_id="Exact-Profile",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="THUMBS_DOWN",
            timestamp=datetime.now(timezone.utc),
            metadata={"delivery_target": "Exact-Channel"},
        )
    )
    incoming = IncomingMessage(
        message_id="message-2",
        channel=ChannelType.BISQ2,
        question="The answer omitted a condition.",
        user=UserContext(
            user_id="model-safe-user",
            metadata={"bisq2_sender_profile_id": "Exact-Profile"},
        ),
        channel_metadata={"conversation_id": "Exact-Channel"},
    )
    consumed = await coordinator.consume_if_pending(incoming=incoming, channel=channel)

    assert result
    assert consumed is True
    assert channel.send_message.await_count == 2
    _, prompt = channel.send_message.await_args_list[0].args
    _, ack = channel.send_message.await_args_list[1].args
    assert prompt.user.user_id == "model-safe-user"
    assert ack.user.user_id == "model-safe-user"
    assert prompt.user.metadata == {"bisq2_sender_profile_id": "Exact-Profile"}
    assert ack.user.metadata == {"bisq2_sender_profile_id": "Exact-Profile"}


@pytest.mark.asyncio
async def test_bisq_followup_rejects_generic_user_id_as_profile_substitute() -> None:
    feedback_service = MagicMock()
    feedback_service.update_feedback_entry = AsyncMock(return_value=True)
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )
    assert await coordinator.start_followup(
        record=_record(),
        channel_id="bisq2",
        external_message_id="ext-1",
        reactor_id="user-1",
        reactor_identity_hash="hash-1",
    )
    incoming = IncomingMessage(
        message_id="m-2",
        channel=ChannelType.BISQ2,
        question="The answer missed trade limits.",
        user=UserContext(
            user_id="user-1",
            channel_user_id="user-1",
            metadata={"bisq2_sender_profile_id": "different-profile"},
        ),
        channel_metadata={"conversation_id": "support.support"},
    )

    consumed = await coordinator.consume_if_pending(incoming=incoming, channel=channel)

    assert consumed is False
    feedback_service.update_feedback_entry.assert_not_awaited()
    assert channel.send_message.await_count == 1


@pytest.mark.asyncio
async def test_matrix_followup_keeps_generic_user_context_behavior() -> None:
    feedback_service = MagicMock()
    feedback_service.update_feedback_entry = AsyncMock(return_value=True)
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    channel.get_delivery_target = MagicMock(return_value="matrix-room")
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )
    record = _record()
    record.channel_id = "matrix"
    record.delivery_target = "matrix-room"
    record.origin_sender_profile_id = None
    assert await coordinator.start_followup(
        record=record,
        channel_id="matrix",
        external_message_id="event-1",
        reactor_id="matrix-user",
        reactor_identity_hash="hash-1",
    )
    incoming = IncomingMessage(
        message_id="event-2",
        channel=ChannelType.MATRIX,
        question="The answer omitted one condition.",
        user=UserContext(user_id="matrix-user"),
        channel_metadata={"room_id": "matrix-room"},
    )

    consumed = await coordinator.consume_if_pending(incoming=incoming, channel=channel)

    assert consumed is True
    _, prompt = channel.send_message.await_args_list[0].args
    _, ack = channel.send_message.await_args_list[1].args
    assert prompt.user.metadata == {}
    assert ack.user.metadata == {}


@pytest.mark.asyncio
async def test_followup_send_exception_log_omits_protected_values(caplog) -> None:
    protected_target = "protected-target"
    protected_profile = "protected-profile"
    protected_message = "protected-message"
    record = _record()
    record.delivery_target = protected_target
    record.origin_sender_profile_id = protected_profile
    record.external_message_id = protected_message
    channel = MagicMock()
    channel.send_message = AsyncMock(
        side_effect=RuntimeError(
            f"{protected_target} {protected_profile} {protected_message}"
        )
    )
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=MagicMock(),
        channel_registry=registry,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    started = await coordinator.start_followup(
        record=record,
        channel_id="bisq2",
        external_message_id=protected_message,
        reactor_id=protected_profile,
        reactor_identity_hash="safe-hash",
    )

    assert started is False
    assert "RuntimeError" in caplog.text
    assert protected_target not in caplog.text
    assert protected_profile not in caplog.text
    assert protected_message not in caplog.text


@pytest.mark.asyncio
async def test_followup_persist_exception_log_omits_protected_values(caplog) -> None:
    protected_target = "protected-target"
    protected_profile = "protected-profile"
    protected_message = "protected-message"
    record = _record()
    record.delivery_target = protected_target
    record.origin_sender_profile_id = protected_profile
    record.internal_message_id = protected_message
    feedback_service = MagicMock()
    feedback_service.update_feedback_entry = AsyncMock(
        side_effect=RuntimeError(
            f"{protected_target} {protected_profile} {protected_message}"
        )
    )
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    channel.get_delivery_target = MagicMock(return_value=protected_target)
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )
    assert await coordinator.start_followup(
        record=record,
        channel_id="bisq2",
        external_message_id="external-message",
        reactor_id=protected_profile,
        reactor_identity_hash="safe-hash",
    )
    incoming = IncomingMessage(
        message_id="incoming-message",
        channel=ChannelType.BISQ2,
        question="Clarification",
        user=UserContext(
            user_id="model-safe-user",
            metadata={"bisq2_sender_profile_id": protected_profile},
        ),
        channel_metadata={"conversation_id": protected_target},
    )

    consumed = await coordinator.consume_if_pending(incoming=incoming, channel=channel)

    assert consumed is False
    assert "RuntimeError" in caplog.text
    assert protected_target not in caplog.text
    assert protected_profile not in caplog.text
    assert protected_message not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("control_mode", ["kill", "shadow", "canary"])
async def test_start_followup_obeys_launch_control(
    tmp_path,
    control_mode: str,
) -> None:
    launch_control = ChannelLaunchControlService(
        str(tmp_path / "feedback.db"), environment_enabled=True
    )
    if control_mode != "kill":
        launch_control.set_autonomous_delivery_enabled(True)
    if control_mode == "canary":
        launch_control.set_channel_policy(
            "bisq2",
            shadow_mode=False,
            canary_enabled=True,
            canary_hourly_limit=1,
            canary_daily_limit=1,
        )
        assert launch_control.authorize_autonomous_delivery(
            "bisq2", "existing-reservation"
        ).allowed

    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=MagicMock(),
        channel_registry=registry,
        launch_control_service=launch_control,
    )

    started = await coordinator.start_followup(
        record=_record(),
        channel_id="bisq2",
        external_message_id="ext-1",
        reactor_id="user-1",
        reactor_identity_hash="hash-1",
    )

    assert started is False
    channel.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_followup_fails_closed_without_launch_control() -> None:
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=MagicMock(),
        channel_registry=registry,
    )

    started = await coordinator.start_followup(
        record=_record(),
        channel_id="bisq2",
        external_message_id="ext-1",
        reactor_id="user-1",
        reactor_identity_hash="hash-1",
    )

    assert started is False
    channel.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "launch_control",
    [
        SimpleNamespace(),
        SimpleNamespace(
            authorize_autonomous_delivery=lambda channel_id, message_id: (
                SimpleNamespace(allowed="yes", reason="invalid")
            )
        ),
        SimpleNamespace(
            authorize_autonomous_delivery=lambda channel_id, message_id: (
                SimpleNamespace(allowed=True, reason="")
            )
        ),
    ],
)
async def test_start_followup_fails_closed_for_malformed_launch_control(
    launch_control,
) -> None:
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=MagicMock(),
        channel_registry=registry,
        launch_control_service=launch_control,
    )

    started = await coordinator.start_followup(
        record=_record(),
        channel_id="matrix",
        external_message_id="external-message",
        reactor_id="test-user",
        reactor_identity_hash="test-user-hash",
    )

    assert started is False
    channel.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_followup_fails_closed_when_launch_control_raises() -> None:
    def fail_authorization(channel_id, message_id):
        raise RuntimeError("launch guard unavailable")

    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=MagicMock(),
        channel_registry=registry,
        launch_control_service=SimpleNamespace(
            authorize_autonomous_delivery=fail_authorization
        ),
    )

    started = await coordinator.start_followup(
        record=_record(),
        channel_id="matrix",
        external_message_id="external-message",
        reactor_id="test-user",
        reactor_identity_hash="test-user-hash",
    )

    assert started is False
    channel.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("control_mode", ["kill", "shadow", "canary"])
async def test_feedback_ack_obeys_launch_control(
    tmp_path,
    control_mode: str,
) -> None:
    feedback_service = MagicMock()
    feedback_service.analyze_feedback_text = AsyncMock(return_value=[])
    feedback_service.update_feedback_entry = AsyncMock(return_value=True)
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    channel.get_delivery_target = MagicMock(return_value="test-conversation")
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    launch_control = ChannelLaunchControlService(
        str(tmp_path / "feedback.db"), environment_enabled=True
    )
    launch_control.set_autonomous_delivery_enabled(True)
    launch_control.set_channel_policy("bisq2", shadow_mode=False)
    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        launch_control_service=launch_control,
    )
    record = _record()
    record.delivery_target = "test-conversation"
    assert await coordinator.start_followup(
        record=record,
        channel_id="bisq2",
        external_message_id="ext-1",
        reactor_id="user-1",
        reactor_identity_hash="hash-1",
    )

    if control_mode == "kill":
        launch_control.set_autonomous_delivery_enabled(False)
    elif control_mode == "shadow":
        launch_control.set_channel_policy("bisq2", shadow_mode=True)
    else:
        launch_control.set_channel_policy(
            "bisq2",
            canary_enabled=True,
            canary_hourly_limit=0,
            canary_daily_limit=0,
        )
    incoming = IncomingMessage(
        message_id="m-2",
        channel=ChannelType.BISQ2,
        question="The answer missed trade limits.",
        user=UserContext(
            user_id="model-safe-user",
            channel_user_id="user-1",
            metadata={"bisq2_sender_profile_id": "user-1"},
        ),
        channel_metadata={"conversation_id": "test-conversation"},
        channel_signature=None,
    )

    consumed = await coordinator.consume_if_pending(incoming=incoming, channel=channel)

    assert consumed is True
    feedback_service.update_feedback_entry.assert_awaited_once()
    assert channel.send_message.await_count == 1
