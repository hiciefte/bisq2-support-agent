"""Tests for multichannel feedback model extensions.

Covers:
- message_id relaxed regex (Matrix event IDs, Bisq2 hex, web UUIDs)
- Channel/method defaults and backwards compatibility
- New optional fields on FeedbackRequest and FeedbackItem
- FeedbackFilterRequest channel/method filters
- FeedbackStatsResponse new fields with defaults
"""

import pytest
from app.models.feedback import (
    FeedbackFilterRequest,
    FeedbackItem,
    FeedbackRequest,
    FeedbackStatsResponse,
)
from pydantic import ValidationError

# =============================================================================
# message_id validation
# =============================================================================


class TestMessageIdValidation:
    """Test relaxed message_id pattern."""

    def test_uuid_still_valid(self):
        """Web UUIDs continue to work."""
        req = FeedbackRequest(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            question="Q",
            answer="A",
            rating=1,
        )
        assert req.message_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_matrix_event_id_valid(self):
        """Matrix event IDs ($xxx:server) are now accepted."""
        req = FeedbackRequest(
            message_id="$abcdef1234:matrix.org",
            question="Q",
            answer="A",
            rating=1,
        )
        assert req.message_id == "$abcdef1234:matrix.org"

    def test_bisq2_hex_id_valid(self):
        """Bisq2 hex message IDs are accepted."""
        req = FeedbackRequest(
            message_id="a1b2c3d4e5f6",
            question="Q",
            answer="A",
            rating=1,
        )
        assert req.message_id == "a1b2c3d4e5f6"

    def test_empty_message_id_rejected(self):
        """Empty message_id is rejected."""
        with pytest.raises(ValidationError):
            FeedbackRequest(
                message_id="",
                question="Q",
                answer="A",
                rating=1,
            )

    def test_message_id_max_length(self):
        """message_id exceeding 256 chars is rejected."""
        with pytest.raises(ValidationError):
            FeedbackRequest(
                message_id="a" * 257,
                question="Q",
                answer="A",
                rating=1,
            )

    def test_message_id_special_chars_rejected(self):
        """message_id with disallowed special characters is rejected."""
        with pytest.raises(ValidationError):
            FeedbackRequest(
                message_id="msg id with spaces",
                question="Q",
                answer="A",
                rating=1,
            )


# =============================================================================
# Channel field defaults
# =============================================================================


class TestChannelFieldDefaults:
    """Test channel and feedback_method defaults for backwards compatibility."""

    def test_default_channel_is_web(self):
        """Default channel should be 'web'."""
        req = FeedbackRequest(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            question="Q",
            answer="A",
            rating=1,
        )
        assert req.channel == "web"

    def test_default_feedback_method_is_web_dialog(self):
        """Default feedback_method should be 'web_dialog'."""
        req = FeedbackRequest(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            question="Q",
            answer="A",
            rating=1,
        )
        assert req.feedback_method == "web_dialog"

    def test_explicit_channel_override(self):
        """Channel can be set explicitly."""
        req = FeedbackRequest(
            message_id="$evt:server",
            question="Q",
            answer="A",
            rating=1,
            channel="matrix",
            feedback_method="reaction",
        )
        assert req.channel == "matrix"
        assert req.feedback_method == "reaction"


# =============================================================================
# New optional fields
# =============================================================================


class TestNewOptionalFields:
    """Test new optional fields on FeedbackRequest."""

    def test_external_message_id_optional(self):
        """external_message_id is optional and defaults to None."""
        req = FeedbackRequest(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            question="Q",
            answer="A",
            rating=1,
        )
        assert req.external_message_id is None

    def test_external_message_id_set(self):
        """external_message_id can be set."""
        req = FeedbackRequest(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            question="Q",
            answer="A",
            rating=1,
            external_message_id="$evt:matrix.org",
        )
        assert req.external_message_id == "$evt:matrix.org"

    def test_reactor_identity_hash_optional(self):
        """reactor_identity_hash is optional."""
        req = FeedbackRequest(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            question="Q",
            answer="A",
            rating=1,
        )
        assert req.reactor_identity_hash is None

    def test_reaction_emoji_optional(self):
        """reaction_emoji is optional."""
        req = FeedbackRequest(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            question="Q",
            answer="A",
            rating=1,
        )
        assert req.reaction_emoji is None

    def test_all_reaction_fields_set(self):
        """All reaction fields can be set together."""
        req = FeedbackRequest(
            message_id="$evt:matrix.org",
            question="How does Bisq work?",
            answer="Bisq is a decentralized exchange.",
            rating=1,
            channel="matrix",
            feedback_method="reaction",
            external_message_id="$evt:matrix.org",
            reactor_identity_hash="abc123def456",
            reaction_emoji="\U0001f44d",
        )
        assert req.channel == "matrix"
        assert req.feedback_method == "reaction"
        assert req.external_message_id == "$evt:matrix.org"
        assert req.reactor_identity_hash == "abc123def456"
        assert req.reaction_emoji == "\U0001f44d"


