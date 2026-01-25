"""
TDD Tests for UnifiedFAQExtractor.

This test suite follows RED-GREEN-REFACTOR cycle for implementing
a simplified FAQ extraction approach that uses a single LLM call
to extract Q&A pairs from chat messages.

UnifiedFAQExtractor extracts FAQ Q&A PAIRS (question + staff answer).

The extractor should:
1. Accept raw messages + staff identifiers
2. Use single LLM call to extract FAQ Q&A pairs
3. Handle corrections (use final/corrected answer)
4. Let LLM handle conversation grouping (topic-based)
5. Return structured FAQ candidates ready for pipeline
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import will fail until implementation exists - that's the RED phase
try:
    from app.services.training.unified_faq_extractor import (
        ExtractedFAQ,
        FAQExtractionResult,
        UnifiedFAQExtractor,
    )

    IMPLEMENTATION_EXISTS = True
except ImportError:
    IMPLEMENTATION_EXISTS = False
    UnifiedFAQExtractor = None
    ExtractedFAQ = None
    FAQExtractionResult = None


# Skip all tests if implementation doesn't exist yet (RED phase)
pytestmark = pytest.mark.skipif(
    not IMPLEMENTATION_EXISTS,
    reason="UnifiedFAQExtractor not yet implemented (RED phase)",
)


# =============================================================================
# Test Data Fixtures
# =============================================================================


@pytest.fixture
def staff_identifiers() -> List[str]:
    """Staff identifiers for testing."""
    return ["suddenwhipvapor", "strayorigin", "mwithm"]


@pytest.fixture
def simple_qa_messages() -> List[Dict[str, Any]]:
    """Simple Q&A exchange with citation-based pairing (Bisq 2 format)."""
    return [
        {
            "messageId": "msg_q1",
            "message": "How do I start trading on Bisq Easy?",
            "author": "user123",
            "date": "2026-01-15T10:00:00Z",
            "citation": None,
        },
        {
            "messageId": "msg_a1",
            "message": "Go to Trade > Trade Wizard to start. New users have a $600 limit.",
            "author": "suddenwhipvapor",
            "date": "2026-01-15T10:05:00Z",
            "citation": {
                "author": "user123",
                "text": "How do I start trading on Bisq Easy?",
            },
        },
    ]


@pytest.fixture
def multi_qa_messages() -> List[Dict[str, Any]]:
    """Multiple Q&A pairs from different users."""
    return [
        {
            "messageId": "msg_q1",
            "message": "What is the trade limit for new users?",
            "author": "alice",
            "date": "2026-01-15T10:00:00Z",
            "citation": None,
        },
        {
            "messageId": "msg_q2",
            "message": "Is Bisq Easy available on mobile?",
            "author": "bob",
            "date": "2026-01-15T10:01:00Z",
            "citation": None,
        },
        {
            "messageId": "msg_a1",
            "message": "The trade limit is $600 USD for new users without reputation.",
            "author": "suddenwhipvapor",
            "date": "2026-01-15T10:03:00Z",
            "citation": {
                "author": "alice",
                "text": "What is the trade limit for new users?",
            },
        },
        {
            "messageId": "msg_a2",
            "message": "Currently Bisq Easy is only available on desktop (Linux, macOS, Windows).",
            "author": "mwithm",
            "date": "2026-01-15T10:04:00Z",
            "citation": {
                "author": "bob",
                "text": "Is Bisq Easy available on mobile?",
            },
        },
    ]


@pytest.fixture
def correction_messages() -> List[Dict[str, Any]]:
    """Messages with staff correction - should use final answer."""
    return [
        {
            "messageId": "msg_q1",
            "message": "What payment methods are supported?",
            "author": "user456",
            "date": "2026-01-15T10:00:00Z",
            "citation": None,
        },
        {
            "messageId": "msg_a1",
            "message": "We support bank transfers only.",
            "author": "suddenwhipvapor",
            "date": "2026-01-15T10:02:00Z",
            "citation": {
                "author": "user456",
                "text": "What payment methods are supported?",
            },
        },
        {
            "messageId": "msg_a2",
            "message": "Actually, correction: We support bank transfers, SEPA, and various other methods. Check the Trade Wizard for the full list.",
            "author": "suddenwhipvapor",
            "date": "2026-01-15T10:03:00Z",
            "citation": {
                "author": "user456",
                "text": "What payment methods are supported?",
            },
        },
    ]


@pytest.fixture
def matrix_format_messages() -> List[Dict[str, Any]]:
    """Matrix format messages with m.relates_to for reply tracking."""
    return [
        {
            "event_id": "$evt_q1:matrix.org",
            "sender": "@user123:matrix.org",
            "origin_server_ts": 1705312800000,
            "content": {
                "body": "How does reputation work in Bisq Easy?",
                "msgtype": "m.text",
            },
        },
        {
            "event_id": "$evt_a1:matrix.org",
            "sender": "@suddenwhipvapor:matrix.org",
            "origin_server_ts": 1705312860000,
            "content": {
                "body": "Reputation is built through successful trades. Higher reputation allows higher trade limits.",
                "msgtype": "m.text",
                "m.relates_to": {
                    "m.in_reply_to": {
                        "event_id": "$evt_q1:matrix.org",
                    }
                },
            },
        },
    ]


@pytest.fixture
def mixed_chatter_messages() -> List[Dict[str, Any]]:
    """Messages with non-question chatter that should be filtered."""
    return [
        {
            "messageId": "msg_1",
            "message": "Good morning everyone!",
            "author": "alice",
            "date": "2026-01-15T09:00:00Z",
            "citation": None,
        },
        {
            "messageId": "msg_2",
            "message": "What is the minimum trade amount?",
            "author": "bob",
            "date": "2026-01-15T09:05:00Z",
            "citation": None,
        },
        {
            "messageId": "msg_3",
            "message": "👍",
            "author": "charlie",
            "date": "2026-01-15T09:06:00Z",
            "citation": None,
        },
        {
            "messageId": "msg_4",
            "message": "The minimum trade amount is $10 USD equivalent.",
            "author": "suddenwhipvapor",
            "date": "2026-01-15T09:08:00Z",
            "citation": {
                "author": "bob",
                "text": "What is the minimum trade amount?",
            },
        },
        {
            "messageId": "msg_5",
            "message": "Thanks!",
            "author": "bob",
            "date": "2026-01-15T09:09:00Z",
            "citation": None,
        },
    ]


# =============================================================================
# PHASE 1: Basic Instantiation Tests (RED)
# =============================================================================


class TestExtractorInstantiation:
    """Test basic extractor creation and configuration."""

    def test_extractor_creates_with_aisuite_client(self):
        """Extractor should initialize with AISuite client and settings."""
        mock_client = MagicMock()
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096

        extractor = UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
        )

        assert extractor is not None
        assert extractor.aisuite_client == mock_client
        assert extractor.settings == mock_settings

    def test_extractor_accepts_custom_staff_identifiers(self, staff_identifiers):
        """Extractor should accept custom staff identifiers."""
        mock_client = MagicMock()
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096

        extractor = UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

        assert extractor.staff_identifiers == staff_identifiers

    def test_extractor_has_default_staff_identifiers(self):
        """Extractor should have default staff identifiers if none provided."""
        mock_client = MagicMock()
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096

        extractor = UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
        )

        assert extractor.staff_identifiers is not None
        assert len(extractor.staff_identifiers) > 0


# =============================================================================
# PHASE 2: Simple Q&A Extraction Tests (RED)
# =============================================================================


class TestSimpleQAExtraction:
    """Test extraction of simple Q&A pairs."""

    @pytest.fixture
    def extractor(self, staff_identifiers):
        """Create extractor with mocked AISuite client."""
        mock_client = MagicMock()
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

    @pytest.mark.asyncio
    async def test_extracts_single_qa_pair(self, extractor, simple_qa_messages):
        """Should extract a single Q&A pair from simple conversation."""
        # Mock LLM response
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How do I start trading on Bisq Easy?",
                    "answer_text": "Go to Trade > Trade Wizard to start. New users have a $600 limit.",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.95,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        assert result is not None
        assert isinstance(result, FAQExtractionResult)
        assert len(result.faqs) == 1
        assert result.faqs[0].question_text == "How do I start trading on Bisq Easy?"
        assert "Trade Wizard" in result.faqs[0].answer_text

    @pytest.mark.asyncio
    async def test_extracts_multiple_qa_pairs(self, extractor, multi_qa_messages):
        """Should extract multiple Q&A pairs from conversation."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "What is the trade limit for new users?",
                    "answer_text": "The trade limit is $600 USD for new users without reputation.",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.92,
                },
                {
                    "question_text": "Is Bisq Easy available on mobile?",
                    "answer_text": "Currently Bisq Easy is only available on desktop (Linux, macOS, Windows).",
                    "question_msg_id": "msg_q2",
                    "answer_msg_id": "msg_a2",
                    "confidence": 0.94,
                },
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=multi_qa_messages,
                source="bisq2",
            )

        assert len(result.faqs) == 2
        questions = [faq.question_text for faq in result.faqs]
        assert "What is the trade limit for new users?" in questions
        assert "Is Bisq Easy available on mobile?" in questions

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_qa_pairs(self, extractor):
        """Should return empty result when no Q&A pairs found."""
        messages = [
            {
                "messageId": "msg_1",
                "message": "Hello everyone!",
                "author": "user123",
                "date": "2026-01-15T10:00:00Z",
                "citation": None,
            },
        ]

        mock_llm_response = {"faq_pairs": []}

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(messages=messages, source="bisq2")

        assert result is not None
        assert len(result.faqs) == 0


