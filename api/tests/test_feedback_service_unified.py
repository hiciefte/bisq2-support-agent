"""
TDD tests for unified feedback storage and security hardening.

Tests cover:
- Channel spoofing prevention (/feedback/react forces channel_id="web")
- Input size limits (explanation max 2000 chars, sources max 100 items)
- Learning failure resilience (storage succeeds even if weight update fails)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.feedback import FeedbackRequest
from pydantic import ValidationError


class TestChannelSpoofingPrevention:
    """Security: /feedback/react hardcodes channel_id='web' in ReactionEvent."""

    def test_react_route_forces_web_channel(self, test_client):
        """ReactionEvent passed to processor always has channel_id='web'."""
        mock_processor = MagicMock()
        mock_processor.process = AsyncMock(return_value=True)
        test_client.app.state.reaction_processor = mock_processor

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_test-uuid-1234", "rating": 1},
        )

        assert response.status_code == 200
        event = mock_processor.process.call_args.args[0]
        assert event.channel_id == "web"

    def test_react_route_uses_reaction_method(self, test_client):
        """Feedback stored via /feedback/react uses 'reaction' method (via ReactionProcessor)."""
        mock_processor = MagicMock()
        mock_processor.process = AsyncMock(return_value=True)
        test_client.app.state.reaction_processor = mock_processor

        response = test_client.post(
            "/feedback/react",
            json={"message_id": "web_test-uuid-5678", "rating": 0},
        )

        assert response.status_code == 200
        # ReactionProcessor always stores with feedback_method="reaction"
        event = mock_processor.process.call_args.args[0]
        assert event.raw_reaction in ("thumbs_up", "thumbs_down")


class TestFeedbackInputValidation:
    """Security: input size limits on FeedbackRequest model."""

    def test_explanation_max_2000_chars(self):
        """Explanation exceeding 2000 chars should be rejected."""
        long_explanation = "x" * 2001
        with pytest.raises(ValidationError):
            FeedbackRequest(
                message_id="web_test-uuid",
                question="Test",
                answer="Test",
                rating=0,
                explanation=long_explanation,
            )

    def test_explanation_at_2000_chars_accepted(self):
        """Explanation at exactly 2000 chars should be accepted."""
        explanation = "x" * 2000
        req = FeedbackRequest(
            message_id="web_test-uuid",
            question="Test",
            answer="Test",
            rating=0,
            explanation=explanation,
        )
        assert len(req.explanation) == 2000

    def test_sources_max_100_items(self):
        """Sources list exceeding 100 items should be rejected."""
        too_many_sources = [{"type": "faq", "title": f"FAQ {i}"} for i in range(101)]
        with pytest.raises(ValidationError):
            FeedbackRequest(
                message_id="web_test-uuid",
                question="Test",
                answer="Test",
                rating=1,
                sources=too_many_sources,
            )

    def test_sources_at_100_items_accepted(self):
        """Sources list at exactly 100 items should be accepted."""
        sources = [{"type": "faq", "title": f"FAQ {i}"} for i in range(100)]
        req = FeedbackRequest(
            message_id="web_test-uuid",
            question="Test",
            answer="Test",
            rating=1,
            sources=sources,
        )
        assert len(req.sources) == 100


class TestLearningFailureResilience:
    """Learning failure should not prevent feedback storage."""

    @pytest.mark.asyncio
    async def test_learning_failure_does_not_fail_storage(self, test_settings):
        """If apply_feedback_weights_async fails, store_feedback still returns True."""
        from app.services.feedback_service import FeedbackService

        service = FeedbackService(settings=test_settings)

        # Make weight application raise an exception
        with patch.object(
            service,
            "apply_feedback_weights_async",
            side_effect=Exception("Weight crash"),
        ):
            result = await service.store_feedback(
                {
                    "message_id": "web_test-resilience",
                    "question": "Test question",
                    "answer": "Test answer",
                    "rating": 1,
                }
            )

        # Storage should still succeed
        assert result is True
