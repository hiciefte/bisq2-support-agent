"""Tests for ReactionProcessor: identity hashing, process flow, revocation, and auto-escalation."""

import asyncio
import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.reactions import (
    ReactionEvent,
    ReactionProcessor,
    ReactionRating,
    SentMessageTracker,
)


@pytest.fixture()
def tracker():
    """Tracker pre-loaded with one message."""
    t = SentMessageTracker(ttl_hours=24)
    t.track(
        channel_id="matrix",
        external_message_id="$evt:server",
        internal_message_id="int-1",
        question="How does Bisq work?",
        answer="Bisq is a decentralized exchange.",
        user_id="@voter:server",
        sources=[{"title": "FAQ", "score": 0.9}],
    )
    return t


@pytest.fixture()
def feedback_service():
    """Mock feedback service with store_reaction_feedback and revoke_reaction_feedback."""
    svc = MagicMock()
    svc.store_reaction_feedback = MagicMock()
    svc.revoke_reaction_feedback = MagicMock()
    svc.get_active_reaction_rating = MagicMock(return_value=0)
    return svc


@pytest.fixture()
def processor(tracker, feedback_service):
    """Processor wired with tracker and mock feedback service."""
    return ReactionProcessor(
        tracker=tracker,
        feedback_service=feedback_service,
        reactor_identity_salt="test-salt",
    )


@pytest.fixture()
def followup_coordinator():
    svc = AsyncMock()
    svc.start_followup = AsyncMock(return_value=True)
    svc.cancel_followup = AsyncMock(return_value=None)
    return svc


# =============================================================================
# Identity hashing
# =============================================================================


class TestIdentityHashing:
    """Test deterministic, salted, privacy-safe identity hashing."""

    def test_hash_is_sha256_hex(self, processor):
        result = processor.hash_reactor_identity("matrix", "@alice:server")
        assert len(result) == 64  # sha256 hex length
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_is_deterministic(self, processor):
        h1 = processor.hash_reactor_identity("matrix", "@alice:server")
        h2 = processor.hash_reactor_identity("matrix", "@alice:server")
        assert h1 == h2

    def test_hash_matches_expected(self, processor):
        """Verify hash matches manual calculation."""
        normalized = "matrix:@alice:server"
        salted = f"test-salt{normalized}"
        expected = hashlib.sha256(salted.encode()).hexdigest()
        result = processor.hash_reactor_identity("matrix", "@alice:server")
        assert result == expected

    def test_different_channels_produce_different_hashes(self, processor):
        h1 = processor.hash_reactor_identity("matrix", "user1")
        h2 = processor.hash_reactor_identity("bisq2", "user1")
        assert h1 != h2

    def test_different_users_produce_different_hashes(self, processor):
        h1 = processor.hash_reactor_identity("matrix", "@alice:server")
        h2 = processor.hash_reactor_identity("matrix", "@bob:server")
        assert h1 != h2

    def test_different_salts_produce_different_hashes(self, tracker, feedback_service):
        p1 = ReactionProcessor(
            tracker=tracker,
            feedback_service=feedback_service,
            reactor_identity_salt="salt-a",
        )
        p2 = ReactionProcessor(
            tracker=tracker,
            feedback_service=feedback_service,
            reactor_identity_salt="salt-b",
        )
        h1 = p1.hash_reactor_identity("matrix", "@alice:server")
        h2 = p2.hash_reactor_identity("matrix", "@alice:server")
        assert h1 != h2

    def test_empty_salt_still_hashes(self, tracker, feedback_service):
        p = ReactionProcessor(
            tracker=tracker, feedback_service=feedback_service, reactor_identity_salt=""
        )
        result = p.hash_reactor_identity("matrix", "@alice:server")
        expected = hashlib.sha256("matrix:@alice:server".encode()).hexdigest()
        assert result == expected


# =============================================================================
# Process flow
# =============================================================================


