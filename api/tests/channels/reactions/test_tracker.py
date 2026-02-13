"""Tests for SentMessageTracker: track, lookup, TTL expiry, multi-channel isolation."""

from datetime import datetime, timezone

from app.channels.reactions import SentMessageTracker


class TestSentMessageTrackerTrack:
    """Test message tracking."""

    def test_track_stores_record(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="How?",
            answer="Like this.",
            user_id="user1",
        )
        record = tracker.lookup("matrix", "$evt:server")
        assert record is not None
        assert record.internal_message_id == "int-1"
        assert record.question == "How?"

    def test_track_with_sources(self):
        tracker = SentMessageTracker(ttl_hours=24)
        sources = [{"title": "FAQ", "score": 0.9}]
        tracker.track(
            channel_id="bisq2",
            external_message_id="msg-1",
            internal_message_id="int-1",
            question="What?",
            answer="This.",
            user_id="user1",
            sources=sources,
        )
        record = tracker.lookup("bisq2", "msg-1")
        assert record.sources == sources

    def test_track_overwrites_existing(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Old?",
            answer="Old.",
            user_id="user1",
        )
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-2",
            question="New?",
            answer="New.",
            user_id="user1",
        )
        record = tracker.lookup("matrix", "$evt:server")
        assert record.internal_message_id == "int-2"
        assert record.question == "New?"


class TestSentMessageTrackerLookup:
    """Test message lookup."""

    def test_lookup_nonexistent_returns_none(self):
        tracker = SentMessageTracker(ttl_hours=24)
        assert tracker.lookup("matrix", "nonexistent") is None

    def test_lookup_wrong_channel_returns_none(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="u1",
        )
        assert tracker.lookup("bisq2", "$evt:server") is None


class TestSentMessageTrackerTTL:
    """Test TTL expiry."""

    def test_expired_record_returns_none(self):
        tracker = SentMessageTracker(ttl_hours=0)  # immediate expiry
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="u1",
        )
        # Force timestamp to past
        key = "matrix:$evt:server"
        record = tracker._records[key]
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        tracker._records[key] = type(record)(
            internal_message_id=record.internal_message_id,
            external_message_id=record.external_message_id,
            channel_id=record.channel_id,
            question=record.question,
            answer=record.answer,
            user_id=record.user_id,
            timestamp=past,
        )
        assert tracker.lookup("matrix", "$evt:server") is None


class TestSentMessageTrackerMultiChannel:
    """Test multi-channel isolation."""

    def test_same_ext_id_different_channels(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="msg-1",
            internal_message_id="int-m",
            question="Matrix Q",
            answer="Matrix A",
            user_id="u1",
        )
        tracker.track(
            channel_id="bisq2",
            external_message_id="msg-1",
            internal_message_id="int-b",
            question="Bisq Q",
            answer="Bisq A",
            user_id="u2",
        )
        matrix_record = tracker.lookup("matrix", "msg-1")
        bisq2_record = tracker.lookup("bisq2", "msg-1")
        assert matrix_record.internal_message_id == "int-m"
        assert bisq2_record.internal_message_id == "int-b"


class TestSentMessageTrackerRemove:
    """Test explicit removal."""

    def test_remove_existing(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:server",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="u1",
        )
        removed = tracker.remove("matrix", "$evt:server")
        assert removed is True
        assert tracker.lookup("matrix", "$evt:server") is None

    def test_remove_nonexistent(self):
        tracker = SentMessageTracker(ttl_hours=24)
        removed = tracker.remove("matrix", "nonexistent")
        assert removed is False


class TestTrackerExtendedFields:
    """Test confidence/routing fields on SentMessageRecord via tracker.track()."""

    def test_track_with_confidence_score(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:1",
            internal_message_id="int-1",
            question="Q",
            answer="A",
            user_id="u1",
            confidence_score=0.85,
        )
        record = tracker.lookup("matrix", "$evt:1")
        assert record.confidence_score == 0.85

    def test_track_with_requires_human_true(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:2",
            internal_message_id="int-2",
            question="Q",
            answer="A",
            user_id="u1",
            requires_human=True,
        )
        record = tracker.lookup("matrix", "$evt:2")
        assert record.requires_human is True

    def test_track_with_routing_action(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:3",
            internal_message_id="int-3",
            question="Q",
            answer="A",
            user_id="u1",
            routing_action="auto_send",
        )
        record = tracker.lookup("matrix", "$evt:3")
        assert record.routing_action == "auto_send"

    def test_new_fields_default_none(self):
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="matrix",
            external_message_id="$evt:4",
            internal_message_id="int-4",
            question="Q",
            answer="A",
            user_id="u1",
        )
        record = tracker.lookup("matrix", "$evt:4")
        assert record.confidence_score is None
        assert record.requires_human is None
        assert record.routing_action is None

    def test_existing_callers_unaffected(self):
        """Old-style call (no new kwargs) still works."""
        tracker = SentMessageTracker(ttl_hours=24)
        tracker.track(
            channel_id="bisq2",
            external_message_id="msg-1",
            internal_message_id="int-1",
            question="What?",
            answer="This.",
            user_id="user1",
            sources=[{"title": "FAQ"}],
        )
        record = tracker.lookup("bisq2", "msg-1")
        assert record is not None
        assert record.question == "What?"
        assert record.confidence_score is None
