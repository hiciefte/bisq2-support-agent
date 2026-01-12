"""Tests for ConversationStateManager service."""

from datetime import datetime, timedelta

import pytest
from app.services.rag.conversation_state import ConversationStateManager


@pytest.fixture
def manager():
    return ConversationStateManager()


class TestStateCreation:
    """Test conversation state creation and retrieval."""

    def test_create_new_state(self, manager):
        state = manager.get_or_create_state("conv-123")
        assert state.turn_count == 0
        assert state.detected_version is None
        assert state.version_confidence == 0.0
        assert state.topics_discussed == []
        assert state.entities_mentioned == {}

    def test_get_existing_state(self, manager):
        # Create state
        manager.update_state(
            "conv-123", detected_version="Bisq 2", version_confidence=0.9
        )

        # Retrieve same state
        state = manager.get_or_create_state("conv-123")
        assert state.detected_version == "Bisq 2"
        assert state.version_confidence == 0.9

    def test_multiple_conversations_isolated(self, manager):
        manager.update_state(
            "conv-1", detected_version="Bisq 1", version_confidence=0.9
        )
        manager.update_state(
            "conv-2", detected_version="Bisq 2", version_confidence=0.8
        )

        state1 = manager.get_or_create_state("conv-1")
        state2 = manager.get_or_create_state("conv-2")

        assert state1.detected_version == "Bisq 1"
        assert state2.detected_version == "Bisq 2"


class TestVersionTracking:
    """Test version detection tracking across turns."""

    def test_update_version_higher_confidence(self, manager):
        manager.update_state("conv-123", "Bisq 2", 0.5)
        manager.update_state("conv-123", "Bisq 1", 0.9)
        state = manager.get_or_create_state("conv-123")
        assert state.detected_version == "Bisq 1"
        assert state.version_confidence == 0.9

    def test_lower_confidence_doesnt_override(self, manager):
        manager.update_state("conv-123", "Bisq 1", 0.9)
        manager.update_state("conv-123", "Bisq 2", 0.5)
        state = manager.get_or_create_state("conv-123")
        assert state.detected_version == "Bisq 1"
        assert state.version_confidence == 0.9

    def test_equal_confidence_doesnt_override(self, manager):
        manager.update_state("conv-123", "Bisq 1", 0.7)
        manager.update_state("conv-123", "Bisq 2", 0.7)
        state = manager.get_or_create_state("conv-123")
        assert state.detected_version == "Bisq 1"  # First one wins

    def test_none_version_doesnt_override(self, manager):
        manager.update_state("conv-123", "Bisq 1", 0.9)
        manager.update_state("conv-123", None, 0.5)
        state = manager.get_or_create_state("conv-123")
        assert state.detected_version == "Bisq 1"


class TestTopicTracking:
    """Test topic accumulation across turns."""

    def test_accumulate_topics(self, manager):
        manager.update_state("conv-123", topics=["trading"])
        manager.update_state("conv-123", topics=["reputation", "trading"])
        state = manager.get_or_create_state("conv-123")
        assert "trading" in state.topics_discussed
        assert "reputation" in state.topics_discussed
        assert len(state.topics_discussed) == 2  # No duplicates

    def test_topic_deduplication(self, manager):
        manager.update_state("conv-123", topics=["trading", "trading", "trading"])
        state = manager.get_or_create_state("conv-123")
        assert state.topics_discussed.count("trading") == 1

    def test_empty_topics_no_change(self, manager):
        manager.update_state("conv-123", topics=["trading"])
        manager.update_state("conv-123", topics=[])
        state = manager.get_or_create_state("conv-123")
        assert state.topics_discussed == ["trading"]


class TestEntityTracking:
    """Test entity tracking across turns."""

    def test_update_entities(self, manager):
        manager.update_state("conv-123", entities={"trade_id": "12345"})
        manager.update_state("conv-123", entities={"amount": "100 USD"})
        state = manager.get_or_create_state("conv-123")
        assert state.entities_mentioned["trade_id"] == "12345"
        assert state.entities_mentioned["amount"] == "100 USD"

    def test_entity_override(self, manager):
        manager.update_state("conv-123", entities={"amount": "100 USD"})
        manager.update_state("conv-123", entities={"amount": "200 USD"})
        state = manager.get_or_create_state("conv-123")
        assert state.entities_mentioned["amount"] == "200 USD"