# =============================================================================
# FeedbackItem extensions
# =============================================================================


class TestFeedbackItemExtensions:
    """Test new fields on FeedbackItem."""

    def test_feedback_item_default_channel(self):
        """FeedbackItem defaults channel to 'web'."""
        item = FeedbackItem(
            message_id="test-id",
            question="Q",
            answer="A",
            rating=1,
            timestamp="2024-01-01T00:00:00Z",
        )
        assert item.channel == "web"
        assert item.feedback_method == "web_dialog"

    def test_feedback_item_with_reaction_fields(self):
        """FeedbackItem can include reaction-specific fields."""
        item = FeedbackItem(
            message_id="$evt:server",
            question="Q",
            answer="A",
            rating=1,
            timestamp="2024-01-01T00:00:00Z",
            channel="matrix",
            feedback_method="reaction",
            external_message_id="$evt:server",
            reactor_identity_hash="abc123",
            reaction_emoji="\U0001f44d",
        )
        assert item.channel == "matrix"
        assert item.feedback_method == "reaction"
        assert item.external_message_id == "$evt:server"


# =============================================================================
# FeedbackFilterRequest extensions
# =============================================================================


class TestFeedbackFilterRequestExtensions:
    """Test channel/method filters on FeedbackFilterRequest."""

    def test_channel_filter_optional(self):
        """channel filter is optional."""
        req = FeedbackFilterRequest()
        assert req.channel is None

    def test_feedback_method_filter_optional(self):
        """feedback_method filter is optional."""
        req = FeedbackFilterRequest()
        assert req.feedback_method is None

    def test_channel_filter_set(self):
        """channel filter can be set."""
        req = FeedbackFilterRequest(channel="matrix")
        assert req.channel == "matrix"

    def test_feedback_method_filter_set(self):
        """feedback_method filter can be set."""
        req = FeedbackFilterRequest(feedback_method="reaction")
        assert req.feedback_method == "reaction"


# =============================================================================
# FeedbackStatsResponse extensions
# =============================================================================


class TestFeedbackStatsResponseExtensions:
    """Test new fields on FeedbackStatsResponse with backwards compat."""

    def test_default_feedback_by_channel(self):
        """feedback_by_channel defaults to empty dict."""
        resp = FeedbackStatsResponse(
            total_feedback=10,
            positive_count=8,
            negative_count=2,
            helpful_rate=0.8,
            common_issues={},
            recent_negative_count=1,
            needs_faq_count=0,
            source_effectiveness={},
            feedback_by_month={},
        )
        assert resp.feedback_by_channel == {}

    def test_default_feedback_by_method(self):
        """feedback_by_method defaults to empty dict."""
        resp = FeedbackStatsResponse(
            total_feedback=10,
            positive_count=8,
            negative_count=2,
            helpful_rate=0.8,
            common_issues={},
            recent_negative_count=1,
            needs_faq_count=0,
            source_effectiveness={},
            feedback_by_month={},
        )
        assert resp.feedback_by_method == {}

    def test_feedback_by_channel_populated(self):
        """feedback_by_channel can be populated."""
        resp = FeedbackStatsResponse(
            total_feedback=10,
            positive_count=8,
            negative_count=2,
            helpful_rate=0.8,
            common_issues={},
            recent_negative_count=1,
            needs_faq_count=0,
            source_effectiveness={},
            feedback_by_month={},
            feedback_by_channel={
                "web": {"positive": 5, "negative": 1},
                "matrix": {"positive": 3, "negative": 1},
            },
        )
        assert "web" in resp.feedback_by_channel
        assert "matrix" in resp.feedback_by_channel

    def test_feedback_by_method_populated(self):
        """feedback_by_method can be populated."""
        resp = FeedbackStatsResponse(
            total_feedback=10,
            positive_count=8,
            negative_count=2,
            helpful_rate=0.8,
            common_issues={},
            recent_negative_count=1,
            needs_faq_count=0,
            source_effectiveness={},
            feedback_by_month={},
            feedback_by_method={
                "web_dialog": {"positive": 5, "negative": 1},
                "reaction": {"positive": 3, "negative": 1},
            },
        )
        assert "web_dialog" in resp.feedback_by_method
        assert "reaction" in resp.feedback_by_method
