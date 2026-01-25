"""Tests for substantive answer filter."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from app.services.training.matrix_export_parser import QAPair
from app.services.training.substantive_filter import (
    FilterResult,
    SubstantiveAnswerFilter,
)


class TestSubstantiveAnswerFilter:
    """Test cases for SubstantiveAnswerFilter."""

    @pytest.fixture
    def mock_ai_client(self):
        """Create a mock AI client."""
        return MagicMock()

    @pytest.fixture
    def filter_instance(self, mock_ai_client):
        """Create a filter instance with mocked AI client."""
        return SubstantiveAnswerFilter(mock_ai_client)

    @pytest.fixture
    def sample_qa_pairs(self):
        """Create sample Q&A pairs for testing."""
        now = datetime.now(timezone.utc)
        return [
            QAPair(
                question_event_id="$q1",
                question_text="How do I start a trade?",
                question_sender="@user1:matrix.org",
                question_timestamp=now,
                answer_event_id="$a1",
                answer_text="You can start a trade by selecting an offer from the offerbook and clicking 'Take Offer'.",
                answer_sender="@staff:matrix.org",
                answer_timestamp=now,
            ),
            QAPair(
                question_event_id="$q2",
                question_text="Thanks for the help!",
                question_sender="@user2:matrix.org",
                question_timestamp=now,
                answer_event_id="$a2",
                answer_text="np",
                answer_sender="@staff:matrix.org",
                answer_timestamp=now,
            ),
            QAPair(
                question_event_id="$q3",
                question_text="What is the trade limit?",
                question_sender="@user3:matrix.org",
                question_timestamp=now,
                answer_event_id="$a3",
                answer_text="The trade limit for new accounts is $600 USD equivalent.",
                answer_sender="@staff:matrix.org",
                answer_timestamp=now,
            ),
        ]

    # === Empty Input Tests ===

    @pytest.mark.asyncio
    async def test_filter_empty_input(self, filter_instance):
        """Test filtering with empty input returns empty results."""
        substantive, filtered = await filter_instance.filter_answers([])
        assert substantive == []
        assert filtered == []

    # === Successful Filtering Tests ===

    @pytest.mark.asyncio
    async def test_filter_classifies_correctly(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that filter correctly classifies Q&A pairs."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        [
                            {
                                "answer_index": 0,
                                "classification": "substantive",
                                "confidence": 0.95,
                            },
                            {
                                "answer_index": 1,
                                "classification": "trivial",
                                "confidence": 0.9,
                            },
                            {
                                "answer_index": 2,
                                "classification": "substantive",
                                "confidence": 0.85,
                            },
                        ]
                    )
                )
            )
        ]
        mock_ai_client.chat.completions.create.return_value = mock_response

        substantive, filtered = await filter_instance.filter_answers(sample_qa_pairs)

        # Should have 2 substantive and 1 filtered
        assert len(substantive) == 2
        assert len(filtered) == 1

        # First and third should be substantive
        assert substantive[0].answer_event_id == "$a1"
        assert substantive[1].answer_event_id == "$a3"

        # Second should be filtered as trivial
        assert filtered[0][0].answer_event_id == "$a2"
        assert filtered[0][1] == "trivial"

    @pytest.mark.asyncio
    async def test_filter_handles_off_topic(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that off_topic classification is handled correctly."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        [
                            {
                                "answer_index": 0,
                                "classification": "off_topic",
                                "confidence": 0.8,
                            },
                            {
                                "answer_index": 1,
                                "classification": "trivial",
                                "confidence": 0.9,
                            },
                            {
                                "answer_index": 2,
                                "classification": "substantive",
                                "confidence": 0.95,
                            },
                        ]
                    )
                )
            )
        ]
        mock_ai_client.chat.completions.create.return_value = mock_response

        substantive, filtered = await filter_instance.filter_answers(sample_qa_pairs)

        assert len(substantive) == 1
        assert len(filtered) == 2
        assert filtered[0][1] == "off_topic"
        assert filtered[1][1] == "trivial"

    # === JSON Parsing Tests ===

    @pytest.mark.asyncio
    async def test_filter_handles_markdown_code_block(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that filter handles JSON wrapped in markdown code block."""
        json_content = json.dumps(
            [
                {"answer_index": 0, "classification": "substantive", "confidence": 0.9},
                {"answer_index": 1, "classification": "trivial", "confidence": 0.85},
                {"answer_index": 2, "classification": "substantive", "confidence": 0.9},
            ]
        )
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=f"```json\n{json_content}\n```"))
        ]
        mock_ai_client.chat.completions.create.return_value = mock_response

        substantive, filtered = await filter_instance.filter_answers(sample_qa_pairs)

        assert len(substantive) == 2
        assert len(filtered) == 1

    # === Error Handling Tests ===

    @pytest.mark.asyncio
    async def test_filter_error_keeps_all_as_substantive(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that on error, all pairs are kept as substantive (conservative)."""
        mock_ai_client.chat.completions.create.side_effect = Exception("API Error")

        substantive, filtered = await filter_instance.filter_answers(sample_qa_pairs)

        # All should be kept as substantive
        assert len(substantive) == 3
        assert len(filtered) == 0

    @pytest.mark.asyncio
    async def test_filter_invalid_json_keeps_all(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that invalid JSON response keeps all as substantive."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="not valid json"))]
        mock_ai_client.chat.completions.create.return_value = mock_response

        substantive, filtered = await filter_instance.filter_answers(sample_qa_pairs)

        # All should be kept on JSON parse error
        assert len(substantive) == 3
        assert len(filtered) == 0

    # === Batch Processing Tests ===

    @pytest.mark.asyncio
    async def test_filter_batches_large_input(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that large inputs are processed in batches."""
        # Create 25 pairs (more than default batch_size of 20)
        now = datetime.now(timezone.utc)
        large_input = []
        for i in range(25):
            large_input.append(
                QAPair(
                    question_event_id=f"$q{i}",
                    question_text=f"Question {i}",
                    question_sender="@user:matrix.org",
                    question_timestamp=now,
                    answer_event_id=f"$a{i}",
                    answer_text=f"Substantive answer {i}",
                    answer_sender="@staff:matrix.org",
                    answer_timestamp=now,
                )
            )

        # Mock to return all as substantive
        def create_mock_response(batch_size):
            return MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content=json.dumps(
                                [
                                    {
                                        "answer_index": i,
                                        "classification": "substantive",
                                        "confidence": 0.9,
                                    }
                                    for i in range(batch_size)
                                ]
                            )
                        )
                    )
                ]
            )

        # First call has 20 items, second has 5
        mock_ai_client.chat.completions.create.side_effect = [
            create_mock_response(20),
            create_mock_response(5),
        ]

        substantive, filtered = await filter_instance.filter_answers(
            large_input, batch_size=20
        )

        # Should have made 2 API calls
        assert mock_ai_client.chat.completions.create.call_count == 2
        assert len(substantive) == 25

    @pytest.mark.asyncio
    async def test_filter_custom_batch_size(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that custom batch size is respected."""
        # Mock to return all as substantive
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        [
                            {
                                "answer_index": 0,
                                "classification": "substantive",
                                "confidence": 0.9,
                            }
                        ]
                    )
                )
            )
        ]
        mock_ai_client.chat.completions.create.return_value = mock_response

        # With batch_size=1, should make 3 calls for 3 pairs
        await filter_instance.filter_answers(sample_qa_pairs, batch_size=1)

        assert mock_ai_client.chat.completions.create.call_count == 3

    # === Sync Wrapper Tests ===

    def test_filter_sync_wrapper(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test synchronous wrapper method."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        [
                            {
                                "answer_index": 0,
                                "classification": "substantive",
                                "confidence": 0.9,
                            },
                            {
                                "answer_index": 1,
                                "classification": "trivial",
                                "confidence": 0.8,
                            },
                            {
                                "answer_index": 2,
                                "classification": "substantive",
                                "confidence": 0.9,
                            },
                        ]
                    )
                )
            )
        ]
        mock_ai_client.chat.completions.create.return_value = mock_response

        substantive, filtered = filter_instance.filter_answers_sync(sample_qa_pairs)

        assert len(substantive) == 2
        assert len(filtered) == 1

    # === Edge Cases ===

    @pytest.mark.asyncio
    async def test_filter_handles_missing_index(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that missing answer_index defaults to 0."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        [
                            # Missing answer_index, should default to 0
                            {"classification": "substantive", "confidence": 0.9},
                        ]
                    )
                )
            )
        ]
        mock_ai_client.chat.completions.create.return_value = mock_response

        substantive, filtered = await filter_instance.filter_answers(sample_qa_pairs)

        # Only first pair should be classified (index 0)
        assert len(substantive) == 1
        assert substantive[0].answer_event_id == "$a1"

    @pytest.mark.asyncio
    async def test_filter_handles_out_of_range_index(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that out-of-range indices are safely ignored."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        [
                            {
                                "answer_index": 0,
                                "classification": "substantive",
                                "confidence": 0.9,
                            },
                            {
                                "answer_index": 100,
                                "classification": "substantive",
                                "confidence": 0.9,
                            },  # Out of range
                        ]
                    )
                )
            )
        ]
        mock_ai_client.chat.completions.create.return_value = mock_response

        substantive, filtered = await filter_instance.filter_answers(sample_qa_pairs)

        # Only valid index should be processed
        assert len(substantive) == 1

    @pytest.mark.asyncio
    async def test_filter_handles_empty_response(
        self, filter_instance, mock_ai_client, sample_qa_pairs
    ):
        """Test that empty/null response content is handled."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_ai_client.chat.completions.create.return_value = mock_response

        substantive, filtered = await filter_instance.filter_answers(sample_qa_pairs)

        # Empty response parses as empty array, no pairs classified
        assert len(substantive) == 0
        assert len(filtered) == 0


class TestFilterResult:
    """Test cases for FilterResult dataclass."""

    def test_filter_result_creation(self):
        """Test FilterResult dataclass creation."""
        result = FilterResult(
            answer_index=0, classification="substantive", confidence=0.95
        )
        assert result.answer_index == 0
        assert result.classification == "substantive"
        assert result.confidence == 0.95

    def test_filter_result_classifications(self):
        """Test all valid classification values."""
        for classification in ["substantive", "trivial", "off_topic"]:
            result = FilterResult(
                answer_index=0, classification=classification, confidence=0.8
            )
            assert result.classification == classification