class TestProcessFlow:
    """Test full process flow: tracked message → feedback stored."""

    @pytest.mark.asyncio()
    async def test_process_tracked_message_returns_true(self, processor):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor.process(event)
        assert result

    @pytest.mark.asyncio()
    async def test_process_calls_store_with_correct_data(
        self, processor, feedback_service
    ):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        await processor.process(event)
        feedback_service.store_reaction_feedback.assert_called_once()
        call_kwargs = feedback_service.store_reaction_feedback.call_args
        # Check key fields
        assert call_kwargs.kwargs["message_id"] == "int-1"
        assert call_kwargs.kwargs["rating"] == "positive"
        assert call_kwargs.kwargs["channel"] == "matrix"
        assert call_kwargs.kwargs["feedback_method"] == "reaction"
        assert call_kwargs.kwargs["external_message_id"] == "$evt:server"
        assert call_kwargs.kwargs["reaction_emoji"] == "\U0001f44d"
        assert call_kwargs.kwargs["question"] == "How does Bisq work?"
        assert call_kwargs.kwargs["answer"] == "Bisq is a decentralized exchange."
        assert call_kwargs.kwargs["sources"] == [{"title": "FAQ", "score": 0.9}]

    @pytest.mark.asyncio()
    async def test_process_negative_rating(self, processor, feedback_service):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        await processor.process(event)
        call_kwargs = feedback_service.store_reaction_feedback.call_args
        assert call_kwargs.kwargs["rating"] == "negative"

    @pytest.mark.asyncio()
    async def test_process_includes_reactor_identity_hash(
        self, processor, feedback_service
    ):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        await processor.process(event)
        call_kwargs = feedback_service.store_reaction_feedback.call_args
        expected_hash = processor.hash_reactor_identity("matrix", "@voter:server")
        assert call_kwargs.kwargs["reactor_identity_hash"] == expected_hash

    @pytest.mark.asyncio()
    async def test_non_asker_reaction_is_ignored(self, processor, feedback_service):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@someone-else:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor.process(event)
        assert not result
        feedback_service.store_reaction_feedback.assert_not_called()

    @pytest.mark.asyncio()
    async def test_conflicting_reactions_clear_projection(
        self, tracker, feedback_service
    ):
        processor = ReactionProcessor(
            tracker=tracker,
            feedback_service=feedback_service,
            reactor_identity_salt="test-salt",
        )
        await processor.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.POSITIVE,
                raw_reaction="\U0001f44d",
                timestamp=datetime.now(timezone.utc),
            )
        )
        await processor.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.NEGATIVE,
                raw_reaction="\U0001f44e",
                timestamp=datetime.now(timezone.utc),
            )
        )
        assert feedback_service.store_reaction_feedback.call_count == 1
        feedback_service.revoke_reaction_feedback.assert_called_once()


# =============================================================================
# Untracked reaction telemetry
# =============================================================================


class TestUntrackedTelemetry:
    """Test untracked reaction drop counting."""

    @pytest.mark.asyncio()
    async def test_untracked_reaction_returns_false(self, processor):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$unknown:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor.process(event)
        assert not result

    @pytest.mark.asyncio()
    async def test_untracked_count_increments(self, processor):
        assert processor._untracked_count == 0
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$unknown:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        await processor.process(event)
        assert processor._untracked_count == 1
        await processor.process(event)
        assert processor._untracked_count == 2

    @pytest.mark.asyncio()
    async def test_tracked_reaction_does_not_increment_untracked(self, processor):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        await processor.process(event)
        assert processor._untracked_count == 0

    @pytest.mark.asyncio()
    async def test_untracked_does_not_call_feedback_service(
        self, processor, feedback_service
    ):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$unknown:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        await processor.process(event)
        feedback_service.store_reaction_feedback.assert_not_called()


# =============================================================================
# Revocation
# =============================================================================