# =============================================================================
# PHASE 3: Correction Handling Tests (RED)
# =============================================================================


class TestCorrectionHandling:
    """Test that corrections are handled properly - final answer should be used."""

    @pytest.fixture
    def extractor(self, staff_identifiers):
        """Create extractor with mocked LLM."""
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096
        mock_client = MagicMock()

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

    @pytest.mark.asyncio
    async def test_uses_corrected_answer(self, extractor, correction_messages):
        """Should use the final/corrected answer, not the initial one."""
        # LLM should recognize the correction and return only the final answer
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "What payment methods are supported?",
                    "answer_text": "We support bank transfers, SEPA, and various other methods. Check the Trade Wizard for the full list.",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a2",  # The correction message
                    "confidence": 0.90,
                    "has_correction": True,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=correction_messages,
                source="bisq2",
            )

        assert len(result.faqs) == 1
        faq = result.faqs[0]
        # Should use the corrected answer
        assert "bank transfers, SEPA" in faq.answer_text
        # Should NOT use the incorrect initial answer
        assert faq.answer_text != "We support bank transfers only."

    @pytest.mark.asyncio
    async def test_marks_corrected_faqs(self, extractor, correction_messages):
        """Should mark FAQs that had corrections."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "What payment methods are supported?",
                    "answer_text": "Corrected answer here.",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a2",
                    "confidence": 0.90,
                    "has_correction": True,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=correction_messages,
                source="bisq2",
            )

        assert result.faqs[0].has_correction is True


# =============================================================================
# PHASE 4: Multi-Source Support Tests (RED)
# =============================================================================


class TestMultiSourceSupport:
    """Test extraction from different sources (Bisq 2, Matrix)."""

    @pytest.fixture
    def extractor(self):
        """Create extractor with default staff."""
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096

        # Staff identifiers for both formats
        staff_ids = [
            "suddenwhipvapor",
            "@suddenwhipvapor:matrix.org",
        ]
        mock_client = MagicMock()

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_ids,
        )

    @pytest.mark.asyncio
    async def test_extracts_from_bisq2_format(self, extractor, simple_qa_messages):
        """Should handle Bisq 2 message format."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How do I start trading on Bisq Easy?",
                    "answer_text": "Go to Trade > Trade Wizard.",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.95,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        assert result.source == "bisq2"
        assert len(result.faqs) == 1

    @pytest.mark.asyncio
    async def test_extracts_from_matrix_format(self, extractor, matrix_format_messages):
        """Should handle Matrix message format."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How does reputation work in Bisq Easy?",
                    "answer_text": "Reputation is built through successful trades.",
                    "question_msg_id": "$evt_q1:matrix.org",
                    "answer_msg_id": "$evt_a1:matrix.org",
                    "confidence": 0.93,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=matrix_format_messages,
                source="matrix",
            )

        assert result.source == "matrix"
        assert len(result.faqs) == 1


# =============================================================================
# PHASE 5: Chatter Filtering Tests (RED)
# =============================================================================


class TestChatterFiltering:
    """Test that non-Q&A messages are properly filtered."""

    @pytest.fixture
    def extractor(self, staff_identifiers):
        """Create extractor."""
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096
        mock_client = MagicMock()

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

    @pytest.mark.asyncio
    async def test_filters_greetings_and_acknowledgments(
        self, extractor, mixed_chatter_messages
    ):
        """Should only extract actual Q&A, not greetings/thanks."""
        # LLM should identify only the real Q&A pair
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "What is the minimum trade amount?",
                    "answer_text": "The minimum trade amount is $10 USD equivalent.",
                    "question_msg_id": "msg_2",
                    "answer_msg_id": "msg_4",
                    "confidence": 0.92,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=mixed_chatter_messages,
                source="bisq2",
            )

        # Should only have 1 FAQ, not greetings/thanks/emoji
        assert len(result.faqs) == 1
        assert result.faqs[0].question_text == "What is the minimum trade amount?"


# =============================================================================
# PHASE 6: Result Structure Tests (RED)
# =============================================================================


class TestResultStructure:
    """Test the structure of extraction results."""

    @pytest.fixture
    def extractor(self, staff_identifiers):
        """Create extractor."""
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096
        mock_client = MagicMock()

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

    @pytest.mark.asyncio
    async def test_result_contains_metadata(self, extractor, simple_qa_messages):
        """Result should contain extraction metadata."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "Test question",
                    "answer_text": "Test answer",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.90,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        assert result.source == "bisq2"
        assert result.total_messages == len(simple_qa_messages)
        assert result.extracted_count == 1
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_extracted_faq_has_required_fields(
        self, extractor, simple_qa_messages
    ):
        """Each ExtractedFAQ should have all required fields."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "Test question",
                    "answer_text": "Test answer",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.90,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        faq = result.faqs[0]
        assert hasattr(faq, "question_text")
        assert hasattr(faq, "answer_text")
        assert hasattr(faq, "question_msg_id")
        assert hasattr(faq, "answer_msg_id")
        assert hasattr(faq, "confidence")
        assert hasattr(faq, "has_correction")


# =============================================================================
# PHASE 7: Privacy/Anonymization Tests (RED)
# =============================================================================


class TestPrivacyAnonymization:
    """Test that usernames are anonymized before sending to LLM."""

    @pytest.fixture
    def extractor(self, staff_identifiers):
        """Create extractor."""
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096
        mock_client = MagicMock()

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

    @pytest.mark.asyncio
    async def test_anonymizes_usernames_in_llm_call(
        self, extractor, simple_qa_messages
    ):
        """Should anonymize usernames before sending to LLM."""
        captured_prompt = None

        async def capture_prompt(*args, **kwargs):
            nonlocal captured_prompt
            captured_prompt = kwargs.get("messages_text") or args[0]
            return {"faq_pairs": []}

        with patch.object(extractor, "_call_llm", side_effect=capture_prompt):
            await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        # Real usernames should NOT appear in the prompt
        assert captured_prompt is not None
        assert "user123" not in captured_prompt
        assert "suddenwhipvapor" not in captured_prompt
        # Anonymized names should appear instead
        assert "User_" in captured_prompt or "Staff_" in captured_prompt

    @pytest.mark.asyncio
    async def test_preserves_original_usernames_in_result(
        self, extractor, simple_qa_messages
    ):
        """Should preserve original usernames in extraction result metadata."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "Test question",
                    "answer_text": "Test answer",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.90,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        # Original message IDs should be preserved for traceability
        assert result.faqs[0].question_msg_id == "msg_q1"
        assert result.faqs[0].answer_msg_id == "msg_a1"


