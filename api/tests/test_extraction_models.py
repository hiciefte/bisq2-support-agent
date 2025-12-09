"""Tests for Pydantic models used in LLM question extraction (Phase 1.3).

TDD Approach: Tests written first, then implementation.
Phase 1.3: Create validated data models for LLM extraction I/O.
"""

import pytest
from pydantic import ValidationError


class TestMessageInput:
    """Test MessageInput model for individual messages."""

    def test_valid_message_input(self):
        """Should accept valid message data."""
        from app.services.llm_extraction.models import MessageInput

        msg = MessageInput(
            event_id="$msg1",
            sender="@user:matrix.org",
            body="How do I install Bisq 2?",
            timestamp=1700000000000,
        )

        assert msg.event_id == "$msg1"
        assert msg.sender == "@user:matrix.org"
        assert msg.body == "How do I install Bisq 2?"
        assert msg.timestamp == 1700000000000

    def test_message_body_length_validation(self):
        """Should enforce max body length."""
        from app.services.llm_extraction.models import MessageInput

        with pytest.raises(ValidationError, match="at most 5000 characters"):
            MessageInput(
                event_id="$msg1",
                sender="@user:matrix.org",
                body="a" * 5001,  # Exceeds limit
                timestamp=1700000000000,
            )

    def test_message_min_length_validation(self):
        """Should enforce min body length."""
        from app.services.llm_extraction.models import MessageInput

        with pytest.raises(ValidationError, match="at least 1 character"):
            MessageInput(
                event_id="$msg1",
                sender="@user:matrix.org",
                body="",  # Too short
                timestamp=1700000000000,
            )

    def test_unicode_normalization(self):
        """Should normalize Unicode to canonical form (NFKC)."""
        from app.services.llm_extraction.models import MessageInput

        msg = MessageInput(
            event_id="$msg1",
            sender="@user:matrix.org",
            body="café",  # Using composed form
            timestamp=1700000000000,
        )

        # Should be normalized
        assert msg.body == "café"


class TestConversationInput:
    """Test ConversationInput model for extraction requests."""

    def test_valid_conversation_input(self):
        """Should accept valid conversation data."""
        from app.services.llm_extraction.models import (
            ConversationInput,
            MessageInput,
        )

        messages = [
            MessageInput(
                event_id="$msg1",
                sender="@user:matrix.org",
                body="How do I install Bisq 2?",
                timestamp=1700000000000,
            ),
            MessageInput(
                event_id="$msg2",
                sender="@support:matrix.org",
                body="You can download it from bisq.network",
                timestamp=1700000060000,
            ),
        ]

        conv = ConversationInput(
            conversation_id="conv_1", messages=messages, room_id="!room:matrix.org"
        )

        assert conv.conversation_id == "conv_1"
        assert len(conv.messages) == 2
        assert conv.room_id == "!room:matrix.org"

    def test_conversation_max_messages(self):
        """Should enforce max messages limit."""
        from app.services.llm_extraction.models import (
            ConversationInput,
            MessageInput,
        )

        # Create 101 messages (exceeds limit of 100)
        messages = [
            MessageInput(
                event_id=f"$msg{i}",
                sender="@user:matrix.org",
                body=f"Message {i}",
                timestamp=1700000000000 + i,
            )
            for i in range(101)
        ]

        with pytest.raises(ValidationError, match="at most 100 items"):
            ConversationInput(
                conversation_id="conv_1",
                messages=messages,
                room_id="!room:matrix.org",
            )

    def test_conversation_min_messages(self):
        """Should require at least one message."""
        from app.services.llm_extraction.models import ConversationInput

        with pytest.raises(ValidationError, match="at least 1 item"):
            ConversationInput(
                conversation_id="conv_1", messages=[], room_id="!room:matrix.org"
            )


class TestExtractedQuestion:
    """Test ExtractedQuestion model for LLM extraction output."""

    def test_valid_extracted_question(self):
        """Should accept valid extracted question."""
        from app.services.llm_extraction.models import ExtractedQuestion

        question = ExtractedQuestion(
            message_id="$msg1",
            question_text="How do I install Bisq 2?",
            question_type="initial_question",
            confidence=0.95,
        )

        assert question.message_id == "$msg1"
        assert question.question_text == "How do I install Bisq 2?"
        assert question.question_type == "initial_question"
        assert question.confidence == 0.95

    def test_question_type_validation(self):
        """Should only accept valid question types."""
        from app.services.llm_extraction.models import ExtractedQuestion

        # Valid types
        valid_types = [
            "initial_question",
            "follow_up",
            "staff_question",
            "not_question",
        ]
        for qtype in valid_types:
            question = ExtractedQuestion(
                message_id="$msg1",
                question_text="Test question",
                question_type=qtype,
                confidence=0.8,
            )
            assert question.question_type == qtype

        # Invalid type
        with pytest.raises(ValidationError):
            ExtractedQuestion(
                message_id="$msg1",
                question_text="Test question",
                question_type="invalid_type",
                confidence=0.8,
            )

    def test_confidence_range_validation(self):
        """Should enforce confidence range (0.0-1.0)."""
        from app.services.llm_extraction.models import ExtractedQuestion

        # Valid confidence values
        for conf in [0.0, 0.5, 1.0]:
            question = ExtractedQuestion(
                message_id="$msg1",
                question_text="Test",
                question_type="initial_question",
                confidence=conf,
            )
            assert question.confidence == conf

        # Invalid confidence (too high)
        with pytest.raises(ValidationError):
            ExtractedQuestion(
                message_id="$msg1",
                question_text="Test",
                question_type="initial_question",
                confidence=1.5,
            )

        # Invalid confidence (negative)
        with pytest.raises(ValidationError):
            ExtractedQuestion(
                message_id="$msg1",
                question_text="Test",
                question_type="initial_question",
                confidence=-0.1,
            )


class TestExtractionResult:
    """Test ExtractionResult model for batch extraction output."""

    def test_valid_extraction_result(self):
        """Should accept valid extraction result."""
        from app.services.llm_extraction.models import (
            ExtractedQuestion,
            ExtractionResult,
        )

        questions = [
            ExtractedQuestion(
                message_id="$msg1",
                question_text="How do I install Bisq 2?",
                question_type="initial_question",
                confidence=0.95,
            ),
            ExtractedQuestion(
                message_id="$msg3",
                question_text="Does it support Bitcoin?",
                question_type="follow_up",
                confidence=0.85,
            ),
        ]

        result = ExtractionResult(
            conversation_id="conv_1",
            questions=questions,
            total_messages=5,
            processing_time_ms=250,
        )

        assert result.conversation_id == "conv_1"
        assert len(result.questions) == 2
        assert result.total_messages == 5
        assert result.processing_time_ms == 250

    def test_empty_questions_allowed(self):
        """Should allow empty questions list (no questions found)."""
        from app.services.llm_extraction.models import ExtractionResult

        result = ExtractionResult(
            conversation_id="conv_1",
            questions=[],
            total_messages=3,
            processing_time_ms=150,
        )

        assert len(result.questions) == 0

    def test_processing_time_must_be_non_negative(self):
        """Should enforce non-negative processing time."""
        from app.services.llm_extraction.models import ExtractionResult

        # Zero is allowed (very fast processing)
        result = ExtractionResult(
            conversation_id="conv_1",
            questions=[],
            total_messages=3,
            processing_time_ms=0,
        )
        assert result.processing_time_ms == 0

        # Negative not allowed
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            ExtractionResult(
                conversation_id="conv_1",
                questions=[],
                total_messages=3,
                processing_time_ms=-100,
            )
