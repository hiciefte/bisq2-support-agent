"""Tests for reaction models: ReactionRating, ReactionEvent, SentMessageRecord."""

from datetime import datetime, timezone

import pytest
from app.channels.reactions import ReactionEvent, ReactionRating, SentMessageRecord
from pydantic import ValidationError


class TestReactionRating:
    """Test ReactionRating enum."""

    def test_negative_value(self):
        assert ReactionRating.NEGATIVE == 0

    def test_positive_value(self):
        assert ReactionRating.POSITIVE == 1

    def test_from_int(self):
        assert ReactionRating(0) == ReactionRating.NEGATIVE
        assert ReactionRating(1) == ReactionRating.POSITIVE


class TestReactionEvent:
    """Test ReactionEvent Pydantic model."""

    def test_valid_event(self):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$abc123:matrix.org",
            reactor_id="@user:matrix.org",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\U0001f44d",
            timestamp=datetime.now(timezone.utc),
        )
        assert event.channel_id == "matrix"
        assert event.rating == ReactionRating.POSITIVE

    def test_default_metadata_empty(self):
        event = ReactionEvent(
            channel_id="bisq2",
            external_message_id="abc123",
            reactor_id="user1",
            rating=ReactionRating.NEGATIVE,
            raw_reaction="\U0001f44e",
            timestamp=datetime.now(timezone.utc),
        )
        assert event.metadata == {}

    def test_with_metadata(self):
        event = ReactionEvent(
            channel_id="matrix",
            external_message_id="$event:server",
            reactor_id="@user:server",
            rating=ReactionRating.POSITIVE,
            raw_reaction="\u2764\ufe0f",
            timestamp=datetime.now(timezone.utc),
            metadata={"source": "reaction"},
        )
        assert event.metadata == {"source": "reaction"}

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            ReactionEvent(
                channel_id="matrix",
                # missing other required fields
            )

    def test_channel_id_required(self):
        with pytest.raises(ValidationError):
            ReactionEvent(
                external_message_id="abc",
                reactor_id="user",
                rating=ReactionRating.POSITIVE,
                raw_reaction="\U0001f44d",
                timestamp=datetime.now(timezone.utc),
            )


class TestSentMessageRecord:
    """Test SentMessageRecord dataclass."""

    def test_creation(self):
        now = datetime.now(timezone.utc)
        record = SentMessageRecord(
            internal_message_id="int-123",
            external_message_id="$ext:matrix.org",
            channel_id="matrix",
            question="How do I?",
            answer="You can...",
            user_id="user1",
            timestamp=now,
        )
        assert record.internal_message_id == "int-123"
        assert record.external_message_id == "$ext:matrix.org"
        assert record.channel_id == "matrix"
        assert record.sources is None

    def test_with_sources(self):
        record = SentMessageRecord(
            internal_message_id="int-456",
            external_message_id="ext-456",
            channel_id="bisq2",
            question="What is?",
            answer="It is...",
            user_id="user2",
            timestamp=datetime.now(timezone.utc),
            sources=[{"title": "FAQ", "score": 0.9}],
        )
        assert len(record.sources) == 1
        assert record.sources[0]["title"] == "FAQ"
