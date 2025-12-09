"""Tests for Extraction Prompt Manager (Phase 1.4).

TDD Approach: Tests written first, then implementation.
Phase 1.4: Build prompt manager for LLM question extraction.
"""

import pytest
from typing import List
from app.services.llm_extraction.models import MessageInput, ConversationInput


@pytest.fixture
def sample_conversation() -> ConversationInput:
    """Sample conversation for testing."""
    messages = [
        MessageInput(
            event_id="$msg1",
            sender="@user1:matrix.org",
            body="How do I install Bisq 2?",
            timestamp=1700000000000,
        ),
        MessageInput(
            event_id="$msg2",
            sender="@support:matrix.org",
            body="You can download it from bisq.network",
            timestamp=1700000060000,
        ),
        MessageInput(
            event_id="$msg3",
            sender="@user1:matrix.org",
            body="Thanks! Does it support Bitcoin?",
            timestamp=1700000120000,
        ),
    ]

    return ConversationInput(
        conversation_id="conv_1", messages=messages, room_id="!room:matrix.org"
    )


class TestExtractionPromptManager:
    """Test ExtractionPromptManager for formatting LLM prompts."""

    def test_format_conversation_as_messages(self, sample_conversation):
        """Should format conversation as LangChain messages."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )

        # Configure staff senders
        manager = ExtractionPromptManager(staff_senders=["@support:matrix.org"])
        messages = manager.format_conversation(sample_conversation)

        # Should have system message + conversation messages
        assert len(messages) == 4  # 1 system + 3 conversation messages
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"
        assert messages[3]["role"] == "user"

    def test_system_prompt_contains_instructions(self, sample_conversation):
        """Should include extraction instructions in system prompt."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )

        manager = ExtractionPromptManager()
        messages = manager.format_conversation(sample_conversation)

        system_content = messages[0]["content"]

        # Check for key instruction elements
        assert "identify questions" in system_content.lower()
        assert "initial_question" in system_content
        assert "follow_up" in system_content
        assert "staff_question" in system_content
        assert "JSON" in system_content  # Should specify JSON output format

    def test_conversation_messages_include_metadata(self, sample_conversation):
        """Should include sender and event_id in message content."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )

        manager = ExtractionPromptManager()
        messages = manager.format_conversation(sample_conversation)

        # First user message
        assert "@user1:matrix.org" in messages[1]["content"]
        assert "$msg1" in messages[1]["content"]
        assert "How do I install Bisq 2?" in messages[1]["content"]

    def test_alternating_roles_for_conversation(self, sample_conversation):
        """Should alternate roles based on sender."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )

        # Configure staff senders
        manager = ExtractionPromptManager(staff_senders=["@support:matrix.org"])
        messages = manager.format_conversation(sample_conversation)

        # Skip system message, check conversation messages
        conv_messages = messages[1:]

        # user1 -> user, support -> assistant, user1 -> user
        assert conv_messages[0]["role"] == "user"
        assert conv_messages[1]["role"] == "assistant"
        assert conv_messages[2]["role"] == "user"

    def test_json_output_schema_in_prompt(self, sample_conversation):
        """Should include JSON schema in system prompt."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )

        manager = ExtractionPromptManager()
        messages = manager.format_conversation(sample_conversation)

        system_content = messages[0]["content"]

        # Should specify output format
        assert "message_id" in system_content
        assert "question_text" in system_content
        assert "question_type" in system_content
        assert "confidence" in system_content

    def test_truncation_for_long_conversations(self):
        """Should truncate conversations exceeding max tokens."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )

        # Create very long conversation
        long_messages = [
            MessageInput(
                event_id=f"$msg{i}",
                sender="@user:matrix.org",
                body="This is a very long message body " * 100,  # ~700 chars each
                timestamp=1700000000000 + i,
            )
            for i in range(50)  # 50 messages
        ]

        long_conversation = ConversationInput(
            conversation_id="conv_long",
            messages=long_messages,
            room_id="!room:matrix.org",
        )

        manager = ExtractionPromptManager(max_tokens=4000)
        messages = manager.format_conversation(long_conversation)

        # Should be truncated (system + fewer than 50 messages)
        assert len(messages) < 51

    def test_empty_conversation_handling(self):
        """Should handle conversations with minimal messages."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )
        from app.services.llm_extraction.models import ConversationInput, MessageInput

        single_message_conv = ConversationInput(
            conversation_id="conv_single",
            messages=[
                MessageInput(
                    event_id="$msg1",
                    sender="@user:matrix.org",
                    body="Quick question",
                    timestamp=1700000000000,
                )
            ],
            room_id="!room:matrix.org",
        )

        manager = ExtractionPromptManager()
        messages = manager.format_conversation(single_message_conv)

        # Should have system + 1 message
        assert len(messages) == 2

    def test_staff_sender_gets_assistant_role(self):
        """Should assign assistant role to known staff senders."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )
        from app.services.llm_extraction.models import ConversationInput, MessageInput

        # Configure staff senders
        manager = ExtractionPromptManager(
            staff_senders=["@support:matrix.org", "@admin:matrix.org"]
        )

        messages_data = [
            MessageInput(
                event_id="$msg1",
                sender="@user:matrix.org",
                body="Help me",
                timestamp=1700000000000,
            ),
            MessageInput(
                event_id="$msg2",
                sender="@support:matrix.org",  # Staff
                body="Sure, here's how",
                timestamp=1700000060000,
            ),
            MessageInput(
                event_id="$msg3",
                sender="@admin:matrix.org",  # Staff
                body="Additional info",
                timestamp=1700000120000,
            ),
        ]

        conversation = ConversationInput(
            conversation_id="conv_test",
            messages=messages_data,
            room_id="!room:matrix.org",
        )

        formatted = manager.format_conversation(conversation)

        # Skip system message
        conv_messages = formatted[1:]

        assert conv_messages[0]["role"] == "user"  # @user
        assert conv_messages[1]["role"] == "assistant"  # @support (staff)
        assert conv_messages[2]["role"] == "assistant"  # @admin (staff)

    def test_max_tokens_configuration(self, sample_conversation):
        """Should respect max_tokens configuration."""
        from app.services.llm_extraction.prompt_manager import (
            ExtractionPromptManager,
        )

        # Test with different max_tokens settings
        manager_small = ExtractionPromptManager(max_tokens=1000)
        manager_large = ExtractionPromptManager(max_tokens=8000)

        # Both should work with sample conversation
        messages_small = manager_small.format_conversation(sample_conversation)
        messages_large = manager_large.format_conversation(sample_conversation)

        # Should produce valid message lists
        assert len(messages_small) > 0
        assert len(messages_large) > 0