# =============================================================================
# PHASE 8: Error Handling Tests (RED)
# =============================================================================


class TestErrorHandling:
    """Test error handling and edge cases."""

    @pytest.fixture
    def extractor(self, staff_identifiers):
        """Create extractor."""
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096
        mock_client = MagicMock()

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

    @pytest.mark.asyncio
    async def test_handles_empty_message_list(self, extractor):
        """Should handle empty message list gracefully."""
        result = await extractor.extract_faqs(messages=[], source="bisq2")

        assert result is not None
        assert len(result.faqs) == 0
        assert result.extracted_count == 0

    @pytest.mark.asyncio
    async def test_handles_llm_error_gracefully(self, extractor, simple_qa_messages):
        """Should handle LLM API errors gracefully."""
        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("API Error")

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        # Should return empty result, not raise exception
        assert result is not None
        assert len(result.faqs) == 0
        assert result.error is not None
        assert "API Error" in result.error

    @pytest.mark.asyncio
    async def test_handles_malformed_llm_response(self, extractor, simple_qa_messages):
        """Should handle malformed LLM response gracefully."""
        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            # Return malformed response (missing faq_pairs)
            mock_call.return_value = {"invalid": "response"}

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        assert result is not None
        assert len(result.faqs) == 0


# =============================================================================
# PHASE 9: Integration with Pipeline Tests (RED)
# =============================================================================


