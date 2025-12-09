"""End-to-end integration tests for message classification system.

This module tests the complete classification flow from raw message input
through AISuite classifier to final classification result, including all
security features (rate limiting, circuit breaker, PII redaction, caching).
"""

import os
from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.core.config import Settings
from app.services.shadow_mode.aisuite_classifier import AISuiteClassifier


@pytest.fixture
def e2e_settings():
    """Settings for E2E testing with real OpenAI API."""
    settings = Settings()
    settings.LLM_CLASSIFICATION_MODEL = "openai:gpt-4o-mini"
    settings.LLM_CLASSIFICATION_TEMPERATURE = 0.2
    settings.LLM_CLASSIFICATION_THRESHOLD = 0.75
    settings.LLM_CLASSIFICATION_RATE_LIMIT_REQUESTS = 10
    settings.LLM_CLASSIFICATION_RATE_LIMIT_WINDOW = 60
    settings.LLM_CLASSIFICATION_CACHE_SIZE = 100
    settings.LLM_CLASSIFICATION_CACHE_TTL_HOURS = 1
    # OPENAI_API_KEY should come from environment
    return settings


@pytest.fixture
def mock_ai_client_for_e2e():
    """Mock AISuite client with realistic multi-turn conversation responses."""
    client = Mock()

    # Response mapping - use exact message matching for reliable E2E tests
    exact_responses = {
        "i can't open my trade": {
            "role": "USER_QUESTION",
            "confidence_breakdown": {
                "keyword_match": 20,
                "syntax_pattern": 20,
                "semantic_clarity": 25,
                "context_alignment": 15,
            },
            "confidence": 0.80,
        },
        "have you tried restarting the application?": {
            "role": "STAFF_RESPONSE",
            "confidence_breakdown": {
                "keyword_match": 22,
                "syntax_pattern": 23,
                "semantic_clarity": 28,
                "context_alignment": 17,
            },
            "confidence": 0.90,
        },
        "yes, still not working": {
            "role": "USER_QUESTION",
            "confidence_breakdown": {
                "keyword_match": 15,
                "syntax_pattern": 18,
                "semantic_clarity": 22,
                "context_alignment": 15,
            },
            "confidence": 0.70,
        },
        "ok thanks": {
            "role": "USER_QUESTION",
            "confidence_breakdown": {
                "keyword_match": 10,
                "syntax_pattern": 8,
                "semantic_clarity": 12,
                "context_alignment": 8,
            },
            "confidence": 0.38,
        },
    }

    # Fallback patterns for partial matches
    pattern_responses = [
        (
            "email is",
            {
                "role": "USER_QUESTION",
                "confidence_breakdown": {
                    "keyword_match": 10,
                    "syntax_pattern": 10,
                    "semantic_clarity": 10,
                    "context_alignment": 10,
                },
                "confidence": 0.40,
            },
        ),
    ]

    def create_mock_response(model=None, messages=None, temperature=None, **kwargs):
        # Extract user message from messages array
        user_message = ""
        if messages:
            for msg in messages:
                if msg.get("role") == "user":
                    user_message = msg.get("content", "")
                    break

        import json

        # Extract just the actual message text after "Message: " in prompt
        if "Message: " in user_message:
            actual_message = user_message.split("Message: ")[-1].strip()
        else:
            actual_message = user_message.strip()

        # Try exact match first
        if actual_message.lower() in exact_responses:
            response_data = exact_responses[actual_message.lower()]
            mock_response = Mock()
            mock_response.choices = [
                Mock(message=Mock(content=json.dumps(response_data)))
            ]
            return mock_response

        # Try pattern match
        for pattern, response_data in pattern_responses:
            if pattern.lower() in actual_message.lower():
                mock_response = Mock()
                mock_response.choices = [
                    Mock(message=Mock(content=json.dumps(response_data)))
                ]
                return mock_response

        # Default response for unmapped messages
        mock_response = Mock()
        mock_response.choices = [
            Mock(
                message=Mock(
                    content='{"role": "USER_QUESTION", "confidence_breakdown": {"keyword_match": 10, "syntax_pattern": 10, "semantic_clarity": 10, "context_alignment": 10}, "confidence": 0.40}'
                )
            )
        ]
        return mock_response

    client.chat.completions.create = AsyncMock(side_effect=create_mock_response)
    return client


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_single_message_classification(e2e_settings, mock_ai_client_for_e2e):
    """E2E: Classify single user question message."""
    classifier = AISuiteClassifier(mock_ai_client_for_e2e, e2e_settings)

    result = await classifier.classify(
        message="i can't open my trade",
        sender_id="user123",
    )

    # Verify classification result
    assert result["role"] == "USER_QUESTION"
    assert result["confidence"] == 0.80
    assert result["confidence_breakdown"]["keyword_match"] == 20
    assert result["confidence_breakdown"]["syntax_pattern"] == 20
    assert result["confidence_breakdown"]["semantic_clarity"] == 25
    assert result["confidence_breakdown"]["context_alignment"] == 15


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_multi_turn_conversation(e2e_settings, mock_ai_client_for_e2e):
    """E2E: Classify multi-turn conversation with context."""
    classifier = AISuiteClassifier(mock_ai_client_for_e2e, e2e_settings)

    # Turn 1: User asks question
    result1 = await classifier.classify(
        message="i can't open my trade",
        sender_id="user123",
    )
    assert result1["role"] == "USER_QUESTION"
    assert result1["confidence"] == 0.80

    # Turn 2: Staff responds
    result2 = await classifier.classify(
        message="have you tried restarting the application?",
        sender_id="staff456",
        prev_messages=["i can't open my trade"],
    )
    assert result2["role"] == "STAFF_RESPONSE"
    assert result2["confidence"] == 0.90

    # Turn 3: User follows up
    result3 = await classifier.classify(
        message="yes, still not working",
        sender_id="user123",
        prev_messages=[
            "i can't open my trade",
            "have you tried restarting the application?",
        ],
    )
    assert result3["role"] == "USER_QUESTION"
    assert result3["confidence"] == 0.70


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_cache_hit_prevents_llm_call(e2e_settings, mock_ai_client_for_e2e):
    """E2E: Verify caching prevents redundant LLM API calls."""
    classifier = AISuiteClassifier(mock_ai_client_for_e2e, e2e_settings)

    # First call - should hit LLM
    result1 = await classifier.classify(
        message="i can't open my trade",
        sender_id="user123",
    )

    # Second call with same message - should hit cache
    result2 = await classifier.classify(
        message="i can't open my trade",
        sender_id="user123",
    )

    # Results should be identical
    assert result1 == result2

    # LLM should only be called once (cache hit on second call)
    assert mock_ai_client_for_e2e.chat.completions.create.call_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_rate_limiting_blocks_spam(e2e_settings, mock_ai_client_for_e2e):
    """E2E: Verify rate limiting prevents abuse."""
    # Lower rate limit for testing
    e2e_settings.LLM_CLASSIFICATION_RATE_LIMIT_REQUESTS = 3
    classifier = AISuiteClassifier(mock_ai_client_for_e2e, e2e_settings)

    # First 3 requests should succeed
    await classifier.classify("message 1", "user123")
    await classifier.classify("message 2", "user123")
    await classifier.classify("message 3", "user123")

    # 4th request should be rate limited
    with pytest.raises(Exception, match="Rate limit exceeded"):
        await classifier.classify("message 4", "user123")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_circuit_breaker_opens_after_failures(
    e2e_settings, mock_ai_client_for_e2e
):
    """E2E: Verify circuit breaker opens after repeated failures."""
    # Make LLM calls fail
    mock_ai_client_for_e2e.chat.completions.create = AsyncMock(
        side_effect=Exception("API error")
    )

    classifier = AISuiteClassifier(mock_ai_client_for_e2e, e2e_settings)

    # Trigger 5 failures to open circuit breaker
    for i in range(5):
        try:
            await classifier.classify(f"message {i}", "user123")
        except:
            pass

    # Circuit should now be open
    with pytest.raises(Exception, match="Circuit breaker"):
        await classifier.classify("test", "user123")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_pii_redaction_before_llm_call(e2e_settings, mock_ai_client_for_e2e):
    """E2E: Verify PII is redacted before sending to LLM."""
    classifier = AISuiteClassifier(mock_ai_client_for_e2e, e2e_settings)

    await classifier.classify(
        message="my email is user@example.com and phone is 555-123-4567",
        sender_id="user123",
    )

    # Check that LLM received redacted message
    call_args = mock_ai_client_for_e2e.chat.completions.create.call_args
    messages = call_args[1]["messages"]
    user_message = messages[-1]["content"]

    # Email should be redacted
    assert "user@example.com" not in user_message
    assert "[EMAIL]" in user_message

    # Phone should be redacted (PIIFilter uses pattern that matches ###-###-####)
    assert "555-123-4567" not in user_message
    assert "[PHONE]" in user_message


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_low_confidence_ambiguous_message(
    e2e_settings, mock_ai_client_for_e2e
):
    """E2E: Verify system correctly identifies low-confidence ambiguous messages."""
    classifier = AISuiteClassifier(mock_ai_client_for_e2e, e2e_settings)

    result = await classifier.classify(
        message="ok thanks",
        sender_id="user123",
    )

    # Should have low confidence (< 0.5)
    assert result["confidence"] < 0.5
    assert result["confidence"] == 0.38

    # Should still return valid classification
    assert result["role"] in ["USER_QUESTION", "STAFF_RESPONSE"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_hierarchical_confidence_validation(
    e2e_settings, mock_ai_client_for_e2e
):
    """E2E: Verify hierarchical confidence dependencies are respected."""
    classifier = AISuiteClassifier(mock_ai_client_for_e2e, e2e_settings)

    result = await classifier.classify(
        message="i can't open my trade",
        sender_id="user123",
    )

    breakdown = result["confidence_breakdown"]

    # Verify hierarchical constraint:
    # If semantic_clarity > 10, then (keyword_match + syntax_pattern) >= 15
    if breakdown["semantic_clarity"] > 10:
        assert (
            breakdown["keyword_match"] + breakdown["syntax_pattern"] >= 15
        ), "Semantic clarity requires keyword+syntax foundation"

    # Verify context alignment constraint:
    # If context_alignment > 5, then semantic_clarity >= 15
    if breakdown["context_alignment"] > 5:
        assert (
            breakdown["semantic_clarity"] >= 15
        ), "Context alignment requires semantic clarity"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"), reason="Requires OPENAI_API_KEY for real API test"
)
async def test_e2e_real_openai_api_call():
    """E2E: Test with real OpenAI API (requires API key)."""
    import aisuite as ai

    settings = Settings()
    client = ai.Client()

    classifier = AISuiteClassifier(client, settings)

    result = await classifier.classify(
        message="i can't open my trade, getting error message",
        sender_id="test_user",
    )

    # Verify real API returns valid classification
    assert result["role"] in ["USER_QUESTION", "STAFF_RESPONSE"]
    assert 0.0 <= result["confidence"] <= 1.0
    assert "confidence_breakdown" in result
    assert sum(result["confidence_breakdown"].values()) == int(
        result["confidence"] * 100
    )
