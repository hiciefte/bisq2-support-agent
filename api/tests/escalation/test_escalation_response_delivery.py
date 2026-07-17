"""Tests for ResponseDelivery service.

Tests the routing and delivery of staff responses to the correct channel adapter.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import ChannelType, OutgoingMessage
from app.channels.reactions import (
    ReactionEvent,
    ReactionProcessor,
    ReactionRating,
    SentMessageTracker,
)
from app.models.escalation import Escalation, EscalationPriority, EscalationStatus
from app.services.channel_launch_control_service import ChannelLaunchControlService


def _make_escalation(channel="web", **overrides):
    """Create test escalation with sensible defaults."""
    defaults = dict(
        id=42,
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel=channel,
        user_id="user_123",
        question="How do I restore my wallet?",
        ai_draft_answer="Based on docs...",
        confidence_score=0.42,
        routing_action="needs_human",
        status=EscalationStatus.RESPONDED,
        priority=EscalationPriority.NORMAL,
        created_at=datetime.now(timezone.utc),
        staff_answer="You can restore by...",
        channel_metadata=None,
    )
    defaults.update(overrides)
    return Escalation(**defaults)


def _allow_bisq_delivery(adapter) -> None:
    adapter.allows_test_delivery = MagicMock(return_value=True)


def _bisq_metadata(
    target: str = "Exact-Channel",
    profile: str = "Exact-Profile",
) -> dict[str, str]:
    return {
        "channel_id": target,
        "conversation_id": target,
        "delivery_target": target,
        "origin_sender_profile_id": profile,
        "sender_profile_id": profile,
    }


class TestResponseDeliveryWeb:
    """Test web channel delivery behavior."""

    @pytest.mark.asyncio
    async def test_web_delivery_returns_true(self):
        """Web channel returns True immediately (uses polling, not push)."""
        from app.services.escalation.response_delivery import ResponseDelivery

        registry = MagicMock()
        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(channel="web")

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is True

    @pytest.mark.asyncio
    async def test_web_delivery_does_not_call_channel(self):
        """Web channel skips adapter lookup (no push needed)."""
        from app.services.escalation.response_delivery import ResponseDelivery

        registry = MagicMock()
        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(channel="web")

        await delivery.deliver(escalation, "Staff answer here")

        registry.get.assert_not_called()


class TestResponseDeliveryMatrix:
    """Test Matrix channel delivery behavior."""

    @pytest.mark.asyncio
    async def test_matrix_delivery_sends_to_room(self):
        """Matrix delivery calls send_message on adapter."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="!abc:matrix.org")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix", channel_metadata={"room_id": "!abc:matrix.org"}
        )

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is True
        registry.get.assert_called_once_with("matrix")
        adapter.get_delivery_target.assert_called_once()
        adapter.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_matrix_delivery_extracts_room_id(self):
        """Matrix delivery passes channel_metadata to get_delivery_target."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="!abc:matrix.org")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix", channel_metadata={"room_id": "!abc:matrix.org"}
        )

        await delivery.deliver(escalation, "Staff answer here")

        adapter.get_delivery_target.assert_called_once_with(
            {"room_id": "!abc:matrix.org"}
        )

    @pytest.mark.asyncio
    async def test_matrix_delivery_failure_returns_false(self):
        """Matrix delivery returns False when send_message fails."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="!abc:matrix.org")
        adapter.send_message = AsyncMock(return_value=False)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix", channel_metadata={"room_id": "!abc:matrix.org"}
        )

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("launch_state", ["kill", "shadow"])
    @pytest.mark.parametrize(
        ("channel_id", "channel_metadata"),
        [
            ("matrix", {"room_id": "room-id"}),
            (
                "bisq2",
                _bisq_metadata("conversation-id", "profile-approved"),
            ),
        ],
    )
    async def test_reviewed_staff_delivery_ignores_autonomous_launch_guard(
        self,
        tmp_path,
        launch_state: str,
        channel_id: str,
        channel_metadata: dict[str, str],
    ) -> None:
        """Manual reviewed responses remain deliverable during an automatic stop."""
        from app.services.escalation.response_delivery import ResponseDelivery

        launch_control = ChannelLaunchControlService(
            str(tmp_path / "feedback.db"), environment_enabled=True
        )
        if launch_state == "shadow":
            launch_control.set_autonomous_delivery_enabled(True)
        expected_reason = "kill_switch" if launch_state == "kill" else "shadow_mode"
        assert launch_control.review_only_reason(channel_id) == expected_reason

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(
            side_effect=lambda metadata: metadata.get("delivery_target", "room-id")
        )
        adapter.send_message = AsyncMock(return_value=True)
        if channel_id == "bisq2":
            _allow_bisq_delivery(adapter)
        registry = MagicMock()
        registry.get.return_value = adapter
        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel=channel_id,
            channel_metadata=channel_metadata,
        )

        result = await delivery.deliver(escalation, "Reviewed staff answer")

        assert result is True
        adapter.send_message.assert_awaited_once()


