"""Tests for EscalationRepository CRUD operations."""

from datetime import datetime, timedelta, timezone

import pytest
from app.models.escalation import (
    DuplicateEscalationError,
    EscalationCreate,
    EscalationFilters,
    EscalationNotFoundError,
    EscalationStatus,
    EscalationUpdate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_create(
    message_id: str = "550e8400-e29b-41d4-a716-446655440000",
    channel: str = "web",
    **overrides,
) -> EscalationCreate:
    defaults = dict(
        message_id=message_id,
        channel=channel,
        user_id="user_123",
        username="TestUser",
        question="How do I restore my wallet?",
        ai_draft_answer="Based on the documentation, you can restore...",
        confidence_score=0.42,
        routing_action="needs_human",
        routing_reason="Low confidence",
        sources=[{"title": "Wallet Guide", "relevance_score": 0.6}],
        channel_metadata={"session_id": "sess_abc"},
    )
    defaults.update(overrides)
    return EscalationCreate(**defaults)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestEscalationRepositoryCreate:
    """Test escalation creation in SQLite."""

    @pytest.mark.asyncio
    async def test_create_escalation_returns_escalation_with_id(
        self, escalation_repository
    ):
        """Created escalation has auto-incremented ID."""
        await escalation_repository.initialize()
        result = await escalation_repository.create(_make_create())
        assert result.id >= 1
        assert result.message_id == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_create_sets_pending_status(self, escalation_repository):
        """New escalation has status='pending'."""
        await escalation_repository.initialize()
        result = await escalation_repository.create(_make_create())
        assert result.status == EscalationStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_sets_created_at_timestamp(self, escalation_repository):
        """created_at populated on creation."""
        await escalation_repository.initialize()
        before = datetime.now(timezone.utc)
        result = await escalation_repository.create(_make_create())
        after = datetime.now(timezone.utc)
        assert before <= result.created_at <= after

    @pytest.mark.asyncio
    async def test_create_duplicate_message_id_raises_error(
        self, escalation_repository
    ):
        """Duplicate message_id raises DuplicateEscalationError."""
        await escalation_repository.initialize()
        await escalation_repository.create(_make_create())
        with pytest.raises(DuplicateEscalationError):
            await escalation_repository.create(_make_create())

    @pytest.mark.asyncio
    async def test_create_stores_json_sources(self, escalation_repository):
        """Source documents stored as JSON and retrieved correctly."""
        await escalation_repository.initialize()
        sources = [
            {"title": "Guide A", "score": 0.9},
            {"title": "Guide B", "score": 0.7},
        ]
        result = await escalation_repository.create(_make_create(sources=sources))
        assert result.sources == sources

    @pytest.mark.asyncio
    async def test_create_stores_json_channel_metadata(self, escalation_repository):
        """Channel metadata stored as JSON and retrieved correctly."""
        await escalation_repository.initialize()
        metadata = {"room_id": "!abc:matrix.org", "session_id": "sess_123"}
        result = await escalation_repository.create(
            _make_create(channel_metadata=metadata)
        )
        assert result.channel_metadata == metadata


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestEscalationRepositoryRead:
    """Test escalation retrieval."""

    @pytest.mark.asyncio
    async def test_get_by_id_returns_escalation(self, escalation_repository):
        """Existing ID returns Escalation."""
        await escalation_repository.initialize()
        created = await escalation_repository.create(_make_create())
        fetched = await escalation_repository.get_by_id(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.question == created.question

    @pytest.mark.asyncio
    async def test_get_by_id_nonexistent_returns_none(self, escalation_repository):
        """Unknown ID returns None."""
        await escalation_repository.initialize()
        result = await escalation_repository.get_by_id(99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_message_id_returns_escalation(self, escalation_repository):
        """UUID message_id lookup works."""
        await escalation_repository.initialize()
        created = await escalation_repository.create(_make_create())
        fetched = await escalation_repository.get_by_message_id(
            "550e8400-e29b-41d4-a716-446655440000"
        )
        assert fetched is not None
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_message_id_nonexistent_returns_none(
        self, escalation_repository
    ):
        """Unknown message_id returns None."""
        await escalation_repository.initialize()
        result = await escalation_repository.get_by_message_id("nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestEscalationRepositoryUpdate:
    """Test escalation updates."""

    @pytest.mark.asyncio
    async def test_update_status_succeeds(self, escalation_repository):
        """Status field updated correctly."""
        await escalation_repository.initialize()
        created = await escalation_repository.create(_make_create())
        updated = await escalation_repository.update(
            created.id,
            EscalationUpdate(status=EscalationStatus.IN_REVIEW),
        )
        assert updated.status == EscalationStatus.IN_REVIEW

    @pytest.mark.asyncio
    async def test_update_staff_answer_succeeds(self, escalation_repository):
        """staff_answer and staff_id updated."""
        await escalation_repository.initialize()
        created = await escalation_repository.create(_make_create())
        now = datetime.now(timezone.utc)
        updated = await escalation_repository.update(
            created.id,
            EscalationUpdate(
                staff_answer="Here is the correct procedure...",
                staff_id="staff_42",
                status=EscalationStatus.RESPONDED,
                responded_at=now,
            ),
        )
        assert updated.staff_answer == "Here is the correct procedure..."
        assert updated.staff_id == "staff_42"
        assert updated.status == EscalationStatus.RESPONDED

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_error(self, escalation_repository):
        """Unknown ID raises EscalationNotFoundError."""
        await escalation_repository.initialize()
        with pytest.raises(EscalationNotFoundError):
            await escalation_repository.update(
                99999,
                EscalationUpdate(status=EscalationStatus.CLOSED),
            )


# ---------------------------------------------------------------------------
# List / Filter
# ---------------------------------------------------------------------------


class TestEscalationRepositoryList:
    """Test escalation listing and filtering."""

    @pytest.mark.asyncio
    async def test_list_all_returns_all(self, escalation_repository):
        """No filters returns all escalations."""
        await escalation_repository.initialize()
        await escalation_repository.create(_make_create(message_id="msg-001"))
        await escalation_repository.create(_make_create(message_id="msg-002"))
        await escalation_repository.create(_make_create(message_id="msg-003"))
        results, total = await escalation_repository.list_escalations(
            EscalationFilters()
        )
        assert total == 3
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, escalation_repository):
        """Filter by status returns matching only."""
        await escalation_repository.initialize()
        esc1 = await escalation_repository.create(_make_create(message_id="msg-001"))
        await escalation_repository.create(_make_create(message_id="msg-002"))
        await escalation_repository.update(
            esc1.id, EscalationUpdate(status=EscalationStatus.IN_REVIEW)
        )
        results, total = await escalation_repository.list_escalations(
            EscalationFilters(status=EscalationStatus.PENDING)
        )
        assert total == 1
        assert results[0].message_id == "msg-002"

    @pytest.mark.asyncio
    async def test_list_filter_by_channel(self, escalation_repository):
        """Filter by channel returns matching only."""
        await escalation_repository.initialize()
        await escalation_repository.create(
            _make_create(message_id="msg-001", channel="web")
        )
        await escalation_repository.create(
            _make_create(message_id="msg-002", channel="matrix")
        )
        results, total = await escalation_repository.list_escalations(
            EscalationFilters(channel="matrix")
        )
        assert total == 1
        assert results[0].channel == "matrix"

    @pytest.mark.asyncio
    async def test_list_pagination(self, escalation_repository):
        """Limit and offset work correctly."""
        await escalation_repository.initialize()
        for i in range(5):
            await escalation_repository.create(_make_create(message_id=f"msg-{i:03d}"))
        results, total = await escalation_repository.list_escalations(
            EscalationFilters(limit=2, offset=0)
        )
        assert total == 5
        assert len(results) == 2

        results2, total2 = await escalation_repository.list_escalations(
            EscalationFilters(limit=2, offset=2)
        )
        assert total2 == 5
        assert len(results2) == 2
        assert results[0].id != results2[0].id

    @pytest.mark.asyncio
    async def test_get_counts_by_status(self, escalation_repository):
        """Counts grouped by status are correct."""
        await escalation_repository.initialize()
        esc1 = await escalation_repository.create(_make_create(message_id="msg-001"))
        await escalation_repository.create(_make_create(message_id="msg-002"))
        await escalation_repository.update(
            esc1.id, EscalationUpdate(status=EscalationStatus.IN_REVIEW)
        )
        counts = await escalation_repository.get_counts()
        assert counts.pending == 1
        assert counts.in_review == 1
        assert counts.responded == 0
        assert counts.closed == 0
        assert counts.total == 2


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class TestEscalationRepositorySecurity:
    """Test SQL injection prevention."""

    @pytest.mark.asyncio
    async def test_sql_injection_in_question_prevented(self, escalation_repository):
        """SQL in question field doesn't execute."""
        await escalation_repository.initialize()
        malicious_question = "'; DROP TABLE escalations; --"
        result = await escalation_repository.create(
            _make_create(question=malicious_question)
        )
        assert result.question == malicious_question
        # Table still exists — verify by fetching
        fetched = await escalation_repository.get_by_id(result.id)
        assert fetched is not None

    @pytest.mark.asyncio
    async def test_sql_injection_in_staff_answer_prevented(self, escalation_repository):
        """SQL in staff_answer field doesn't execute."""
        await escalation_repository.initialize()
        created = await escalation_repository.create(_make_create())
        malicious_answer = "'; UPDATE escalations SET status='closed'; --"
        updated = await escalation_repository.update(
            created.id,
            EscalationUpdate(staff_answer=malicious_answer),
        )
        assert updated.staff_answer == malicious_answer
        # Original status unchanged (still pending, not 'closed')
        assert updated.status == EscalationStatus.PENDING


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


class TestEscalationRepositoryMaintenance:
    """Test close_stale and purge_old."""

    @pytest.mark.asyncio
    async def test_close_stale_marks_old_pending(self, escalation_repository):
        """Pending escalations older than threshold are closed."""
        await escalation_repository.initialize()
        await escalation_repository.create(_make_create(message_id="msg-001"))
        # Close anything older than 1 second in the future (catches everything)
        threshold = datetime.now(timezone.utc) + timedelta(seconds=1)
        count = await escalation_repository.close_stale(threshold)
        assert count == 1
        fetched = await escalation_repository.get_by_message_id("msg-001")
        assert fetched.status == EscalationStatus.CLOSED

    @pytest.mark.asyncio
    async def test_purge_old_deletes_closed(self, escalation_repository):
        """Closed escalations older than retention are purged."""
        await escalation_repository.initialize()
        esc = await escalation_repository.create(_make_create(message_id="msg-001"))
        await escalation_repository.update(
            esc.id, EscalationUpdate(status=EscalationStatus.CLOSED)
        )
        threshold = datetime.now(timezone.utc) + timedelta(seconds=1)
        count = await escalation_repository.purge_old(threshold)
        assert count == 1
        fetched = await escalation_repository.get_by_message_id("msg-001")
        assert fetched is None