class TestRevocation:
    """Test reaction revocation flow."""

    @pytest.mark.asyncio()
    async def test_revoke_returns_true(self, processor):
        result = await processor.revoke_reaction(
            "matrix", "$evt:server", "@voter:server"
        )
        assert result is True

    @pytest.mark.asyncio()
    async def test_revoke_calls_feedback_service(self, processor, feedback_service):
        await processor.revoke_reaction("matrix", "$evt:server", "@voter:server")
        expected_hash = processor.hash_reactor_identity("matrix", "@voter:server")
        feedback_service.revoke_reaction_feedback.assert_called_once_with(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash=expected_hash,
        )

    @pytest.mark.asyncio()
    async def test_revoke_without_feedback_service_method(self, tracker):
        """Revoke when feedback service has no revoke_reaction_feedback method."""
        svc = MagicMock(spec=[])  # no methods
        p = ReactionProcessor(tracker=tracker, feedback_service=svc)
        result = await p.revoke_reaction("matrix", "$evt:server", "@voter:server")
        assert result is False  # service unavailable → returns False

    @pytest.mark.asyncio()
    async def test_revoke_by_non_asker_is_ignored(self, processor, feedback_service):
        result = await processor.revoke_reaction(
            "matrix", "$evt:server", "@someone-else:server"
        )
        assert result is False
        feedback_service.revoke_reaction_feedback.assert_not_called()


# =============================================================================
# Error handling
# =============================================================================


class TestProcessErrorHandling:
    """Test error handling in process and revoke."""

    @pytest.mark.asyncio()
    async def test_process_returns_false_on_store_error(
        self, processor, feedback_service
    ):
        feedback_service.store_reaction_feedback.side_effect = RuntimeError("db error")
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor.process(event)
        assert not result

    @pytest.mark.asyncio()
    async def test_process_returns_false_when_service_unavailable(self, tracker):
        """process() returns False when feedback_service is missing."""
        svc = MagicMock(spec=[])  # no store_reaction_feedback method
        p = ReactionProcessor(tracker=tracker, feedback_service=svc)
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        result = await p.process(event)
        assert not result

    @pytest.mark.asyncio()
    async def test_revoke_returns_false_on_error(self, processor, feedback_service):
        feedback_service.revoke_reaction_feedback.side_effect = RuntimeError("db error")
        result = await processor.revoke_reaction(
            "matrix", "$evt:server", "@voter:server"
        )
        assert result is False


# =============================================================================
# Auto-escalation on negative reaction
# =============================================================================


@pytest.fixture()
def escalation_service():
    """Mock escalation service."""
    svc = AsyncMock()
    svc.create_escalation = AsyncMock(return_value=type("Esc", (), {"id": 42})())
    svc.record_staff_answer_rating = AsyncMock(return_value=True)
    svc.auto_close_reaction_escalation = AsyncMock(return_value=True)
    svc.repository = MagicMock()
    svc.repository.get_by_id = AsyncMock(return_value=None)
    svc.repository.get_by_message_id = AsyncMock(return_value=None)
    return svc


@pytest.fixture()
def high_conf_tracker():
    """Tracker with a high-confidence auto-sent message."""
    t = SentMessageTracker(ttl_hours=24)
    t.track(
        channel_id="matrix",
        external_message_id="$evt:server",
        internal_message_id="int-1",
        question="How does Bisq work?",
        answer="Bisq is a decentralized exchange.",
        user_id="@voter:server",
        sources=[{"title": "FAQ", "score": 0.9}],
        confidence_score=0.97,
        routing_action="auto_send",
        requires_human=False,
    )
    return t


@pytest.fixture()
def processor_with_esc(high_conf_tracker, feedback_service, escalation_service):
    """Processor with escalation service wired."""
    return ReactionProcessor(
        tracker=high_conf_tracker,
        feedback_service=feedback_service,
        reactor_identity_salt="test-salt",
        escalation_service=escalation_service,
    )


