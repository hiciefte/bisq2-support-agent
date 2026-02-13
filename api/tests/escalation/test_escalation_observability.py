"""Tests for escalation observability: metrics and structured logging."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.escalation import Escalation, EscalationCreate, EscalationStatus
from app.services.escalation.escalation_service import (
    ESCALATION_DELIVERY,
    ESCALATION_LIFECYCLE,
    ESCALATION_RESPONSE_TIME,
    EscalationService,
)


def _make_service(
    repo=None,
    delivery=None,
    faq_service=None,
    learning_engine=None,
    settings=None,
):
    settings = settings or MagicMock()
    settings.ESCALATION_CLAIM_TTL_MINUTES = 30
    return EscalationService(
        repository=repo or AsyncMock(),
        response_delivery=delivery or AsyncMock(),
        faq_service=faq_service or MagicMock(),
        learning_engine=learning_engine or MagicMock(),
        settings=settings,
    )


def _make_escalation(**overrides):
    defaults = dict(
        id=1,
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel="web",
        user_id="web_user_123",
        username="TestUser",
        question="How do I restore?",
        ai_draft_answer="Go to Settings.",
        confidence_score=0.42,
        routing_action="needs_human",
        routing_reason="Low confidence",
        status=EscalationStatus.IN_REVIEW,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        sources=[],
        channel_metadata={},
        staff_id="staff_1",
        claimed_at=datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Escalation(**defaults)


class TestEscalationLifecycleMetrics:
    """Test that lifecycle Counter increments on state transitions."""

    @pytest.mark.asyncio
    async def test_create_increments_lifecycle_created(self):
        """create_escalation() increments escalation_lifecycle_total{action=created}."""
        repo = AsyncMock()
        created = _make_escalation(status=EscalationStatus.PENDING)
        repo.create = AsyncMock(return_value=created)

        service = _make_service(repo=repo)
        before = ESCALATION_LIFECYCLE.labels(action="created")._value.get()
        await service.create_escalation(
            EscalationCreate(
                message_id="test-metrics-001",
                channel="web",
                user_id="user",
                username="User",
                question="Q?",
                ai_draft_answer="A.",
                confidence_score=0.4,
                routing_action="needs_human",
            )
        )
        after = ESCALATION_LIFECYCLE.labels(action="created")._value.get()
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_claim_increments_lifecycle_claimed(self):
        """claim_escalation() increments escalation_lifecycle_total{action=claimed}."""
        esc = _make_escalation(
            status=EscalationStatus.PENDING, staff_id=None, claimed_at=None
        )
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.IN_REVIEW)
        )

        service = _make_service(repo=repo)
        before = ESCALATION_LIFECYCLE.labels(action="claimed")._value.get()
        await service.claim_escalation(1, "staff_1")
        after = ESCALATION_LIFECYCLE.labels(action="claimed")._value.get()
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_respond_increments_lifecycle_responded(self):
        """respond_to_escalation() increments escalation_lifecycle_total{action=responded}."""
        esc = _make_escalation()
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery)
        before = ESCALATION_LIFECYCLE.labels(action="responded")._value.get()
        await service.respond_to_escalation(1, "Answer", "staff_1")
        after = ESCALATION_LIFECYCLE.labels(action="responded")._value.get()
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_close_increments_lifecycle_closed(self):
        """close_escalation() increments escalation_lifecycle_total{action=closed}."""
        esc = _make_escalation(status=EscalationStatus.RESPONDED)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.CLOSED)
        )

        service = _make_service(repo=repo)
        before = ESCALATION_LIFECYCLE.labels(action="closed")._value.get()
        await service.close_escalation(1)
        after = ESCALATION_LIFECYCLE.labels(action="closed")._value.get()
        assert after == before + 1


class TestEscalationDeliveryMetrics:
    """Test that delivery Counter increments by channel and outcome."""

    @pytest.mark.asyncio
    async def test_successful_delivery_increments_success(self):
        """Successful delivery increments {channel=web, outcome=success}."""
        esc = _make_escalation(channel="web")
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery)
        before = ESCALATION_DELIVERY.labels(
            channel="web", outcome="success"
        )._value.get()
        await service.respond_to_escalation(1, "Answer", "staff_1")
        after = ESCALATION_DELIVERY.labels(
            channel="web", outcome="success"
        )._value.get()
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_failed_delivery_increments_failed(self):
        """Failed delivery increments {channel=matrix, outcome=failed}."""
        esc = _make_escalation(channel="matrix")
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=False)

        service = _make_service(repo=repo, delivery=delivery)
        before = ESCALATION_DELIVERY.labels(
            channel="matrix", outcome="failed"
        )._value.get()
        await service.respond_to_escalation(1, "Answer", "staff_1")
        after = ESCALATION_DELIVERY.labels(
            channel="matrix", outcome="failed"
        )._value.get()
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_delivery_error_increments_error(self):
        """Delivery exception increments {channel=bisq2, outcome=error}."""
        esc = _make_escalation(channel="bisq2")
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(side_effect=RuntimeError("conn refused"))

        service = _make_service(repo=repo, delivery=delivery)
        before = ESCALATION_DELIVERY.labels(
            channel="bisq2", outcome="error"
        )._value.get()
        await service.respond_to_escalation(1, "Answer", "staff_1")
        after = ESCALATION_DELIVERY.labels(
            channel="bisq2", outcome="error"
        )._value.get()
        assert after == before + 1


class TestEscalationResponseTimeMetric:
    """Test response time histogram observation."""

    @pytest.mark.asyncio
    async def test_response_time_observed(self):
        """Histogram observes seconds from creation to response."""
        created = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        esc = _make_escalation(created_at=created)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery)
        await service.respond_to_escalation(1, "Answer", "staff_1")
        # Histogram sum should increase (we can't easily check the exact value
        # because datetime.now() is used, but count should increase)
        assert ESCALATION_RESPONSE_TIME._sum.get() > 0


class TestEscalationHookMetrics:
    """Test EscalationPostHook Prometheus counters."""

    @pytest.mark.asyncio
    async def test_hook_increments_created_counter(self):
        """Successful hook execution increments escalation_created_total."""
        from app.channels.hooks.escalation_hook import (
            ESCALATION_CREATED,
            EscalationPostHook,
        )
        from app.channels.models import (
            ChannelType,
            IncomingMessage,
            OutgoingMessage,
            ResponseMetadata,
            UserContext,
        )

        mock_service = AsyncMock()
        mock_service.create_escalation = AsyncMock(return_value=_make_escalation())
        mock_registry = MagicMock()
        adapter = MagicMock()
        adapter.format_escalation_message = MagicMock(return_value="Escalated")
        mock_registry.get = MagicMock(return_value=adapter)

        hook = EscalationPostHook(mock_service, mock_registry)

        incoming = IncomingMessage(
            message_id="msg-001",
            channel=ChannelType.WEB,
            question="Q?",
            user=UserContext(
                user_id="u1",
                session_id=None,
                channel_user_id=None,
                auth_token=None,
            ),
        )
        outgoing = OutgoingMessage(
            message_id="out-001",
            in_reply_to="msg-001",
            channel=ChannelType.WEB,
            answer="AI answer",
            user=UserContext(
                user_id="u1",
                session_id=None,
                channel_user_id=None,
                auth_token=None,
            ),
            metadata=ResponseMetadata(
                processing_time_ms=100.0,
                rag_strategy="hybrid",
                model_name="gpt-4",
                confidence_score=0.3,
                version_confidence=None,
            ),
            requires_human=True,
        )

        before = ESCALATION_CREATED.labels(channel="web")._value.get()
        await hook.execute(incoming, outgoing)
        after = ESCALATION_CREATED.labels(channel="web")._value.get()
        assert after == before + 1


class TestStructuredLogging:
    """Test that structured log extra fields are passed."""

    @pytest.mark.asyncio
    async def test_respond_logs_escalation_id_and_channel(self):
        """respond_to_escalation logs with extra escalation_id, channel, staff_id."""
        esc = _make_escalation(channel="matrix")
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery)

        with patch("app.services.escalation.escalation_service.logger") as mock_logger:
            await service.respond_to_escalation(1, "Answer", "staff_1")
            # Find the "Escalation responded" info call
            info_calls = [
                c for c in mock_logger.info.call_args_list if "responded" in str(c)
            ]
            assert len(info_calls) >= 1
            extra = info_calls[0][1].get("extra", {})
            assert extra["escalation_id"] == 1
            assert extra["channel"] == "matrix"
            assert extra["staff_id"] == "staff_1"