class TestResponseDeliveryBisq2:
    """Test Bisq2 channel delivery behavior."""

    @pytest.mark.asyncio
    async def test_bisq2_delivery_sends_to_chat(self):
        """Bisq2 delivery calls send_message with conversation_id."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="conv-123")
        adapter.send_message = AsyncMock(return_value=True)
        _allow_bisq_delivery(adapter)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="bisq2",
            channel_metadata=_bisq_metadata("conv-123", "profile-approved"),
        )

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is True
        adapter.get_delivery_target.assert_called_once_with(
            _bisq_metadata("conv-123", "profile-approved")
        )
        _, outgoing = adapter.send_message.await_args.args
        assert outgoing.user.metadata == {"bisq2_sender_profile_id": "profile-approved"}
        assert outgoing.user.user_id == "user_123"

    @pytest.mark.asyncio
    async def test_bisq2_delivery_failure_returns_false(self):
        """Bisq2 delivery returns False when send_message fails."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="conv-123")
        adapter.send_message = AsyncMock(return_value=False)
        _allow_bisq_delivery(adapter)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="bisq2",
            channel_metadata=_bisq_metadata("conv-123", "profile-approved"),
        )

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is False

    @pytest.mark.asyncio
    async def test_negative_reaction_provenance_reaches_reviewed_delivery(self):
        from app.services.escalation.response_delivery import ResponseDelivery

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
            confidence_score=0.97,
            routing_action="auto_send",
        )
        feedback_service = MagicMock()
        feedback_service.store_reaction_feedback = MagicMock()
        feedback_service.apply_feedback_weights_async = AsyncMock()
        escalation_service = AsyncMock()
        escalation_service.create_escalation = AsyncMock(return_value=MagicMock(id=9))
        processor = ReactionProcessor(
            tracker,
            feedback_service,
            escalation_service=escalation_service,
        )
        process_result = await processor.process(
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
        create_data = escalation_service.create_escalation.await_args.args[0]
        escalation = Escalation(
            id=9,
            created_at=datetime.now(timezone.utc),
            **create_data.model_dump(),
        )
        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(
            side_effect=lambda metadata: metadata["conversation_id"]
        )
        adapter.allows_test_delivery = MagicMock(return_value=True)
        adapter.send_message = AsyncMock(return_value=True)
        registry = MagicMock()
        registry.get.return_value = adapter

        delivered = await ResponseDelivery(registry).deliver(
            escalation, "Reviewed answer"
        )

        assert process_result.escalation_created is True
        assert delivered is True
        adapter.allows_test_delivery.assert_called_once_with(
            "Exact-Channel", "Exact-Profile"
        )
        target, outgoing = adapter.send_message.await_args.args
        assert target == "Exact-Channel"
        assert outgoing.user.user_id == "model-safe-user"
        assert outgoing.user.metadata == {"bisq2_sender_profile_id": "Exact-Profile"}


class TestResponseDeliveryUnknownChannel:
    """Test handling of unknown/unsupported channels."""

    @pytest.mark.asyncio
    async def test_unknown_channel_returns_false(self):
        """Unknown channel returns False (adapter not found)."""
        from app.services.escalation.response_delivery import ResponseDelivery

        registry = MagicMock()
        registry.get.return_value = None

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(channel="discord")

        result = await delivery.deliver(escalation, "Staff answer here")

        assert result is False


class TestResponseDeliveryAdapterContract:
    """Test that delivery correctly uses the adapter contract."""

    @pytest.mark.asyncio
    async def test_delivery_uses_get_delivery_target(self):
        """Delivery calls get_delivery_target to extract target from metadata."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="target-id")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix", channel_metadata={"room_id": "!room:server"}
        )

        await delivery.deliver(escalation, "Staff answer here")

        adapter.get_delivery_target.assert_called_once_with({"room_id": "!room:server"})

    @pytest.mark.asyncio
    async def test_delivery_passes_outgoing_message_to_adapter(self):
        """Delivery builds OutgoingMessage and passes to send_message."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="target-id")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="matrix",
            channel_metadata={"room_id": "!room:server"},
            message_id="msg-001",
            user_id="user-456",
            question="How do I backup?",
        )

        await delivery.deliver(escalation, "You can backup by...")

        adapter.send_message.assert_called_once()
        call_args = adapter.send_message.call_args
        target, outgoing_msg = call_args[0]

        assert target == "target-id"
        assert isinstance(outgoing_msg, OutgoingMessage)
        assert outgoing_msg.message_id == "escalation-42"
        assert outgoing_msg.channel == ChannelType.MATRIX
        assert outgoing_msg.answer == "You can backup by..."
        assert outgoing_msg.user.user_id == "user-456"
        assert outgoing_msg.in_reply_to == "msg-001"
        assert outgoing_msg.original_question == "How do I backup?"
        assert outgoing_msg.metadata.rag_strategy == "escalation"
        assert outgoing_msg.metadata.model_name == "staff"

    @pytest.mark.asyncio
    async def test_delivery_includes_sources_and_confidence_when_answer_is_accepted(
        self,
    ):
        """Accepted AI draft keeps provenance footer data for channel markdown rendering."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="target-id")
        adapter.send_message = AsyncMock(return_value=True)
        _allow_bisq_delivery(adapter)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="bisq2",
            channel_metadata=_bisq_metadata("target-id", "profile-approved"),
            ai_draft_answer="Exact answer from AI",
            confidence_score=0.71,
            sources=[
                {
                    "document_id": "doc-1",
                    "title": "Bisq Easy",
                    "url": "https://bisq.wiki/Bisq_Easy",
                    "relevance_score": 0.61,
                    "category": "wiki",
                }
            ],
        )

        await delivery.deliver(escalation, "Exact answer from AI")

        _, outgoing_msg = adapter.send_message.call_args[0]
        assert len(outgoing_msg.sources) == 1
        assert outgoing_msg.metadata.confidence_score == 0.71

    @pytest.mark.asyncio
    async def test_delivery_omits_sources_and_confidence_when_staff_edits_answer(self):
        """Staff-edited answers should not inherit AI confidence/sources."""
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="target-id")
        adapter.send_message = AsyncMock(return_value=True)
        _allow_bisq_delivery(adapter)

        registry = MagicMock()
        registry.get.return_value = adapter

        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="bisq2",
            channel_metadata=_bisq_metadata("target-id", "profile-approved"),
            ai_draft_answer="Original AI answer",
            confidence_score=0.71,
            sources=[
                {
                    "document_id": "doc-1",
                    "title": "Bisq Easy",
                    "url": "https://bisq.wiki/Bisq_Easy",
                    "relevance_score": 0.61,
                    "category": "wiki",
                }
            ],
        )

        await delivery.deliver(escalation, "Edited by staff")

        _, outgoing_msg = adapter.send_message.call_args[0]
        assert outgoing_msg.sources == []
        assert outgoing_msg.metadata.confidence_score is None

    @pytest.mark.asyncio
    async def test_bisq_scope_denial_happens_before_translation_io(self):
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="target-id")
        adapter.allows_test_delivery = MagicMock(return_value=False)
        adapter.send_message = AsyncMock()
        registry = MagicMock()
        registry.get.return_value = adapter
        translation_service = MagicMock()
        translation_service.translate_response = AsyncMock()
        delivery = ResponseDelivery(
            registry,
            translation_service=translation_service,
        )
        escalation = _make_escalation(
            channel="bisq2",
            user_language="de",
            channel_metadata=_bisq_metadata("target-id", "profile-blocked"),
        )

        result = await delivery.deliver(escalation, "Reviewed answer")

        assert result is False
        adapter.allows_test_delivery.assert_called_once_with(
            "target-id", "profile-blocked"
        )
        translation_service.translate_response.assert_not_awaited()
        adapter.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bisq_delivery_rejects_missing_dedicated_provenance(self):
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="target-id")
        adapter.allows_test_delivery = MagicMock(return_value=True)
        adapter.send_message = AsyncMock(return_value=True)
        registry = MagicMock()
        registry.get.return_value = adapter
        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="bisq2",
            channel_metadata={
                "channel_id": "target-id",
                "conversation_id": "target-id",
                "sender_profile_id": "profile-id",
            },
        )

        result = await delivery.deliver(escalation, "Reviewed answer")

        assert result is False
        adapter.allows_test_delivery.assert_not_called()
        adapter.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delivery_exception_log_omits_protected_provenance(self, caplog):
        from app.services.escalation.response_delivery import ResponseDelivery

        protected_target = "protected-target"
        protected_profile = "protected-profile"
        protected_message = "protected-message"
        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value=protected_target)
        adapter.allows_test_delivery = MagicMock(return_value=True)
        adapter.send_message = AsyncMock(
            side_effect=RuntimeError(
                f"{protected_target} {protected_profile} {protected_message}"
            )
        )
        registry = MagicMock()
        registry.get.return_value = adapter
        delivery = ResponseDelivery(registry)
        escalation = _make_escalation(
            channel="bisq2",
            message_id=protected_message,
            channel_metadata=_bisq_metadata(protected_target, protected_profile),
        )

        result = await delivery.deliver(escalation, "Reviewed answer")

        assert result is False
        assert "RuntimeError" in caplog.text
        assert protected_target not in caplog.text
        assert protected_profile not in caplog.text
        assert protected_message not in caplog.text


class TestResponseDeliveryLocalization:
    """Test user-language localization for delivered staff answers."""

    @pytest.mark.asyncio
    async def test_delivery_translates_staff_answer_for_non_english_user(self):
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="!abc:matrix.org")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        translation_service = MagicMock()
        translation_service.translate_response = AsyncMock(
            return_value={"translated_text": "Lokalisierte Antwort"}
        )

        delivery = ResponseDelivery(registry, translation_service=translation_service)
        escalation = _make_escalation(
            channel="matrix",
            channel_metadata={"room_id": "!abc:matrix.org"},
            user_language="de",
        )

        await delivery.deliver(escalation, "Canonical English answer")

        translation_service.translate_response.assert_awaited_once_with(
            "Canonical English answer",
            target_lang="de",
            source_lang="en",
        )
        _, outgoing_msg = adapter.send_message.call_args[0]
        assert outgoing_msg.answer == "Lokalisierte Antwort"

    @pytest.mark.asyncio
    async def test_delivery_falls_back_to_canonical_answer_when_translation_fails(self):
        from app.services.escalation.response_delivery import ResponseDelivery

        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value="!abc:matrix.org")
        adapter.send_message = AsyncMock(return_value=True)

        registry = MagicMock()
        registry.get.return_value = adapter

        translation_service = MagicMock()
        translation_service.translate_response = AsyncMock(
            side_effect=RuntimeError("translation outage")
        )

        delivery = ResponseDelivery(registry, translation_service=translation_service)
        escalation = _make_escalation(
            channel="matrix",
            channel_metadata={"room_id": "!abc:matrix.org"},
            user_language="de",
        )

        await delivery.deliver(escalation, "Canonical English answer")

        _, outgoing_msg = adapter.send_message.call_args[0]
        assert outgoing_msg.answer == "Canonical English answer"

    @pytest.mark.asyncio
    async def test_localization_exception_log_omits_bisq_provenance(self, caplog):
        from app.services.escalation.response_delivery import ResponseDelivery

        protected_target = "protected-target"
        protected_profile = "protected-profile"
        protected_message = "protected-message"
        adapter = MagicMock()
        adapter.get_delivery_target = MagicMock(return_value=protected_target)
        adapter.allows_test_delivery = MagicMock(return_value=True)
        adapter.send_message = AsyncMock(return_value=True)
        registry = MagicMock()
        registry.get.return_value = adapter
        translation_service = MagicMock()
        translation_service.translate_response = AsyncMock(
            side_effect=RuntimeError(
                f"{protected_target} {protected_profile} {protected_message}"
            )
        )
        escalation = _make_escalation(
            channel="bisq2",
            message_id=protected_message,
            channel_metadata=_bisq_metadata(protected_target, protected_profile),
            user_language="de",
        )

        delivered = await ResponseDelivery(
            registry, translation_service=translation_service
        ).deliver(escalation, "Canonical answer")

        assert delivered is True
        assert "RuntimeError" in caplog.text
        assert protected_target not in caplog.text
        assert protected_profile not in caplog.text
        assert protected_message not in caplog.text