class TestAutoEscalation:
    """Test auto-escalation on negative reaction for high-confidence auto-sent messages."""

    @pytest.mark.asyncio()
    async def test_negative_high_conf_creates_escalation(
        self, processor_with_esc, escalation_service
    ):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor_with_esc.process(event)
        assert result  # ProcessResult truthy
        assert escalation_service.create_escalation.call_count == 1

    @pytest.mark.asyncio()
    async def test_positive_does_not_escalate(
        self, processor_with_esc, escalation_service
    ):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor_with_esc.process(event)
        assert result
        escalation_service.create_escalation.assert_not_called()

    @pytest.mark.asyncio()
    async def test_already_escalated_skips(self, feedback_service, escalation_service):
        """requires_human=True means it was already escalated -- don't double-escalate."""
        t = SentMessageTracker(ttl_hours=24)
        t.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="@voter:server",
            confidence_score=0.97,
            routing_action="needs_human",
            requires_human=True,
        )
        p = ReactionProcessor(
            tracker=t,
            feedback_service=feedback_service,
            escalation_service=escalation_service,
        )
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        await p.process(event)
        escalation_service.create_escalation.assert_not_called()

    @pytest.mark.asyncio()
    async def test_low_confidence_skips(self, feedback_service, escalation_service):
        """Low confidence (< 0.70) does not auto-escalate."""
        t = SentMessageTracker(ttl_hours=24)
        t.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="@voter:server",
            confidence_score=0.35,
            routing_action="auto_send",
            requires_human=False,
        )
        p = ReactionProcessor(
            tracker=t,
            feedback_service=feedback_service,
            escalation_service=escalation_service,
        )
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        await p.process(event)
        escalation_service.create_escalation.assert_not_called()

    @pytest.mark.asyncio()
    async def test_no_confidence_skips(self, feedback_service, escalation_service):
        """confidence=None -> no auto-escalation."""
        t = SentMessageTracker(ttl_hours=24)
        t.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="@voter:server",
        )
        p = ReactionProcessor(
            tracker=t,
            feedback_service=feedback_service,
            escalation_service=escalation_service,
        )
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        await p.process(event)
        escalation_service.create_escalation.assert_not_called()

    @pytest.mark.asyncio()
    async def test_no_escalation_service_skips(self, feedback_service):
        """escalation_service=None -> skip auto-escalation entirely."""
        t = SentMessageTracker(ttl_hours=24)
        t.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="@voter:server",
            confidence_score=0.97,
            routing_action="auto_send",
            requires_human=False,
        )
        p = ReactionProcessor(
            tracker=t,
            feedback_service=feedback_service,
        )
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        result = await p.process(event)
        assert result  # feedback stored fine, just no escalation

    @pytest.mark.asyncio()
    async def test_escalation_failure_nonfatal(
        self, processor_with_esc, escalation_service, feedback_service
    ):
        """Escalation creation failure doesn't prevent feedback storage."""
        escalation_service.create_escalation.side_effect = RuntimeError("db error")
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor_with_esc.process(event)
        assert result  # feedback was stored successfully despite escalation failure
        feedback_service.store_reaction_feedback.assert_called_once()

    @pytest.mark.asyncio()
    async def test_duplicate_escalation_handled(
        self, processor_with_esc, escalation_service, feedback_service
    ):
        """DuplicateEscalationError is caught gracefully."""
        from app.models.escalation import DuplicateEscalationError

        escalation_service.create_escalation.side_effect = DuplicateEscalationError(
            "duplicate"
        )
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor_with_esc.process(event)
        assert result  # still succeeds

    @pytest.mark.asyncio()
    async def test_result_includes_escalation_metadata(
        self, processor_with_esc, escalation_service
    ):
        """ProcessResult should include escalation_created and escalation_message_id."""
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$evt:server",
            reactor_id="@voter:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor_with_esc.process(event)
        assert hasattr(result, "escalation_created")
        assert result.escalation_created is True
        assert hasattr(result, "escalation_message_id")
        assert result.escalation_message_id == "$evt:server"

    @pytest.mark.asyncio()
    async def test_negative_escalation_is_stabilized_and_cancellable(
        self, feedback_service, escalation_service
    ):
        t = SentMessageTracker(ttl_hours=24)
        t.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="@voter:server",
            confidence_score=0.95,
            routing_action="auto_send",
            requires_human=False,
        )
        p = ReactionProcessor(
            tracker=t,
            feedback_service=feedback_service,
            escalation_service=escalation_service,
            auto_escalation_delay_seconds=0.05,
        )
        feedback_service.get_active_reaction_rating.return_value = 1

        await p.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.NEGATIVE,
                raw_reaction="\U0001f44e",
                timestamp=datetime.now(timezone.utc),
            )
        )
        await p.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.POSITIVE,
                raw_reaction="\U0001f44d",
                timestamp=datetime.now(timezone.utc),
            )
        )

        await asyncio.sleep(0.08)
        escalation_service.create_escalation.assert_not_called()

    @pytest.mark.asyncio()
    async def test_negative_escalation_fires_after_stabilization(
        self, feedback_service, escalation_service
    ):
        t = SentMessageTracker(ttl_hours=24)
        t.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="@voter:server",
            confidence_score=0.95,
            routing_action="auto_send",
            requires_human=False,
        )
        p = ReactionProcessor(
            tracker=t,
            feedback_service=feedback_service,
            escalation_service=escalation_service,
            auto_escalation_delay_seconds=0.05,
        )
        feedback_service.get_active_reaction_rating.return_value = 0

        await p.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.NEGATIVE,
                raw_reaction="\U0001f44e",
                timestamp=datetime.now(timezone.utc),
            )
        )

        await asyncio.sleep(0.08)
        escalation_service.create_escalation.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_revoke_cancels_pending_auto_escalation(
        self, feedback_service, escalation_service
    ):
        t = SentMessageTracker(ttl_hours=24)
        t.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="@voter:server",
            confidence_score=0.95,
            routing_action="auto_send",
            requires_human=False,
        )
        p = ReactionProcessor(
            tracker=t,
            feedback_service=feedback_service,
            escalation_service=escalation_service,
            auto_escalation_delay_seconds=0.05,
        )
        feedback_service.get_active_reaction_rating.return_value = 0

        await p.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.NEGATIVE,
                raw_reaction="\U0001f44e",
                timestamp=datetime.now(timezone.utc),
            )
        )
        await p.revoke_reaction("matrix", "$evt:server", "@voter:server")

        await asyncio.sleep(0.08)
        escalation_service.create_escalation.assert_not_called()

    @pytest.mark.asyncio()
    async def test_conflicting_positive_after_negative_does_not_auto_close(
        self, processor_with_esc, escalation_service
    ):
        await processor_with_esc.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.NEGATIVE,
                raw_reaction="\U0001f44e",
                timestamp=datetime.now(timezone.utc),
            )
        )
        await processor_with_esc.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.POSITIVE,
                raw_reaction="\U0001f44d",
                timestamp=datetime.now(timezone.utc),
            )
        )

        escalation_service.auto_close_reaction_escalation.assert_not_awaited()


