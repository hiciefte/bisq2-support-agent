"""Tests for web escalation event fan-out."""

import asyncio
from datetime import datetime, timezone

import pytest
from app.models.escalation import Escalation, EscalationStatus
from app.services.escalation.escalation_event_broker import EscalationEventBroker


def _make_escalation(**overrides) -> Escalation:
    defaults = dict(
        id=1,
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel="web",
        user_id="web_user_123",
        question="How do I restore?",
        ai_draft_answer="Go to Settings.",
        confidence_score=0.42,
        routing_action="needs_human",
        status=EscalationStatus.RESPONDED,
        staff_answer="Open Settings and restore from seed words.",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        responded_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Escalation(**defaults)


@pytest.mark.asyncio
async def test_publish_delivers_only_to_matching_message_subscribers():
    broker = EscalationEventBroker()
    escalation = _make_escalation()
    other = _make_escalation(message_id="550e8400-e29b-41d4-a716-446655440001")

    async with broker.subscribe(escalation.message_id) as queue:
        await broker.publish(other)
        assert queue.empty()

        await broker.publish(escalation)

        received = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert received == escalation


@pytest.mark.asyncio
async def test_publish_keeps_latest_event_when_subscriber_is_slow():
    broker = EscalationEventBroker()
    first = _make_escalation(staff_answer="First answer")
    latest = _make_escalation(staff_answer="Latest answer")

    async with broker.subscribe(first.message_id) as queue:
        await broker.publish(first)
        await broker.publish(latest)

        received = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert received.staff_answer == "Latest answer"


@pytest.mark.asyncio
async def test_concurrent_publish_keeps_latest_event_for_same_message():
    broker = EscalationEventBroker()
    escalations = [
        _make_escalation(staff_answer=f"Concurrent answer {index}")
        for index in range(10)
    ]

    async with broker.subscribe(escalations[0].message_id) as queue:
        await asyncio.gather(
            *(broker.publish(escalation) for escalation in escalations)
        )

        received = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert received.staff_answer == "Concurrent answer 9"
