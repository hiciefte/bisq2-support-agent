"""Tests for BatchQuestionExtractor - Single-step LLM extraction (TDD).

This replaces the two-step approach (ConversationAggregator + QuestionExtractor)
with a single batch extraction that sends all messages to LLM at once.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from app.core.config import Settings
from app.services.llm_extraction.batch_question_extractor import (
    BatchQuestionExtractor,
    ExtractionResult,
)


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = MagicMock(spec=Settings)
    settings.LLM_EXTRACTION_MODEL = "openai:gpt-4o-mini"
    settings.LLM_EXTRACTION_TEMPERATURE = 0.0
    settings.LLM_EXTRACTION_MAX_TOKENS = 4000
    settings.LLM_EXTRACTION_BATCH_SIZE = 2000
    settings.LLM_EXTRACTION_CACHE_TTL = 3600
    return settings


@pytest.fixture
def mock_ai_client():
    """Mock AISuite client."""
    client = MagicMock()
    return client


@pytest.fixture
def sample_messages() -> List[Dict[str, Any]]:
    """Sample Matrix messages for testing."""
    return [
        {
            "event_id": "$msg1",
            "sender": "@user1:matrix.org",
            "body": "Hi can I have a mediator respond to me? I did a xmr to btc exchange",
            "timestamp": int(
                datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
            ),
        },
        {
            "event_id": "$msg2",
            "sender": "@user1:matrix.org",
            "body": "how do I message them",
            "timestamp": int(
                datetime(2025, 1, 1, 12, 1, 0, tzinfo=timezone.utc).timestamp() * 1000
            ),
        },
        {
            "event_id": "$msg3",
            "sender": "@staff:matrix.org",
            "body": "Can you provide more details about the issue?",
            "timestamp": int(
                datetime(2025, 1, 1, 12, 2, 0, tzinfo=timezone.utc).timestamp() * 1000
            ),
        },
        {
            "event_id": "$msg4",
            "sender": "@user2:matrix.org",
            "body": "Is Bisq 1 still supported?",
            "timestamp": int(
                datetime(2025, 1, 1, 12, 3, 0, tzinfo=timezone.utc).timestamp() * 1000
            ),
        },
    ]


@pytest.fixture
def sample_llm_response() -> str:
    """Sample LLM response with conversations and questions."""
    return json.dumps(
        [
            {
                "conversation_id": "conv_1",
                "related_message_ids": ["$msg1", "$msg2", "$msg3"],
                "conversation_context": "User asking about mediator and messaging",
                "questions": [
                    {
                        "message_id": "$msg1",
                        "question_text": "Hi can I have a mediator respond to me? I did a xmr to btc exchange",
                        "question_type": "initial_question",
                        "confidence": 0.95,
                    },
                    {
                        "message_id": "$msg2",
                        "question_text": "how do I message them",
                        "question_type": "follow_up",
                        "confidence": 0.90,
                    },
                    {
                        "message_id": "$msg3",
                        "question_text": "Can you provide more details about the issue?",
                        "question_type": "staff_question",
                        "confidence": 0.85,
                    },
                ],
            },
            {
                "conversation_id": "conv_2",
                "related_message_ids": ["$msg4"],
                "conversation_context": "User asking about Bisq 1 support",
                "questions": [
                    {
                        "message_id": "$msg4",
                        "question_text": "Is Bisq 1 still supported?",
                        "question_type": "initial_question",
                        "confidence": 0.92,
                    }
                ],
            },
        ]
    )


class TestBatchQuestionExtractor:
    """Test suite for BatchQuestionExtractor."""

    @pytest.mark.asyncio
    async def test_empty_messages(self, mock_ai_client, mock_settings):
        """Test extraction with no messages."""
        extractor = BatchQuestionExtractor(
            ai_client=mock_ai_client,
            settings=mock_settings,
        )

        result = await extractor.extract_questions(
            messages=[], room_id="!test:matrix.org"
        )

        assert isinstance(result, ExtractionResult)
        assert result.total_messages == 0
        assert len(result.questions) == 0
        assert result.conversations == []

    @pytest.mark.asyncio
    async def test_single_batch_extraction(
        self, mock_ai_client, mock_settings, sample_messages, sample_llm_response
    ):
        """Test single batch extraction with all messages."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = sample_llm_response

        with patch("asyncio.to_thread", return_value=mock_response):
            extractor = BatchQuestionExtractor(
                ai_client=mock_ai_client,
                settings=mock_settings,
            )

            result = await extractor.extract_questions(
                messages=sample_messages, room_id="!test:matrix.org"
            )

        # Verify results
        assert result.total_messages == 4
        assert len(result.questions) == 4
        assert len(result.conversations) == 2

        # Verify first conversation
        conv1 = result.conversations[0]
        assert conv1["conversation_id"] == "conv_1"
        assert len(conv1["related_message_ids"]) == 3
        assert len(conv1["questions"]) == 3

        # Verify questions
        q1 = result.questions[0]
        assert q1.message_id == "$msg1"
        assert q1.question_type == "initial_question"
        assert q1.confidence == 0.95

    @pytest.mark.asyncio
    async def test_prompt_formatting(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Test that prompt is formatted correctly with all messages."""
        extractor = BatchQuestionExtractor(
            ai_client=mock_ai_client,
            settings=mock_settings,
        )

        prompt_messages = extractor._format_batch_prompt(sample_messages)

        # Should have system message + user message
        assert len(prompt_messages) == 2
        assert prompt_messages[0]["role"] == "system"
        assert "group related messages" in prompt_messages[0]["content"].lower()
        assert "extract questions" in prompt_messages[0]["content"].lower()

        # Verify all messages are included in user message
        user_content = prompt_messages[1]["content"]
        assert "$msg1" in user_content
        assert "$msg2" in user_content
        assert "$msg3" in user_content
        assert "$msg4" in user_content

    @pytest.mark.asyncio
    async def test_batching_large_message_set(self, mock_ai_client, mock_settings):
        """Test automatic batching for large message sets."""
        # Create 3000 messages (should trigger batching)
        large_message_set = [
            {
                "event_id": f"$msg{i}",
                "sender": "@user:matrix.org",
                "body": f"Question {i}",
                "timestamp": int(
                    datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
                    * 1000
                )
                + i,
            }
            for i in range(3000)
        ]

        mock_settings.LLM_EXTRACTION_BATCH_SIZE = 2000

        # Mock LLM response for batches
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"

        call_count = 0

        async def mock_to_thread(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_response

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            extractor = BatchQuestionExtractor(
                ai_client=mock_ai_client,
                settings=mock_settings,
            )

            result = await extractor.extract_questions(
                messages=large_message_set, room_id="!test:matrix.org"
            )

        # Should have made 2 batches (0-1999, 2000-2999)
        assert call_count == 2
        assert result.total_messages == 3000

    @pytest.mark.asyncio
    async def test_cache_hit(
        self, mock_ai_client, mock_settings, sample_messages, sample_llm_response
    ):
        """Test cache hit for identical message sets."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = sample_llm_response

        api_call_count = 0

        async def mock_to_thread(*args, **kwargs):
            nonlocal api_call_count
            api_call_count += 1
            return mock_response

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            extractor = BatchQuestionExtractor(
                ai_client=mock_ai_client,
                settings=mock_settings,
            )

            # First call - should hit API
            result1 = await extractor.extract_questions(
                messages=sample_messages, room_id="!test:matrix.org"
            )

            # Second call with same messages - should hit cache
            result2 = await extractor.extract_questions(
                messages=sample_messages, room_id="!test:matrix.org"
            )

        # Should only call API once (second call cached)
        assert api_call_count == 1
        assert len(result1.questions) == len(result2.questions)

    @pytest.mark.asyncio
    async def test_json_parse_error_handling(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Test handling of malformed LLM JSON response."""
        # Mock invalid JSON response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "invalid json {"

        with patch("asyncio.to_thread", return_value=mock_response):
            extractor = BatchQuestionExtractor(
                ai_client=mock_ai_client,
                settings=mock_settings,
            )

            result = await extractor.extract_questions(
                messages=sample_messages, room_id="!test:matrix.org"
            )

        # Should return empty result on parse error
        assert result.total_messages == 4
        assert len(result.questions) == 0
        assert len(result.conversations) == 0

    @pytest.mark.asyncio
    async def test_llm_api_error_handling(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Test handling of LLM API errors."""
        with patch("asyncio.to_thread", side_effect=Exception("API Error")):
            extractor = BatchQuestionExtractor(
                ai_client=mock_ai_client,
                settings=mock_settings,
            )

            result = await extractor.extract_questions(
                messages=sample_messages, room_id="!test:matrix.org"
            )

        # Should return empty result on API error
        assert result.total_messages == 4
        assert len(result.questions) == 0
        assert len(result.conversations) == 0

    @pytest.mark.asyncio
    async def test_question_deduplication(
        self, mock_ai_client, mock_settings, sample_messages
    ):
        """Test that duplicate questions are handled correctly."""
        # LLM response with duplicate message_id
        duplicate_response = json.dumps(
            [
                {
                    "conversation_id": "conv_1",
                    "related_message_ids": ["$msg1"],
                    "conversation_context": "Test",
                    "questions": [
                        {
                            "message_id": "$msg1",
                            "question_text": "Question 1",
                            "question_type": "initial_question",
                            "confidence": 0.95,
                        },
                        {
                            "message_id": "$msg1",  # Duplicate
                            "question_text": "Question 1 again",
                            "question_type": "initial_question",
                            "confidence": 0.90,
                        },
                    ],
                }
            ]
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = duplicate_response

        with patch("asyncio.to_thread", return_value=mock_response):
            extractor = BatchQuestionExtractor(
                ai_client=mock_ai_client,
                settings=mock_settings,
            )

            result = await extractor.extract_questions(
                messages=sample_messages, room_id="!test:matrix.org"
            )

        # Should keep only first occurrence
        assert len(result.questions) == 1
        assert result.questions[0].message_id == "$msg1"
