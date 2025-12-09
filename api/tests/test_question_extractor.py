"""Tests for QuestionExtractor (Phase 1.5 - Final component).

TDD Approach: Tests written first, then implementation.
Phase 1.5: Build main orchestration service for LLM-based question extraction.
"""

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def mock_ai_client():
    """Mock AISuite client for testing."""
    client = Mock()
    # Mock successful LLM response with JSON array
    mock_response = Mock()
    mock_response.choices = [
        Mock(
            message=Mock(
                content=json.dumps(
                    [
                        {
                            "message_id": "$msg1",
                            "question_text": "How do I install Bisq 2?",
                            "question_type": "initial_question",
                            "confidence": 0.95,
                        },
                        {
                            "message_id": "$msg3",
                            "question_text": "Does it support Bitcoin?",
                            "question_type": "follow_up",
                            "confidence": 0.85,
                        },
                    ]
                )
            )
        )
    ]
    client.chat.completions.create = AsyncMock(return_value=mock_response)
    return client


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = Mock()
    settings.LLM_EXTRACTION_MODEL = "openai:gpt-4o-mini"
    settings.LLM_EXTRACTION_TEMPERATURE = 0.0
    settings.LLM_EXTRACTION_MAX_TOKENS = 4000
    settings.LLM_EXTRACTION_BATCH_SIZE = 10
    settings.LLM_EXTRACTION_CACHE_TTL = 3600
    settings.LLM_EXTRACTION_CACHE_SIZE = 100
    return settings


@pytest.fixture
def sample_messages() -> List[Dict[str, Any]]:
    """Sample Matrix messages for testing."""
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
    ]