class TestTurnCounting:
    """Test turn counter functionality."""

    def test_turn_count_increments(self, manager):
        manager.update_state("conv-123", topics=["a"])
        manager.update_state("conv-123", topics=["b"])
        manager.update_state("conv-123", topics=["c"])
        state = manager.get_or_create_state("conv-123")
        assert state.turn_count == 3

    def test_turn_count_starts_at_zero(self, manager):
        state = manager.get_or_create_state("conv-123")
        assert state.turn_count == 0


class TestContextSummary:
    """Test context summary generation."""

    def test_context_summary_with_version(self, manager):
        manager.update_state(
            "conv-123",
            detected_version="Bisq 2",
            version_confidence=0.9,
        )
        summary = manager.get_context_summary("conv-123")
        assert "Bisq 2" in summary

    def test_context_summary_with_topics(self, manager):
        manager.update_state(
            "conv-123",
            detected_version="Bisq 2",
            version_confidence=0.9,
            topics=["trading", "reputation"],
        )
        summary = manager.get_context_summary("conv-123")
        assert "trading" in summary
        assert "reputation" in summary

    def test_context_summary_with_entities(self, manager):
        manager.update_state(
            "conv-123",
            entities={"trade_id": "12345"},
        )
        summary = manager.get_context_summary("conv-123")
        assert "trade_id" in summary
        assert "12345" in summary

    def test_context_summary_empty_state(self, manager):
        summary = manager.get_context_summary("conv-123")
        assert summary == ""

    def test_context_summary_limits_topics(self, manager):
        # Should only show last 5 topics
        topics = [f"topic{i}" for i in range(10)]
        manager.update_state("conv-123", topics=topics)
        summary = manager.get_context_summary("conv-123")
        # Last 5 topics should be present
        assert "topic9" in summary
        assert "topic5" in summary


class TestConversationIdGeneration:
    """Test conversation ID generation."""

    def test_generate_id_from_history(self, manager):
        history = [{"role": "user", "content": "Hello there"}]
        conv_id = manager.generate_conversation_id(history)
        assert len(conv_id) == 16  # SHA-256 truncated to 16 hex chars
        assert conv_id.isalnum()

    def test_same_history_same_id(self, manager):
        history = [{"role": "user", "content": "Hello there"}]
        id1 = manager.generate_conversation_id(history)
        id2 = manager.generate_conversation_id(history)
        assert id1 == id2

    def test_different_history_different_id(self, manager):
        history1 = [{"role": "user", "content": "Hello"}]
        history2 = [{"role": "user", "content": "Hi there"}]
        id1 = manager.generate_conversation_id(history1)
        id2 = manager.generate_conversation_id(history2)
        assert id1 != id2

    def test_empty_history_unique_id(self, manager):
        conv_id = manager.generate_conversation_id([])
        # Empty histories should generate unique IDs based on timestamp + random
        assert len(conv_id) == 16  # SHA-256 truncated to 16 hex chars

        # Verify two empty history calls generate different IDs
        conv_id2 = manager.generate_conversation_id([])
        assert conv_id != conv_id2, "Empty history should generate unique IDs each time"


class TestStateCleanup:
    """Test stale state cleanup."""

    def test_cleanup_old_states(self, manager):
        # Create a state
        state = manager.get_or_create_state("conv-old")
        # Manually set old timestamp
        state.last_updated = datetime.now() - timedelta(hours=25)

        # Create a fresh state
        manager.update_state("conv-new", topics=["test"])

        # Cleanup states older than 24 hours
        manager.cleanup_old_states(max_age_hours=24)

        # Old state should be removed
        assert "conv-old" not in manager._states
        # New state should remain
        assert "conv-new" in manager._states

    def test_cleanup_keeps_recent_states(self, manager):
        manager.update_state("conv-1", topics=["test1"])
        manager.update_state("conv-2", topics=["test2"])

        manager.cleanup_old_states(max_age_hours=24)

        # Both recent states should remain
        assert "conv-1" in manager._states
        assert "conv-2" in manager._states


class TestTimestampUpdates:
    """Test that timestamps are updated correctly."""

    def test_last_updated_on_creation(self, manager):
        before = datetime.now()
        manager.update_state("conv-123", topics=["test"])
        after = datetime.now()

        state = manager.get_or_create_state("conv-123")
        assert before <= state.last_updated <= after

    def test_last_updated_on_update(self, manager):
        manager.update_state("conv-123", topics=["test1"])
        first_update = manager.get_or_create_state("conv-123").last_updated

        # Small delay to ensure timestamp difference
        import time

        time.sleep(0.01)

        manager.update_state("conv-123", topics=["test2"])
        second_update = manager.get_or_create_state("conv-123").last_updated

        assert second_update >= first_update
