"""
TDD tests for _trigger_learning() with debounce in ReactionProcessor.

Tests cover:
- Learning is triggered after successful storage
- Debounce prevents rapid triggers within cooldown window
- Learning failure does not affect storage result
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.reactions import (
    ReactionEvent,
    ReactionProcessor,
    ReactionRating,
    SentMessageTracker,
)


def _make_tracker_with_record(
    channel_id: str = "matrix",
    ext_id: str = "evt_123",
) -> SentMessageTracker:
    """Create a tracker with one pre-tracked message."""
    tracker = SentMessageTracker()
    tracker.track(
        channel_id=channel_id,
        external_message_id=ext_id,
        internal_message_id="int_abc",
        question="How do I trade?",
        answer="Open the trade tab.",
        user_id="user1",
    )
    return tracker


def _make_event(
    channel_id: str = "matrix",
    ext_id: str = "evt_123",
    rating: ReactionRating = ReactionRating.POSITIVE,
) -> ReactionEvent:
    return ReactionEvent(
        channel_id=channel_id,
        external_message_id=ext_id,
        reactor_id="reactor1",
        rating=rating,
        raw_reaction="\U0001f44d",
        timestamp=datetime.now(timezone.utc),
    )


class TestReactionLearningTrigger:
    """Tests for debounced learning trigger in ReactionProcessor."""

    @pytest.mark.asyncio
    async def test_trigger_learning_called_after_successful_storage(self):
        """process() should call _trigger_learning() after store succeeds."""
        tracker = _make_tracker_with_record()
        mock_service = MagicMock()
        mock_service.store_reaction_feedback = MagicMock(return_value=True)
        mock_service.apply_feedback_weights_async = AsyncMock()

        processor = ReactionProcessor(tracker, mock_service)
        event = _make_event()

        result = await processor.process(event)

        assert result
        # _trigger_learning should have called apply_feedback_weights_async
        mock_service.apply_feedback_weights_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_debounce_prevents_rapid_triggers(self):
        """Multiple rapid reactions within cooldown should trigger learning only once."""
        tracker = SentMessageTracker()
        # Track 3 different messages
        for i in range(3):
            tracker.track(
                channel_id="matrix",
                external_message_id=f"evt_{i}",
                internal_message_id=f"int_{i}",
                question=f"Q{i}",
                answer=f"A{i}",
                user_id="user1",
            )

        mock_service = MagicMock()
        mock_service.store_reaction_feedback = MagicMock(return_value=True)
        mock_service.apply_feedback_weights_async = AsyncMock()

        processor = ReactionProcessor(tracker, mock_service)
        processor._learning_cooldown_seconds = 5.0  # 5s cooldown

        # Process 3 reactions rapidly (no delay between them)
        for i in range(3):
            event = _make_event(ext_id=f"evt_{i}")
            await processor.process(event)

        # Only 1 learning trigger should have fired (debounce blocks the rest)
        assert mock_service.apply_feedback_weights_async.call_count == 1

    @pytest.mark.asyncio
    async def test_learning_failure_does_not_affect_storage(self):
        """If _trigger_learning() fails, the feedback is still stored."""
        tracker = _make_tracker_with_record()
        mock_service = MagicMock()
        mock_service.store_reaction_feedback = MagicMock(return_value=True)
        mock_service.apply_feedback_weights_async = AsyncMock(
            side_effect=Exception("Learning crash")
        )

        processor = ReactionProcessor(tracker, mock_service)
        event = _make_event()

        result = await processor.process(event)

        # Storage should still succeed
        assert result
        mock_service.store_reaction_feedback.assert_called_once()