class TestQuestionExtractor:
    """Test QuestionExtractor orchestration service."""

    @pytest.mark.asyncio
    async def test_extract_questions_from_messages(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Should extract questions from messages successfully."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        extractor = QuestionExtractor(mock_ai_client, mock_settings)
        result = await extractor.extract_questions(
            messages=sample_messages, room_id="!room:matrix.org"
        )

        # Should return ExtractionResult
        assert result.conversation_id is not None
        assert len(result.questions) == 2
        assert result.total_messages == 3
        assert result.processing_time_ms >= 0

        # Verify extracted questions
        assert result.questions[0].message_id == "$msg1"
        assert result.questions[0].question_type == "initial_question"
        assert result.questions[1].message_id == "$msg3"
        assert result.questions[1].question_type == "follow_up"

    @pytest.mark.asyncio
    async def test_uses_conversation_aggregator(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Should use ConversationAggregator to group messages."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        # Add messages from different conversations
        multi_conv_messages = sample_messages + [
            {
                "event_id": "$msg4",
                "sender": "@user2:matrix.org",
                "body": "What's the fee structure?",
                "timestamp": 1700000180000,
                "reply_to": None,
                "thread_id": None,
            }
        ]

        extractor = QuestionExtractor(mock_ai_client, mock_settings)
        await extractor.extract_questions(
            messages=multi_conv_messages, room_id="!room:matrix.org"
        )

        # Should have called LLM for aggregated conversation
        # (implementation will aggregate messages into conversations first)
        assert mock_ai_client.chat.completions.create.called

    @pytest.mark.asyncio
    async def test_uses_prompt_manager(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Should use ExtractionPromptManager to format prompts."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        extractor = QuestionExtractor(
            mock_ai_client, mock_settings, staff_senders=["@support:matrix.org"]
        )
        await extractor.extract_questions(
            messages=sample_messages, room_id="!room:matrix.org"
        )

        # Verify LLM was called with formatted messages
        call_args = mock_ai_client.chat.completions.create.call_args
        messages_sent = call_args[1]["messages"]

        # Should have system prompt + conversation messages
        assert len(messages_sent) > 0
        assert messages_sent[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_validates_llm_response(self, mock_settings, sample_messages):
        """Should validate LLM response using Pydantic models."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        # Create client with malformed JSON response
        bad_client = Mock()
        bad_response = Mock()
        bad_response.choices = [Mock(message=Mock(content="invalid json"))]
        bad_client.chat.completions.create = AsyncMock(return_value=bad_response)

        extractor = QuestionExtractor(bad_client, mock_settings)

        with pytest.raises(Exception):  # Should raise validation error
            await extractor.extract_questions(
                messages=sample_messages, room_id="!room:matrix.org"
            )

    @pytest.mark.asyncio
    async def test_handles_empty_messages(self, mock_ai_client, mock_settings):
        """Should handle empty message list gracefully."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        extractor = QuestionExtractor(mock_ai_client, mock_settings)
        result = await extractor.extract_questions(
            messages=[], room_id="!room:matrix.org"
        )

        # Should return empty result
        assert len(result.questions) == 0
        assert result.total_messages == 0

    @pytest.mark.asyncio
    async def test_caching_enabled(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Should cache extraction results."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        extractor = QuestionExtractor(mock_ai_client, mock_settings)

        # First call
        result1 = await extractor.extract_questions(
            messages=sample_messages, room_id="!room:matrix.org"
        )

        # Second call with same messages
        result2 = await extractor.extract_questions(
            messages=sample_messages, room_id="!room:matrix.org"
        )

        # Should use cache (LLM called only once)
        assert mock_ai_client.chat.completions.create.call_count == 1
        assert result1.questions == result2.questions

    @pytest.mark.asyncio
    async def test_batch_processing(self, mock_ai_client, mock_settings):
        """Should process multiple conversations in batches."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        # Create multiple separate conversations
        batch_messages = []
        for i in range(5):
            batch_messages.append(
                {
                    "event_id": f"$msg{i}",
                    "sender": f"@user{i}:matrix.org",
                    "body": f"Question {i}?",
                    "timestamp": 1700000000000 + (i * 1000),
                    "reply_to": None,
                    "thread_id": None,
                }
            )

        extractor = QuestionExtractor(mock_ai_client, mock_settings)
        await extractor.extract_questions(
            messages=batch_messages, room_id="!room:matrix.org"
        )

        # Should have processed conversations
        assert mock_ai_client.chat.completions.create.called

    @pytest.mark.asyncio
    async def test_error_handling_llm_failure(self, mock_settings, sample_messages):
        """Should handle LLM API failures gracefully."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        # Create client that raises exception
        failing_client = Mock()
        failing_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )

        extractor = QuestionExtractor(failing_client, mock_settings)

        with pytest.raises(Exception, match="API error"):
            await extractor.extract_questions(
                messages=sample_messages, room_id="!room:matrix.org"
            )

    @pytest.mark.asyncio
    async def test_processing_time_tracking(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Should track processing time accurately."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        extractor = QuestionExtractor(mock_ai_client, mock_settings)
        result = await extractor.extract_questions(
            messages=sample_messages, room_id="!room:matrix.org"
        )

        # Should have non-negative processing time
        assert result.processing_time_ms >= 0
        assert result.processing_time_ms < 10000  # Reasonable upper bound

    @pytest.mark.asyncio
    async def test_staff_sender_configuration(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Should respect staff sender configuration."""
        from app.services.llm_extraction.question_extractor import QuestionExtractor

        # Configure staff senders
        extractor = QuestionExtractor(
            mock_ai_client,
            mock_settings,
            staff_senders=["@support:matrix.org", "@admin:matrix.org"],
        )

        await extractor.extract_questions(
            messages=sample_messages, room_id="!room:matrix.org"
        )

        # Verify staff senders were passed to prompt manager
        call_args = mock_ai_client.chat.completions.create.call_args
        messages_sent = call_args[1]["messages"]

        # Check that support message has assistant role
        support_msg = next(
            m for m in messages_sent if "@support:matrix.org" in m["content"]
        )
        assert support_msg["role"] == "assistant"
