"""Fixtures for escalation tests."""

import pytest
from app.models.escalation import EscalationCreate
from app.services.escalation.escalation_repository import EscalationRepository


@pytest.fixture
def tmp_db_path(tmp_path):
    """Temporary SQLite database path."""
    return str(tmp_path / "test_escalations.db")


@pytest.fixture
def escalation_repository(tmp_db_path):
    """EscalationRepository with temporary DB."""
    return EscalationRepository(db_path=tmp_db_path)


@pytest.fixture
def sample_escalation_create():
    """Sample EscalationCreate data."""
    return EscalationCreate(
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel="web",
        user_id="web_anonymous_123",
        username="Anonymous",
        question="How do I restore my Bisq 2 wallet from seed words?",
        ai_draft_answer="Based on the documentation, you can restore your wallet by navigating to Settings > Wallet > Restore.",
        confidence_score=0.42,
        routing_action="needs_human",
        routing_reason="Low confidence score",
        sources=[{"title": "Wallet Guide", "relevance_score": 0.6}],
        channel_metadata={"session_id": "sess_abc123"},
    )
