"""
Test for conversation grouping bug where all messages get grouped into one conversation.

This test demonstrates the bug where independent question-answer pairs
get incorrectly grouped into a single conversation.
"""

from pathlib import Path

import pytest
from app.services.faq.conversation_processor import ConversationProcessor


class TestConversationGroupingBug:
    """Test suite for conversation grouping bug fix."""

    @pytest.fixture
    def sample_json_with_independent_conversations(self):
        """Use realistic production-like test data with multiple independent Q&A pairs."""
        # Use sanitized production data from fixtures directory (now in JSON format)
        fixture_path = Path(__file__).parent / "fixtures" / "test_conversations.json"
        return fixture_path

    def test_should_create_multiple_conversations_for_independent_qa_pairs(
        self, sample_json_with_independent_conversations
    ):
        """
        Test that independent question-answer pairs create separate conversations.

        CURRENT BUG: All messages get grouped into ONE conversation
        EXPECTED: Three separate conversations, one for each Q&A pair
        """
        processor = ConversationProcessor(
            support_agent_nicknames=[
                "test_support_1",
                "test_support_2",
                "test_support_3",
            ]
        )
        processor.load_messages_from_file(sample_json_with_independent_conversations)
        conversations = processor.group_conversations()

        # This test will FAIL with current implementation
        # Expected: 5 conversations (5 independent Q&A pairs)
        # Current bug: 0 or 1 conversation
        assert (
            len(conversations) == 5
        ), f"Expected 5 conversations, got {len(conversations)}"

        # Verify each conversation has at least 2 messages (question + answer)
        for conv in conversations:
            assert (
                len(conv["messages"]) >= 2
            ), f"Expected at least 2 messages per conversation, got {len(conv['messages'])}"

        # Verify each conversation has at least one user and one support message
        for conv in conversations:
            user_msgs = [msg for msg in conv["messages"] if not msg["is_support"]]
            support_msgs = [msg for msg in conv["messages"] if msg["is_support"]]
            assert len(user_msgs) >= 1, "Expected at least 1 user message"
            assert len(support_msgs) >= 1, "Expected at least 1 support message"

    def test_should_not_mark_other_support_messages_as_processed(
        self, sample_json_with_independent_conversations
    ):
        """
        Test that processing one support message doesn't prevent others from being processed.

        CURRENT BUG: First support message marks subsequent ones as "processed"
        EXPECTED: Each support message creates its own conversation
        """
        processor = ConversationProcessor(
            support_agent_nicknames=[
                "test_support_1",
                "test_support_2",
                "test_support_3",
            ]
        )
        processor.load_messages_from_file(sample_json_with_independent_conversations)
        conversations = processor.group_conversations()

        # Get all support message IDs
        support_msg_ids = {
            msg_id
            for msg_id, msg in processor.get_messages().items()
            if msg["is_support"] and msg["referenced_msg_id"]
        }

        # Verify all support messages appear in conversations
        conversation_msg_ids = {
            msg["msg_id"] for conv in conversations for msg in conv["messages"]
        }

        missing_support = support_msg_ids - conversation_msg_ids
        assert (
            len(missing_support) == 0
        ), f"Support messages not in conversations: {missing_support}"

    def test_conversation_ids_should_be_unique(
        self, sample_json_with_independent_conversations
    ):
        """
        Test that each conversation has a unique ID.

        CURRENT BUG: May have duplicate conversation IDs or single conversation
        EXPECTED: Each conversation has unique ID based on its support message
        """
        processor = ConversationProcessor(
            support_agent_nicknames=[
                "test_support_1",
                "test_support_2",
                "test_support_3",
            ]
        )
        processor.load_messages_from_file(sample_json_with_independent_conversations)
        conversations = processor.group_conversations()

        conversation_ids = [conv["id"] for conv in conversations]
        unique_ids = set(conversation_ids)

        assert len(conversation_ids) == len(
            unique_ids
        ), f"Duplicate conversation IDs found: {conversation_ids}"
