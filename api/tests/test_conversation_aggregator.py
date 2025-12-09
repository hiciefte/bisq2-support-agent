"""Tests for ConversationAggregator (Full LLM Solution Phase 1.2).

TDD Approach: Tests written first, then implementation.
Phase 1.2: Build conversation aggregation from Matrix messages with reply/thread metadata.
"""

import pytest
from datetime import datetime, timezone
from typing import List, Dict, Any


@pytest.fixture
def sample_messages() -> List[Dict[str, Any]]:
    """Sample Matrix messages with reply and thread metadata."""
    return [
        {
            "event_id": "$msg1",
            "sender": "@user1:matrix.org",
            "body": "How do I install Bisq 2?",
            "timestamp": 1700000000000,
            "reply_to": None,
            "thread_id": None,
        },
        {
            "event_id": "$msg2",
            "sender": "@support:matrix.org",
            "body": "You can download it from bisq.network",
            "timestamp": 1700000060000,
            "reply_to": "$msg1",
            "thread_id": None,
        },
        {
            "event_id": "$msg3",
            "sender": "@user1:matrix.org",
            "body": "Thanks! Does it support Bitcoin?",
            "timestamp": 1700000120000,
            "reply_to": "$msg2",
            "thread_id": None,
        },
        {
            "event_id": "$msg4",
            "sender": "@user2:matrix.org",
            "body": "What's the fee structure?",
            "timestamp": 1700000180000,
            "reply_to": None,
            "thread_id": None,
        },
        {
            "event_id": "$msg5",
            "sender": "@support:matrix.org",
            "body": "Fees are 0.1% for trades",
            "timestamp": 1700000240000,
            "reply_to": "$msg4",
            "thread_id": None,
        },
    ]


@pytest.fixture
def threaded_messages() -> List[Dict[str, Any]]:
    """Sample messages with thread structure."""
    return [
        {
            "event_id": "$thread1",
            "sender": "@user1:matrix.org",
            "body": "Starting a discussion about wallets",
            "timestamp": 1700000000000,
            "reply_to": None,
            "thread_id": None,
        },
        {
            "event_id": "$thread1_reply1",
            "sender": "@user2:matrix.org",
            "body": "I prefer hardware wallets",
            "timestamp": 1700000060000,
            "reply_to": "$thread1",
            "thread_id": "$thread1",
        },
        {
            "event_id": "$thread1_reply2",
            "sender": "@user3:matrix.org",
            "body": "Software wallets are more convenient",
            "timestamp": 1700000120000,
            "reply_to": "$thread1",
            "thread_id": "$thread1",
        },
    ]


class TestConversationAggregator:
    """Test ConversationAggregator for building conversations from messages."""

    def test_single_message_creates_single_conversation(self, sample_messages):
        """Should create one conversation from a single message."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        aggregator = ConversationAggregator()
        conversations = aggregator.aggregate([sample_messages[0]])

        assert len(conversations) == 1
        assert len(conversations[0].messages) == 1
        assert conversations[0].messages[0]["event_id"] == "$msg1"

    def test_reply_chain_aggregates_into_single_conversation(self, sample_messages):
        """Should aggregate reply chain into one conversation."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        aggregator = ConversationAggregator()
        # First 3 messages form a reply chain
        conversations = aggregator.aggregate(sample_messages[:3])

        assert len(conversations) == 1
        assert len(conversations[0].messages) == 3
        assert conversations[0].root_message_id == "$msg1"

    def test_separate_conversations_for_different_chains(self, sample_messages):
        """Should create separate conversations for different reply chains."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        aggregator = ConversationAggregator()
        # All 5 messages: 2 separate reply chains
        conversations = aggregator.aggregate(sample_messages)

        assert len(conversations) == 2
        # First conversation: $msg1 -> $msg2 -> $msg3
        assert conversations[0].root_message_id == "$msg1"
        assert len(conversations[0].messages) == 3
        # Second conversation: $msg4 -> $msg5
        assert conversations[1].root_message_id == "$msg4"
        assert len(conversations[1].messages) == 2

    def test_threaded_messages_aggregate_by_thread_id(self, threaded_messages):
        """Should aggregate messages with same thread_id."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        aggregator = ConversationAggregator()
        conversations = aggregator.aggregate(threaded_messages)

        assert len(conversations) == 1
        assert len(conversations[0].messages) == 3
        assert conversations[0].root_message_id == "$thread1"

    def test_conversation_chronological_order(self, sample_messages):
        """Should order messages chronologically within conversations."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        aggregator = ConversationAggregator()
        # Pass messages in reverse order
        conversations = aggregator.aggregate(list(reversed(sample_messages[:3])))

        # Should still be chronological
        timestamps = [msg["timestamp"] for msg in conversations[0].messages]
        assert timestamps == sorted(timestamps)

    def test_conversation_metadata_extraction(self, sample_messages):
        """Should extract metadata from conversation."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        aggregator = ConversationAggregator()
        conversations = aggregator.aggregate(sample_messages[:3])

        conv = conversations[0]
        assert conv.root_message_id == "$msg1"
        assert conv.participant_count == 2  # user1 and support
        assert conv.message_count == 3
        assert conv.start_timestamp == 1700000000000
        assert conv.end_timestamp == 1700000120000

    def test_empty_message_list_returns_empty_conversations(self):
        """Should handle empty message list gracefully."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        aggregator = ConversationAggregator()
        conversations = aggregator.aggregate([])

        assert len(conversations) == 0

    def test_orphaned_reply_creates_separate_conversation(self):
        """Should handle reply without parent as separate conversation."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        orphaned_message = {
            "event_id": "$orphan",
            "sender": "@user:matrix.org",
            "body": "This is a reply",
            "timestamp": 1700000000000,
            "reply_to": "$nonexistent",  # Parent doesn't exist
            "thread_id": None,
        }

        aggregator = ConversationAggregator()
        conversations = aggregator.aggregate([orphaned_message])

        # Should create conversation for orphaned message
        assert len(conversations) == 1
        assert conversations[0].root_message_id == "$orphan"

    def test_long_reply_chain_preserves_order(self):
        """Should handle long reply chains with correct ordering."""
        from app.services.llm_extraction.conversation_aggregator import (
            ConversationAggregator,
        )

        # Create a chain of 10 replies
        messages = []
        for i in range(10):
            msg = {
                "event_id": f"$msg{i}",
                "sender": f"@user{i % 2}:matrix.org",
                "body": f"Message {i}",
                "timestamp": 1700000000000 + (i * 60000),
                "reply_to": f"$msg{i-1}" if i > 0 else None,
                "thread_id": None,
            }
            messages.append(msg)

        aggregator = ConversationAggregator()
        conversations = aggregator.aggregate(messages)

        assert len(conversations) == 1
        assert len(conversations[0].messages) == 10
        # Verify chronological order
        for i in range(len(conversations[0].messages)):
            assert conversations[0].messages[i]["event_id"] == f"$msg{i}"