class TestPipelineIntegration:
    """Test integration patterns with UnifiedPipelineService."""

    @pytest.fixture
    def extractor(self, staff_identifiers):
        """Create extractor."""
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096
        mock_client = MagicMock()

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

    @pytest.mark.asyncio
    async def test_result_compatible_with_pipeline_input(
        self, extractor, simple_qa_messages
    ):
        """Extracted FAQs should be compatible with pipeline processing."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How do I start trading?",
                    "answer_text": "Go to Trade Wizard.",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.90,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        # Each FAQ should have fields needed for pipeline processing
        for faq in result.faqs:
            # Required for creating FAQ candidate
            assert faq.question_text is not None
            assert faq.answer_text is not None
            # Required for deduplication
            assert faq.question_msg_id is not None
            assert faq.answer_msg_id is not None
            # Required for routing decision
            assert 0.0 <= faq.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_can_convert_to_pipeline_format(self, extractor, simple_qa_messages):
        """Should be able to convert results to pipeline-compatible format."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How do I start trading?",
                    "answer_text": "Go to Trade Wizard.",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.90,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response

            result = await extractor.extract_faqs(
                messages=simple_qa_messages,
                source="bisq2",
            )

        # Should have method to convert to pipeline format
        pipeline_items = result.to_pipeline_format()

        assert len(pipeline_items) == 1
        item = pipeline_items[0]
        assert "question_text" in item
        assert "staff_answer" in item
        assert "source_event_id" in item
        assert "source" in item


