"""Tests for Channel Middleware Hooks.

TDD tests for middleware implementations: rate limiting, PII filtering, metrics.
"""

from datetime import datetime, timedelta, timezone

import pytest
from app.channels.hooks import HookPriority
from app.channels.models import (
    ChannelType,
    ErrorCode,
    GatewayError,
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)


def _make_outgoing(answer: str, user_id: str = "test-user") -> OutgoingMessage:
    """Helper to create OutgoingMessage with required fields."""
    return OutgoingMessage(
        message_id="resp-001",
        channel=ChannelType.WEB,
        in_reply_to="msg-001",
        answer=answer,
        sources=[],
        user=UserContext(user_id=user_id),
        metadata=ResponseMetadata(
            processing_time_ms=100.0,
            rag_strategy="retrieval",
            model_name="test-model",
        ),
    )


# =============================================================================
# Rate Limit Hook Tests
# =============================================================================


class TestRateLimitHook:
    """Test RateLimitHook middleware."""

    @pytest.mark.unit
    def test_rate_limit_hook_has_correct_name(self):
        """RateLimitHook has name 'rate_limit'."""
        from app.channels.middleware.rate_limit import RateLimitHook

        hook = RateLimitHook()
        assert hook.name == "rate_limit"

    @pytest.mark.unit
    def test_rate_limit_hook_has_high_priority(self):
        """RateLimitHook has HIGH priority."""
        from app.channels.middleware.rate_limit import RateLimitHook

        hook = RateLimitHook()
        assert hook.priority == HookPriority.HIGH

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_rate_limit_allows_within_limit(self, sample_incoming_message):
        """Messages within limit are allowed."""
        from app.channels.middleware.rate_limit import RateLimitHook

        hook = RateLimitHook(capacity=10, refill_rate=1.0)
        result = await hook.execute(sample_incoming_message)
        assert result is None  # None means allowed

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_rate_limit_blocks_over_limit(self, sample_incoming_message):
        """Messages over limit are blocked."""
        from app.channels.middleware.rate_limit import RateLimitHook

        hook = RateLimitHook(capacity=2, refill_rate=0.1)

        # First two should pass
        await hook.execute(sample_incoming_message)
        await hook.execute(sample_incoming_message)

        # Third should be blocked
        result = await hook.execute(sample_incoming_message)
        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.RATE_LIMIT_EXCEEDED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_rate_limit_tracks_per_user(self, sample_incoming_message):
        """Rate limits are tracked per user."""
        from app.channels.middleware.rate_limit import RateLimitHook

        hook = RateLimitHook(capacity=1, refill_rate=0.01)

        # User 1 gets blocked after 1 request
        await hook.execute(sample_incoming_message)
        result = await hook.execute(sample_incoming_message)
        assert isinstance(result, GatewayError)

        # User 2 should still be allowed
        user2_message = IncomingMessage(
            message_id="msg-002",
            channel=ChannelType.WEB,
            question="Question from user 2",
            user=UserContext(user_id="different-user"),
        )
        result2 = await hook.execute(user2_message)
        assert result2 is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_rate_limit_returns_retry_after(self, sample_incoming_message):
        """Blocked response includes retry_after."""
        from app.channels.middleware.rate_limit import RateLimitHook

        hook = RateLimitHook(capacity=1, refill_rate=0.5)

        # Exhaust limit
        await hook.execute(sample_incoming_message)
        result = await hook.execute(sample_incoming_message)

        assert isinstance(result, GatewayError)
        assert "retry_after" in result.details

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_rate_limit_skipped_when_in_bypass_hooks(self):
        """Rate limit skipped when in bypass_hooks list."""
        from app.channels.middleware.rate_limit import RateLimitHook

        hook = RateLimitHook(capacity=0, refill_rate=0)  # Would always block

        message = IncomingMessage(
            message_id="msg-001",
            channel=ChannelType.WEB,
            question="Test question",
            user=UserContext(user_id="test-user"),
            bypass_hooks=["rate_limit"],
        )

        # Should skip the hook entirely
        assert hook.should_skip(message) is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_rate_limit_refills_over_time(self, sample_incoming_message):
        """Rate limit refills tokens over time."""
        from app.channels.middleware.rate_limit import RateLimitHook

        hook = RateLimitHook(capacity=1, refill_rate=10.0)  # Fast refill for test

        # Exhaust
        await hook.execute(sample_incoming_message)

        # Manually advance time by manipulating bucket
        bucket = hook._get_bucket(sample_incoming_message.user.user_id)
        bucket.last_refill = datetime.now(timezone.utc) - timedelta(seconds=1)
        bucket.tokens = 0

        # Should now have tokens again
        result = await hook.execute(sample_incoming_message)
        assert result is None