class TestReactionFollowup:
    @pytest.mark.asyncio()
    async def test_negative_reaction_starts_followup(
        self, tracker, feedback_service, followup_coordinator
    ):
        processor = ReactionProcessor(
            tracker=tracker,
            feedback_service=feedback_service,
            reactor_identity_salt="test-salt",
            followup_coordinator=followup_coordinator,
        )
        await processor.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.NEGATIVE,
                raw_reaction="\U0001f44e",
                timestamp=datetime.now(timezone.utc),
            )
        )

        followup_coordinator.start_followup.assert_awaited_once()
        followup_coordinator.cancel_followup.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_positive_reaction_cancels_followup(
        self, tracker, feedback_service, followup_coordinator
    ):
        processor = ReactionProcessor(
            tracker=tracker,
            feedback_service=feedback_service,
            reactor_identity_salt="test-salt",
            followup_coordinator=followup_coordinator,
        )
        await processor.process(
            ReactionEvent(
                channel_id="matrix",
                external_message_id="$evt:server",
                reactor_id="@voter:server",
                rating=ReactionRating.POSITIVE,
                raw_reaction="\U0001f44d",
                timestamp=datetime.now(timezone.utc),
            )
        )
        followup_coordinator.start_followup.assert_not_awaited()
        followup_coordinator.cancel_followup.assert_awaited_once()


