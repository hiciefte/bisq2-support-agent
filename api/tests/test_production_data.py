"""
Test conversation processor with production data to verify bug fix.
"""

import pytest
from pathlib import Path
from app.services.faq.conversation_processor import ConversationProcessor


class TestProductionDataProcessing:
    """Test conversation grouping with real production data."""

    @pytest.fixture
    def production_json(self):
        """Path to production JSON export."""
        json_path = Path(__file__).parent.parent / "data" / "support_chat_export.json"
        if not json_path.exists():
            pytest.skip(f"Production JSON not found at {json_path}")
        return json_path

    def test_production_data_creates_multiple_conversations(self, production_json):
        """
        Verify that production data creates multiple conversations, not just one.

        This test validates the bug fix:
        - OLD BUG: All messages grouped into ONE conversation
        - EXPECTED: Multiple independent Q&A conversations
        """
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin", "toruk-makto"]
        )
        processor.load_messages_from_file(production_json)

        # Should have loaded messages
        assert len(processor.messages) > 0, "Should load messages from production JSON"

        # Group conversations
        conversations = processor.group_conversations()

        # Should create multiple conversations, not just one
        assert len(conversations) > 1, (
            f"Expected multiple conversations from production data, got {len(conversations)}. "
            f"This suggests the conversation grouping bug may not be fixed."
        )

        # Each conversation should be a valid Q&A pair
        for conv in conversations:
            assert len(conv["messages"]) >= 2, (
                f"Conversation {conv['id']} has only {len(conv['messages'])} messages. "
                f"Expected at least 2 (user question + support answer)."
            )

            # Verify each conversation has both user and support messages
            has_user = any(not msg["is_support"] for msg in conv["messages"])
            has_support = any(msg["is_support"] for msg in conv["messages"])
            assert has_user and has_support, (
                f"Conversation {conv['id']} missing user or support messages. "
                f"has_user={has_user}, has_support={has_support}"
            )

    def test_support_message_detection_with_production_data(self, production_json):
        """
        Verify support vs user message detection works correctly.

        Support messages: Have a citation (they're answering someone)
        User messages: No citation (they're asking a question)
        """
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin", "toruk-makto"]
        )
        processor.load_messages_from_file(production_json)

        # Should have both support and user messages
        support_msgs = [m for m in processor.messages.values() if m["is_support"]]
        user_msgs = [m for m in processor.messages.values() if not m["is_support"]]

        assert len(support_msgs) > 0, "Should have support messages"
        assert len(user_msgs) > 0, "Should have user messages"

        # All support messages should have a referenced_msg_id
        for msg in support_msgs:
            assert msg["referenced_msg_id"] is not None, (
                f"Support message {msg['msg_id']} has no referenced_msg_id. "
                f"Support messages should always reference the user's question."
            )

        print(f"\nProduction data statistics:")
        print(f"  Total messages: {len(processor.messages)}")
        print(f"  Support messages (with references): {len(support_msgs)}")
        print(f"  User messages (no references): {len(user_msgs)}")
        print(f"  Conversations generated: {len(processor.group_conversations())}")