# =============================================================================
# PII Filter Hook Tests
# =============================================================================


class TestPIIFilterHook:
    """Test PIIFilterHook middleware."""

    @pytest.mark.unit
    def test_pii_filter_hook_has_correct_name(self):
        """PIIFilterHook has name 'pii_filter'."""
        from app.channels.middleware.pii_filter import PIIFilterHook

        hook = PIIFilterHook()
        assert hook.name == "pii_filter"

    @pytest.mark.unit
    def test_pii_filter_hook_has_high_priority(self):
        """PIIFilterHook has HIGH priority."""
        from app.channels.middleware.pii_filter import PIIFilterHook

        hook = PIIFilterHook()
        assert hook.priority == HookPriority.HIGH

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pii_filter_redacts_email_in_response(self, sample_incoming_message):
        """PIIFilterHook redacts email addresses in response."""
        from app.channels.middleware.pii_filter import PIIFilterHook

        hook = PIIFilterHook()

        outgoing = _make_outgoing("Contact us at support@example.com for help.")

        result = await hook.execute(sample_incoming_message, outgoing)

        assert result is None  # Continues processing
        assert "support@example.com" not in outgoing.answer
        assert "[REDACTED]" in outgoing.answer

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pii_filter_redacts_bitcoin_address(self, sample_incoming_message):
        """PIIFilterHook redacts Bitcoin addresses."""
        from app.channels.middleware.pii_filter import PIIFilterHook

        hook = PIIFilterHook()

        outgoing = _make_outgoing("Send to 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")

        await hook.execute(sample_incoming_message, outgoing)

        assert "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2" not in outgoing.answer

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pii_filter_blocks_on_detect_mode(self, sample_incoming_message):
        """PIIFilterHook can block instead of redact."""
        from app.channels.middleware.pii_filter import PIIFilterHook

        hook = PIIFilterHook(mode="block")

        outgoing = _make_outgoing("Contact us at support@example.com")

        result = await hook.execute(sample_incoming_message, outgoing)

        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.PII_DETECTED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pii_filter_allows_clean_responses(self, sample_incoming_message):
        """PIIFilterHook allows responses without PII."""
        from app.channels.middleware.pii_filter import PIIFilterHook

        hook = PIIFilterHook()

        outgoing = _make_outgoing("To backup your wallet, go to Settings > Backup.")

        result = await hook.execute(sample_incoming_message, outgoing)

        assert result is None
        assert "To backup your wallet" in outgoing.answer

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pii_filter_custom_replacement(self, sample_incoming_message):
        """PIIFilterHook supports custom replacement text."""
        from app.channels.middleware.pii_filter import PIIFilterHook

        hook = PIIFilterHook(replacement="[HIDDEN]")

        outgoing = _make_outgoing("Email: test@test.com")

        await hook.execute(sample_incoming_message, outgoing)

        assert "[HIDDEN]" in outgoing.answer

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pii_filter_skipped_when_in_bypass_hooks(
        self, sample_incoming_message
    ):
        """PII filter skipped when in bypass_hooks list."""
        from app.channels.middleware.pii_filter import PIIFilterHook

        hook = PIIFilterHook()

        message = IncomingMessage(
            message_id="msg-001",
            channel=ChannelType.WEB,
            question="Test",
            user=UserContext(user_id="admin"),
            bypass_hooks=["pii_filter"],
        )

        assert hook.should_skip(message) is True


# =============================================================================
# Metrics Hook Tests
# =============================================================================


