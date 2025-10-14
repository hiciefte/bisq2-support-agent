"""
Test suite for JSON-based conversation processor.

Tests the new JSON format from bisq2 API /api/v1/support/export endpoint.
"""

import json
import pytest
from datetime import datetime
from pathlib import Path
import tempfile

from app.services.faq.conversation_processor import ConversationProcessor


class TestJSONConversationProcessor:
    """Test suite for JSON-based conversation processing."""

    @pytest.fixture
    def sample_json_export(self):
        """Sample JSON export matching the bisq2 API format."""
        return {
            "exportDate": "2025-10-14T15:30:00Z",
            "exportMetadata": {
                "channelCount": 2,
                "messageCount": 6,
                "dataRetentionDays": 10,
                "timezone": "UTC",
            },
            "messages": [
                {
                    "date": "2025-10-14T12:00:00Z",
                    "dateFormatted": "2025-10-14 12:00:00",
                    "channel": "support",
                    "author": "user123",
                    "authorId": "hash_user123",
                    "message": "How do I reset my password?",
                    "messageId": "msg_001",
                    "wasEdited": False,
                    "citation": None,
                },
                {
                    "date": "2025-10-14T12:05:00Z",
                    "dateFormatted": "2025-10-14 12:05:00",
                    "channel": "support",
                    "author": "suddenwhipvapor",
                    "authorId": "hash_support1",
                    "message": "Click the forgot password link on the login page",
                    "messageId": "msg_002",
                    "wasEdited": False,
                    "citation": {
                        "messageId": "msg_001",
                        "author": "user123",
                        "authorId": "hash_user123",
                        "text": "How do I reset my password?",
                    },
                },
                {
                    "date": "2025-10-14T12:10:00Z",
                    "dateFormatted": "2025-10-14 12:10:00",
                    "channel": "support",
                    "author": "user456",
                    "authorId": "hash_user456",
                    "message": "Can I trade BTC for USD?",
                    "messageId": "msg_003",
                    "wasEdited": False,
                    "citation": None,
                },
                {
                    "date": "2025-10-14T12:15:00Z",
                    "dateFormatted": "2025-10-14 12:15:00",
                    "channel": "support",
                    "author": "strayorigin",
                    "authorId": "hash_support2",
                    "message": "Yes, you can create offers for BTC/USD trading pairs",
                    "messageId": "msg_004",
                    "wasEdited": False,
                    "citation": {
                        "messageId": "msg_003",
                        "author": "user456",
                        "authorId": "hash_user456",
                        "text": "Can I trade BTC for USD?",
                    },
                },
            ],
        }

    @pytest.fixture
    def temp_json_file(self, sample_json_export):
        """Create a temporary JSON file with sample data."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample_json_export, f)
            temp_path = Path(f.name)
        yield temp_path
        temp_path.unlink()  # Clean up after test

    def test_load_messages_from_json_dict(self, sample_json_export):
        """Test loading messages from JSON dict (from API response)."""
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin"]
        )
        processor.load_messages_from_json(sample_json_export)

        messages = processor.get_messages()
        assert len(messages) == 4, f"Expected 4 messages, got {len(messages)}"

        # Verify message structure
        msg = messages["msg_001"]
        assert msg["msg_id"] == "msg_001"
        assert msg["text"] == "How do I reset my password?"
        assert msg["author"] == "user123"
        assert msg["channel"] == "support"
        assert msg["is_support"] is False
        assert msg["referenced_msg_id"] is None

        # Verify support message with citation
        support_msg = messages["msg_002"]
        assert support_msg["msg_id"] == "msg_002"
        assert support_msg["author"] == "suddenwhipvapor"
        assert support_msg["is_support"] is True
        assert support_msg["referenced_msg_id"] == "msg_001"

    def test_load_messages_from_json_file(self, temp_json_file):
        """Test loading messages from JSON file."""
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin"]
        )
        processor.load_messages_from_file(temp_json_file)

        messages = processor.get_messages()
        assert len(messages) == 4, f"Expected 4 messages, got {len(messages)}"

    def test_group_conversations_from_json(self, sample_json_export):
        """Test grouping messages into conversations from JSON data."""
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin"]
        )
        processor.load_messages_from_json(sample_json_export)
        conversations = processor.group_conversations()

        # Should create 2 separate conversations (2 Q&A pairs)
        assert (
            len(conversations) == 2
        ), f"Expected 2 conversations, got {len(conversations)}"

        # Each conversation should have user + support messages
        for conv in conversations:
            assert len(conv["messages"]) >= 2
            user_msgs = [msg for msg in conv["messages"] if not msg["is_support"]]
            support_msgs = [msg for msg in conv["messages"] if msg["is_support"]]
            assert len(user_msgs) >= 1
            assert len(support_msgs) >= 1

    def test_identify_support_agents_from_nicknames(self, sample_json_export):
        """Test that we can identify support agents by their nicknames."""
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin"]
        )
        processor.load_messages_from_json(sample_json_export)

        messages = processor.get_messages()

        # Find support agents
        support_agents = set()
        for msg in messages.values():
            if msg["is_support"]:
                support_agents.add(msg["author"])

        # Should identify support agents by their actual nicknames
        assert "suddenwhipvapor" in support_agents
        assert "strayorigin" in support_agents
        assert "user123" not in support_agents
        assert "user456" not in support_agents

    def test_parse_timestamps_correctly(self, sample_json_export):
        """Test that ISO 8601 timestamps are parsed correctly."""
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin"]
        )
        processor.load_messages_from_json(sample_json_export)

        messages = processor.get_messages()
        msg = messages["msg_001"]

        assert msg["timestamp"] is not None
        assert isinstance(msg["timestamp"], datetime)
        # Verify it's UTC-aware
        assert msg["timestamp"].tzinfo is not None

    def test_handle_empty_json_export(self):
        """Test handling of empty JSON export."""
        empty_export = {
            "exportDate": "2025-10-14T15:30:00Z",
            "exportMetadata": {
                "channelCount": 0,
                "messageCount": 0,
                "dataRetentionDays": 10,
                "timezone": "UTC",
            },
            "messages": [],
        }

        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin"]
        )
        processor.load_messages_from_json(empty_export)

        messages = processor.get_messages()
        assert len(messages) == 0

        conversations = processor.group_conversations()
        assert len(conversations) == 0

    def test_handle_message_without_citation(self, sample_json_export):
        """Test handling of messages without citations."""
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin"]
        )
        processor.load_messages_from_json(sample_json_export)

        messages = processor.get_messages()
        msg = messages["msg_001"]

        assert msg["referenced_msg_id"] is None
        assert msg["is_support"] is False

    def test_conversation_ordering_by_timestamp(self, sample_json_export):
        """Test that messages in conversations are ordered by timestamp."""
        processor = ConversationProcessor(
            support_agent_nicknames=["suddenwhipvapor", "strayorigin"]
        )
        processor.load_messages_from_json(sample_json_export)
        conversations = processor.group_conversations()

        for conv in conversations:
            timestamps = [msg["timestamp"] for msg in conv["messages"]]
            # Verify chronological order
            assert timestamps == sorted(timestamps)