class TestStaffResponseRatings:
    """Staff-response reactions should feed escalation rating lane."""

    @pytest.mark.asyncio()
    async def test_staff_response_rating_is_recorded(self, feedback_service):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$staff:server",
            internal_message_id="escalation-7",
            question="Q",
            answer="Staff answer",
            user_id="@user:server",
            routing_action="staff_response",
            confidence_score=0.93,
        )
        escalation = type(
            "Escalation",
            (),
            {"id": 7, "message_id": "msg-7", "user_id": "@user:server"},
        )()
        esc_service = AsyncMock()
        esc_service.repository = MagicMock()
        esc_service.repository.get_by_id = AsyncMock(return_value=escalation)
        esc_service.repository.get_by_message_id = AsyncMock(return_value=None)
        esc_service.record_staff_answer_rating = AsyncMock(return_value=True)

        processor = ReactionProcessor(
            tracker=tracker,
            feedback_service=feedback_service,
            reactor_identity_salt="test-salt",
            escalation_service=esc_service,
        )

        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$staff:server",
            reactor_id="@user:server",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        await processor.process(event)

        expected_hash = processor.hash_reactor_identity("matrix", "@user:server")
        esc_service.record_staff_answer_rating.assert_awaited_once_with(
            escalation=escalation,
            rating=0,
            rater_id=expected_hash,
            trusted=True,
        )
        esc_service.create_escalation.assert_not_called()

    @pytest.mark.asyncio()
    async def test_staff_response_other_reactor_is_ignored(self, feedback_service):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$staff:server",
            internal_message_id="escalation-8",
            question="Q",
            answer="Staff answer",
            user_id="@user:server",
            routing_action="staff_response",
        )
        escalation = type(
            "Escalation",
            (),
            {"id": 8, "message_id": "msg-8", "user_id": "@user:server"},
        )()
        esc_service = AsyncMock()
        esc_service.repository = MagicMock()
        esc_service.repository.get_by_id = AsyncMock(return_value=escalation)
        esc_service.repository.get_by_message_id = AsyncMock(return_value=None)
        esc_service.record_staff_answer_rating = AsyncMock(return_value=True)

        processor = ReactionProcessor(
            tracker=tracker,
            feedback_service=feedback_service,
            reactor_identity_salt="test-salt",
            escalation_service=esc_service,
        )

        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$staff:server",
            reactor_id="@other:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        result = await processor.process(event)

        assert not result
        feedback_service.store_reaction_feedback.assert_not_called()
        esc_service.record_staff_answer_rating.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_staff_response_falls_back_to_in_reply_lookup(self, feedback_service):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="bisq2",
            external_message_id="staff-msg-1",
            internal_message_id="out-123",
            question="Q",
            answer="Staff answer",
            user_id="user-1",
            routing_action="staff_response",
            in_reply_to="550e8400-e29b-41d4-a716-446655440000",
        )
        escalation = type(
            "Escalation",
            (),
            {
                "id": 9,
                "message_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user-1",
            },
        )()
        esc_service = AsyncMock()
        esc_service.repository = MagicMock()
        esc_service.repository.get_by_id = AsyncMock(return_value=None)
        esc_service.repository.get_by_message_id = AsyncMock(return_value=escalation)
        esc_service.record_staff_answer_rating = AsyncMock(return_value=True)

        processor = ReactionProcessor(
            tracker=tracker,
            feedback_service=feedback_service,
            escalation_service=esc_service,
        )
        event = ReactionEvent(
            channel_id="bisq2",
            external_message_id="staff-msg-1",
            reactor_id="user-1",
            rating=ReactionRating.POSITIVE,
            raw_reaction="THUMBS_UP",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.process(event)

        esc_service.repository.get_by_id.assert_not_awaited()
        esc_service.repository.get_by_message_id.assert_awaited_once_with(
            "550e8400-e29b-41d4-a716-446655440000"
        )
        esc_service.record_staff_answer_rating.assert_awaited_once()