# =============================================================================
# PHASE 10: Original Answer Preservation Tests (RED)
# =============================================================================


class TestOriginalAnswerPreservation:
    """Test that original conversational answers are preserved."""

    @pytest.fixture
    def extractor(self, staff_identifiers):
        """Create extractor with mocked AISuite client."""
        mock_client = MagicMock()
        mock_settings = MagicMock()
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        mock_settings.LLM_TEMPERATURE = 0.1
        mock_settings.MAX_TOKENS = 4096

        return UnifiedFAQExtractor(
            aisuite_client=mock_client,
            settings=mock_settings,
            staff_identifiers=staff_identifiers,
        )

    @pytest.fixture
    def simple_messages(self) -> List[Dict[str, Any]]:
        """Simple messages for testing original answer preservation."""
        return [
            {
                "messageId": "msg_q1",
                "message": "How do I backup?",
                "author": "user123",
                "date": "2026-01-15T10:00:00Z",
                "citation": None,
            },
            {
                "messageId": "msg_a1",
                "message": "hey! just go to wallet and click backup",
                "author": "suddenwhipvapor",
                "date": "2026-01-15T10:05:00Z",
                "citation": {
                    "author": "user123",
                    "text": "How do I backup?",
                },
            },
        ]

    @pytest.mark.asyncio
    async def test_extraction_returns_original_answer_text(
        self, extractor, simple_messages
    ):
        """Test that extraction includes original_answer_text field."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How do I backup?",
                    "answer_text": "Navigate to Wallet and select Backup.",
                    "original_answer_text": "hey! just go to wallet and click backup",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.9,
                    "has_correction": False,
                    "category": "Wallet",
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            result = await extractor.extract_faqs(
                messages=simple_messages, source="bisq2"
            )

        assert len(result.faqs) == 1
        assert hasattr(result.faqs[0], "original_answer_text")
        assert (
            result.faqs[0].original_answer_text
            == "hey! just go to wallet and click backup"
        )

    @pytest.mark.asyncio
    async def test_pipeline_format_includes_original_staff_answer(
        self, extractor, simple_messages
    ):
        """Test that to_pipeline_format() includes original_staff_answer.

        Note: original_staff_answer uses direct lookup from normalized messages,
        NOT the LLM's original_answer_text copy (which can be incorrect).
        """
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "Test Q",
                    "answer_text": "Transformed answer.",
                    "original_answer_text": "LLM's copy - ignored in favor of direct lookup",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",  # Points to simple_messages[1]
                    "confidence": 0.9,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            result = await extractor.extract_faqs(
                messages=simple_messages, source="bisq2"
            )

        pipeline_data = result.to_pipeline_format()
        assert "original_staff_answer" in pipeline_data[0]
        # Uses direct lookup: simple_messages[1]["message"] = "hey! just go to wallet..."
        assert (
            pipeline_data[0]["original_staff_answer"]
            == "hey! just go to wallet and click backup"
        )

    @pytest.mark.asyncio
    async def test_original_answer_text_is_optional(self, extractor, simple_messages):
        """Test that original_answer_text can be None when not provided."""
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "Test Q",
                    "answer_text": "Test answer",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.9,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            result = await extractor.extract_faqs(
                messages=simple_messages, source="bisq2"
            )

        assert len(result.faqs) == 1
        assert result.faqs[0].original_answer_text is None

    @pytest.mark.asyncio
    async def test_original_staff_answer_uses_direct_lookup_not_llm_copy(
        self, extractor, simple_messages
    ):
        """original_staff_answer should come from direct message lookup, not LLM's copy.

        BUG FIX: The LLM sometimes returns incorrect text for original_answer_text.
        The fix is to use the answer_msg_id to look up the actual message text
        from the normalized messages, bypassing the LLM's potentially wrong copy.
        """
        # LLM returns WRONG text for original_answer_text
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How do I backup?",
                    "answer_text": "Navigate to Wallet and select Backup.",
                    "original_answer_text": "WRONG TEXT FROM LLM - should be ignored",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_a1",  # Points to correct message
                    "confidence": 0.9,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            result = await extractor.extract_faqs(
                messages=simple_messages, source="bisq2"
            )

        pipeline_data = result.to_pipeline_format()

        # Should use direct lookup from normalized messages, NOT LLM's wrong copy
        # The actual message text from simple_messages fixture is:
        # "hey! just go to wallet and click backup"
        assert (
            pipeline_data[0]["original_staff_answer"]
            == "hey! just go to wallet and click backup"
        )
        assert (
            pipeline_data[0]["original_staff_answer"]
            != "WRONG TEXT FROM LLM - should be ignored"
        )

    @pytest.mark.asyncio
    async def test_original_staff_answer_falls_back_to_llm_when_id_not_found(
        self, extractor, simple_messages
    ):
        """When answer_msg_id is not in normalized messages, fall back to LLM's copy.

        This can happen if the LLM returns an invalid message ID. In this case,
        using the LLM's original_answer_text is better than returning None.
        """
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How do I backup?",
                    "answer_text": "Navigate to Wallet and select Backup.",
                    "original_answer_text": "fallback text from LLM",
                    "question_msg_id": "msg_q1",
                    "answer_msg_id": "msg_NONEXISTENT",  # Invalid ID
                    "confidence": 0.9,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            result = await extractor.extract_faqs(
                messages=simple_messages, source="bisq2"
            )

        pipeline_data = result.to_pipeline_format()

        # Should fall back to LLM's copy when direct lookup fails
        assert pipeline_data[0]["original_staff_answer"] == "fallback text from LLM"

    @pytest.mark.asyncio
    async def test_original_user_question_uses_direct_lookup(
        self, extractor, simple_messages
    ):
        """original_user_question should come from direct message lookup.

        This allows admins to see the original user question alongside the
        original staff answer, enabling verification of LLM extraction accuracy.
        """
        mock_llm_response = {
            "faq_pairs": [
                {
                    "question_text": "How do I backup my wallet?",  # Polished
                    "answer_text": "Navigate to Wallet and select Backup.",
                    "original_question_text": "WRONG QUESTION FROM LLM",  # LLM's copy
                    "original_answer_text": "hey! just go to wallet...",
                    "question_msg_id": "msg_q1",  # Points to correct message
                    "answer_msg_id": "msg_a1",
                    "confidence": 0.9,
                }
            ]
        }

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            result = await extractor.extract_faqs(
                messages=simple_messages, source="bisq2"
            )

        pipeline_data = result.to_pipeline_format()

        # Should use direct lookup, not LLM's wrong copy
        # simple_messages[0]["message"] = "How do I backup?"
        assert pipeline_data[0]["original_user_question"] == "How do I backup?"
        assert pipeline_data[0]["original_user_question"] != "WRONG QUESTION FROM LLM"
