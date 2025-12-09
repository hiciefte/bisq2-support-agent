"""Tests for AISuite LLM classifier with security hardening.

This module tests the LLM-based message classifier that uses AISuite
for provider-agnostic LLM access with comprehensive security features.
"""

import hashlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.services.shadow_mode.aisuite_classifier import (
    AISuiteClassifier,
    CircuitBreaker,
    ClassificationInput,
    ClassificationResult,
    ConfidenceBreakdown,
    RateLimiter,
)


class TestClassificationInput:
    """Test input validation with Pydantic."""

    def test_valid_input(self):
        """Should accept valid classification input."""
        input_data = ClassificationInput(
            message="test message",
            sender_id="user123",
        )
        assert input_data.message == "test message"
        assert input_data.sender_id == "user123"
        assert input_data.prev_messages == []  # Default

    def test_message_length_validation(self):
        """Should reject messages exceeding max length."""
        with pytest.raises(ValueError, match="at most 2000 characters"):
            ClassificationInput(
                message="a" * 2001,  # Exceeds limit
                sender_id="user123",
            )

    def test_message_min_length_validation(self):
        """Should reject empty messages."""
        with pytest.raises(ValueError, match="at least 1 character"):
            ClassificationInput(
                message="",
                sender_id="user123",
            )

    def test_sender_id_validation(self):
        """Should validate sender ID length."""
        with pytest.raises(ValueError, match="at least 1 character"):
            ClassificationInput(
                message="test",
                sender_id="",
            )

        with pytest.raises(ValueError, match="at most 100 characters"):
            ClassificationInput(
                message="test",
                sender_id="a" * 101,
            )

    def test_prev_messages_max_items(self):
        """Should limit previous messages to 5."""
        with pytest.raises(ValueError, match="at most 5 items"):
            ClassificationInput(
                message="test",
                sender_id="user123",
                prev_messages=["msg1", "msg2", "msg3", "msg4", "msg5", "msg6"],  # Too many
            )

    def test_unicode_normalization(self):
        """Should normalize Unicode to canonical form (NFKC)."""
        # Test with combining characters (different representations)
        # é can be represented as: 1) single char U+00E9 OR 2) e + combining acute U+0065 U+0301
        input_data = ClassificationInput(
            message="café",  # Using composed form
            sender_id="user123",
        )
        # Should be normalized to NFKC (consistent representation)
        assert input_data.message == "café"  # Normalized form


class TestConfidenceBreakdown:
    """Test confidence breakdown validation."""

    def test_valid_breakdown(self):
        """Should accept valid confidence breakdown."""
        breakdown = ConfidenceBreakdown(
            keyword_match=20,
            syntax_pattern=15,
            semantic_clarity=25,
            context_alignment=10,
        )
        assert breakdown.keyword_match == 20
        assert breakdown.total == 70

    def test_keyword_match_range(self):
        """Should enforce keyword_match range (0-25)."""
        with pytest.raises(ValueError, match="greater than or equal to 0"):
            ConfidenceBreakdown(
                keyword_match=-1,
                syntax_pattern=10,
                semantic_clarity=10,
                context_alignment=10,
            )

        with pytest.raises(ValueError, match="less than or equal to 25"):
            ConfidenceBreakdown(
                keyword_match=26,
                syntax_pattern=10,
                semantic_clarity=10,
                context_alignment=10,
            )

    def test_total_calculation(self):
        """Should automatically calculate total."""
        breakdown = ConfidenceBreakdown(
            keyword_match=25,
            syntax_pattern=25,
            semantic_clarity=30,
            context_alignment=20,
        )
        assert breakdown.total == 100


class TestClassificationResult:
    """Test classification result validation."""

    def test_valid_result(self):
        """Should accept valid classification result."""
        result = ClassificationResult(
            role="USER_QUESTION",
            confidence_breakdown=ConfidenceBreakdown(
                keyword_match=20,
                syntax_pattern=15,
                semantic_clarity=25,
                context_alignment=10,
            ),
            confidence=0.70,
        )
        assert result.role == "USER_QUESTION"
        assert result.confidence == 0.70

    def test_role_must_be_literal(self):
        """Should only accept USER_QUESTION or STAFF_RESPONSE."""
        with pytest.raises(ValueError):
            ClassificationResult(
                role="INVALID_ROLE",
                confidence_breakdown=ConfidenceBreakdown(
                    keyword_match=10,
                    syntax_pattern=10,
                    semantic_clarity=10,
                    context_alignment=10,
                ),
                confidence=0.40,
            )

    def test_confidence_range(self):
        """Should enforce confidence range (0.0-1.0)."""
        with pytest.raises(ValueError):
            ClassificationResult(
                role="USER_QUESTION",
                confidence_breakdown=ConfidenceBreakdown(
                    keyword_match=10,
                    syntax_pattern=10,
                    semantic_clarity=10,
                    context_alignment=10,
                ),
                confidence=1.5,  # Out of range
            )


