"""
TDD tests for POST /feedback/react endpoint.

Routes web thumbs-up/down through the unified ReactionProcessor pipeline
(same path as Matrix and Bisq2 reactions).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.channels.reactions import (
    ReactionProcessor,
    ReactionRating,
    SentMessageRecord,
    SentMessageTracker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_tracker_with_record() -> MagicMock:
    """Return a SentMessageTracker mock with one tracked message."""
    tracker = MagicMock(spec=SentMessageTracker)
    tracker.lookup.return_value = SentMessageRecord(
        internal_message_id="web_abc123",
        external_message_id="web_abc123",
        channel_id="web",
        question="How do I trade?",
        answer="Use the trade wizard.",
        user_id="user_test",
        timestamp=datetime.now(timezone.utc),
        sources=[{"title": "FAQ", "content": "", "url": None}],
    )
    return tracker


def _mock_processor(success: bool = True) -> MagicMock:
    """Return a ReactionProcessor mock."""
    processor = MagicMock(spec=ReactionProcessor)
    processor.process = AsyncMock(return_value=success)
    return processor


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestFeedbackReactEndpoint:
    """POST /feedback/react -> ReactionProcessor pipeline."""

    def test_positive_reaction_returns_success(self, test_client):
        """Positive reaction (rating=1) returns success=True."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_negative_reaction_returns_needs_followup(self, test_client):
        """Negative reaction (rating=0) returns needs_feedback_followup=True."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["needs_feedback_followup"] is True

    def test_positive_does_not_need_followup(self, test_client):
        """Positive reaction should NOT request followup."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 1},
        )

        data = response.json()
        assert data["needs_feedback_followup"] is False

    def test_reaction_event_has_web_channel_id(self, test_client):
        """ReactionEvent passed to processor must have channel_id='web'."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 1},
        )

        event = processor.process.call_args.args[0]
        assert event.channel_id == "web"

    def test_positive_maps_to_thumbs_up(self, test_client):
        """rating=1 should map to ReactionRating.POSITIVE with 'thumbs_up'."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 1},
        )

        event = processor.process.call_args.args[0]
        assert event.rating == ReactionRating.POSITIVE
        assert event.raw_reaction == "thumbs_up"

    def test_negative_maps_to_thumbs_down(self, test_client):
        """rating=0 should map to ReactionRating.NEGATIVE with 'thumbs_down'."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 0},
        )

        event = processor.process.call_args.args[0]
        assert event.rating == ReactionRating.NEGATIVE
        assert event.raw_reaction == "thumbs_down"

    def test_untracked_message_returns_404(self, test_client):
        """processor.process() returns False -> 404 MESSAGE_NOT_TRACKED."""
        processor = _mock_processor(success=False)
        test_client.app.state.reaction_processor = processor

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_unknown", "rating": 1},
        )

        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == "MESSAGE_NOT_TRACKED"

    def test_channel_always_forced_to_web(self, test_client):
        """Even if request somehow differs, channel_id is always 'web'."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 1},
        )

        event = processor.process.call_args.args[0]
        assert event.channel_id == "web"

    def test_processor_unavailable_returns_503(self, test_client):
        """If reaction_processor is not on app.state, return 503."""
        if hasattr(test_client.app.state, "reaction_processor"):
            delattr(test_client.app.state, "reaction_processor")

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 1},
        )

        assert response.status_code == 503


class TestReactionSubmitRequestModel:
    """Validation for the ReactionSubmitRequest Pydantic model."""

    def test_valid_web_message_id_accepted(self, test_client):
        """A valid web_<uuid> message_id should be accepted."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_a1b2c3d4", "rating": 1},
        )

        assert response.status_code == 200

    def test_rating_must_be_0_or_1(self, test_client):
        """rating outside [0,1] should be rejected."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_abc123", "rating": 5},
        )

        assert response.status_code == 422

    def test_message_id_required(self, test_client):
        """message_id is required."""
        processor = _mock_processor(success=True)
        test_client.app.state.reaction_processor = processor

        response = test_client.post(
            "/feedback/react",
            json={"rating": 1},
        )

        assert response.status_code == 422