class TestMetricsHook:
    """Test MetricsHook middleware."""

    @pytest.mark.unit
    def test_metrics_hook_has_correct_name(self):
        """MetricsHook has name 'metrics'."""
        from app.channels.middleware.metrics import MetricsHook

        hook = MetricsHook()
        assert hook.name == "metrics"

    @pytest.mark.unit
    def test_metrics_hook_has_low_priority(self):
        """MetricsHook has LOW priority (runs last)."""
        from app.channels.middleware.metrics import MetricsHook

        hook = MetricsHook()
        assert hook.priority == HookPriority.LOW

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_metrics_hook_records_request(self, sample_incoming_message):
        """MetricsHook records incoming request metrics."""
        from app.channels.middleware.metrics import MetricsHook

        hook = MetricsHook()
        result = await hook.execute(sample_incoming_message)

        assert result is None
        # Check metrics were recorded
        assert hook.get_request_count() >= 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_metrics_hook_records_response(self, sample_incoming_message):
        """MetricsHook records response metrics."""
        from app.channels.middleware.metrics import MetricsHook

        hook = MetricsHook()

        outgoing = _make_outgoing("Test answer")

        result = await hook.execute_post(sample_incoming_message, outgoing)

        assert result is None
        assert hook.get_response_count() >= 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_metrics_hook_tracks_by_channel(self, sample_incoming_message):
        """MetricsHook tracks metrics by channel."""
        from app.channels.middleware.metrics import MetricsHook

        hook = MetricsHook()

        # Web channel request
        await hook.execute(sample_incoming_message)

        # Matrix channel request
        matrix_message = IncomingMessage(
            message_id="msg-002",
            channel=ChannelType.MATRIX,
            question="Matrix question",
            user=UserContext(user_id="matrix-user"),
        )
        await hook.execute(matrix_message)

        channel_stats = hook.get_channel_stats()
        assert channel_stats.get(ChannelType.WEB, 0) >= 1
        assert channel_stats.get(ChannelType.MATRIX, 0) >= 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_metrics_hook_never_blocks(self, sample_incoming_message):
        """MetricsHook never blocks requests."""
        from app.channels.middleware.metrics import MetricsHook

        hook = MetricsHook()

        # Even with errors in metrics recording, should not block
        result = await hook.execute(sample_incoming_message)
        assert result is None

    @pytest.mark.unit
    def test_metrics_hook_get_all_metrics(self):
        """MetricsHook provides all metrics summary."""
        from app.channels.middleware.metrics import MetricsHook

        hook = MetricsHook()
        metrics = hook.get_all_metrics()

        assert "requests" in metrics
        assert "responses" in metrics
        assert "by_channel" in metrics


# =============================================================================
# Authentication Hook Tests (if exists)
# =============================================================================


class TestAuthenticationHook:
    """Test AuthenticationHook middleware."""

    @pytest.mark.unit
    def test_authentication_hook_has_correct_name(self):
        """AuthenticationHook has name 'authentication'."""
        from app.channels.middleware.authentication import AuthenticationHook

        hook = AuthenticationHook()
        assert hook.name == "authentication"

    @pytest.mark.unit
    def test_authentication_hook_has_critical_priority(self):
        """AuthenticationHook has CRITICAL priority."""
        from app.channels.middleware.authentication import AuthenticationHook

        hook = AuthenticationHook()
        assert hook.priority == HookPriority.CRITICAL

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_authentication_allows_web_channel(self, sample_incoming_message):
        """Web channel messages allowed without auth."""
        from app.channels.middleware.authentication import AuthenticationHook

        hook = AuthenticationHook()
        result = await hook.execute(sample_incoming_message)
        assert result is None  # Web doesn't require auth

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_authentication_requires_token_for_bisq2(self):
        """Bisq2 channel requires authentication."""
        from app.channels.middleware.authentication import AuthenticationHook

        hook = AuthenticationHook()

        message = IncomingMessage(
            message_id="bisq-001",
            channel=ChannelType.BISQ2,
            question="Test question",
            user=UserContext(user_id="bisq-user"),  # No auth token
        )

        result = await hook.execute(message)
        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.AUTHENTICATION_FAILED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_authentication_accepts_valid_token(self):
        """Valid authentication token is accepted."""
        from app.channels.middleware.authentication import AuthenticationHook

        hook = AuthenticationHook(valid_tokens={"test-token"})

        message = IncomingMessage(
            message_id="bisq-001",
            channel=ChannelType.BISQ2,
            question="Test question",
            user=UserContext(
                user_id="bisq-user",
                auth_token="test-token",
            ),
        )

        result = await hook.execute(message)
        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_authentication_rejects_invalid_token(self):
        """Invalid authentication token is rejected."""
        from app.channels.middleware.authentication import AuthenticationHook

        hook = AuthenticationHook(valid_tokens={"correct-token"})

        message = IncomingMessage(
            message_id="bisq-001",
            channel=ChannelType.BISQ2,
            question="Test question",
            user=UserContext(
                user_id="bisq-user",
                auth_token="wrong-token",
            ),
        )

        result = await hook.execute(message)
        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.AUTHENTICATION_FAILED