class TestRateLimiter:
    """Test per-user rate limiting."""

    def test_allows_requests_within_limit(self):
        """Should allow requests within rate limit."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)

        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user1") is True

    def test_blocks_requests_exceeding_limit(self):
        """Should block requests exceeding rate limit."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)

        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user1") is False  # Exceeds limit

    def test_different_users_independent_limits(self):
        """Should track rate limits independently per user."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)

        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user2") is True  # Different user, separate limit
        assert limiter.is_allowed("user2") is True

    def test_window_expiration(self):
        """Should reset limit after time window expires."""
        limiter = RateLimiter(max_requests=1, window_seconds=1)

        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user1") is False  # Blocked

        # Wait for window to expire
        import time

        time.sleep(1.1)

        assert limiter.is_allowed("user1") is True  # Allowed again


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_closed_by_default(self):
        """Circuit should be closed (allowing requests) by default."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert breaker.is_open() is False

    def test_opens_after_threshold_failures(self):
        """Circuit should open after reaching failure threshold."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        breaker.record_failure()
        assert breaker.is_open() is False

        breaker.record_failure()
        assert breaker.is_open() is True  # Opened after 2 failures

    def test_resets_on_success(self):
        """Should reset failure count on successful request."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.failure_count == 2

        breaker.record_success()
        assert breaker.failure_count == 0  # Reset

    def test_recovers_after_timeout(self):
        """Circuit should close after recovery timeout."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=1)

        breaker.record_failure()
        assert breaker.is_open() is True

        # Wait for recovery
        import time

        time.sleep(1.1)

        assert breaker.is_open() is False  # Recovered


class TestAISuiteClassifier:
    """Test AISuite classifier with security features."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing."""
        settings = Mock()
        settings.LLM_CLASSIFICATION_MODEL = "openai:gpt-4o-mini"
        settings.LLM_CLASSIFICATION_TEMPERATURE = 0.2
        settings.LLM_CLASSIFICATION_THRESHOLD = 0.75
        settings.LLM_CLASSIFICATION_RATE_LIMIT_REQUESTS = 10
        settings.LLM_CLASSIFICATION_RATE_LIMIT_WINDOW = 60
        settings.LLM_CLASSIFICATION_CACHE_SIZE = 100
        settings.LLM_CLASSIFICATION_CACHE_TTL_HOURS = 1
        settings.ACTIVE_LLM_API_KEY = "test-api-key"
        return settings

    @pytest.fixture
    def mock_ai_client(self):
        """Mock AISuite client."""
        client = Mock()
        # Mock successful LLM response
        mock_response = Mock()
        mock_response.choices = [
            Mock(
                message=Mock(
                    content='{"role": "USER_QUESTION", "confidence_breakdown": {"keyword_match": 20, "syntax_pattern": 15, "semantic_clarity": 25, "context_alignment": 10}, "confidence": 0.70}'
                )
            )
        ]
        client.chat.completions.create = AsyncMock(return_value=mock_response)
        return client

    @pytest.mark.asyncio
    async def test_successful_classification(self, mock_settings, mock_ai_client):
        """Should successfully classify a message."""
        classifier = AISuiteClassifier(mock_ai_client, mock_settings)

        result = await classifier.classify(
            message="i can't open my trade",
            sender_id="user123",
        )

        assert result["role"] == "USER_QUESTION"
        assert result["confidence"] == 0.70
        assert "confidence_breakdown" in result

    @pytest.mark.asyncio
    async def test_rate_limiting(self, mock_settings, mock_ai_client):
        """Should enforce per-user rate limiting."""
        mock_settings.LLM_CLASSIFICATION_RATE_LIMIT_REQUESTS = 2
        classifier = AISuiteClassifier(mock_ai_client, mock_settings)

        # First two requests should succeed
        await classifier.classify("message 1", "user1")
        await classifier.classify("message 2", "user1")

        # Third should be rate limited
        with pytest.raises(Exception, match="Rate limit exceeded"):
            await classifier.classify("message 3", "user1")

    @pytest.mark.asyncio
    async def test_circuit_breaker(self, mock_settings, mock_ai_client):
        """Should open circuit after repeated failures."""
        # Make LLM calls fail
        mock_ai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )

        classifier = AISuiteClassifier(mock_ai_client, mock_settings)

        # Trigger failures to open circuit
        for i in range(5):
            try:
                await classifier.classify(f"message {i}", "user1")
            except:
                pass

        # Circuit should now be open
        with pytest.raises(Exception, match="Circuit breaker"):
            await classifier.classify("test", "user1")

    @pytest.mark.asyncio
    async def test_cache_usage(self, mock_settings, mock_ai_client):
        """Should cache classification results."""
        classifier = AISuiteClassifier(mock_ai_client, mock_settings)

        # First call - should hit LLM
        result1 = await classifier.classify("test message", "user1")

        # Second call with same message - should use cache
        result2 = await classifier.classify("test message", "user1")

        assert result1 == result2
        # LLM should only be called once
        assert mock_ai_client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_pii_redaction(self, mock_settings, mock_ai_client):
        """Should redact PII before sending to LLM."""
        classifier = AISuiteClassifier(mock_ai_client, mock_settings)

        await classifier.classify(
            message="my email is user@example.com",
            sender_id="user123",
        )

        # Check that PII was redacted in LLM call
        call_args = mock_ai_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        user_message = messages[-1]["content"]

        # Email should be redacted
        assert "user@example.com" not in user_message

    @pytest.mark.asyncio
    async def test_hash_only_cache_keys(self, mock_settings, mock_ai_client):
        """Should use hash-only cache keys (no plaintext storage)."""
        classifier = AISuiteClassifier(mock_ai_client, mock_settings)

        await classifier.classify("sensitive message", "user1")

        # Cache keys should be SHA-256 hashes, not plaintext
        cache_keys = list(classifier._cache.keys())
        assert len(cache_keys) > 0

        # Verify it's a hash (64 hex characters for SHA-256)
        for key in cache_keys:
            assert len(key) == 64
            assert all(c in "0123456789abcdef" for c in key)
