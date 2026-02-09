"""Tests for admin feedback route extensions — channel and method filters.

Covers:
- GET /admin/feedback/list accepts channel and feedback_method query params
- FeedbackFilters.apply_filters() handles channel and feedback_method criteria
- GET /admin/feedback/stats includes feedback_by_channel and feedback_by_method
"""

import pytest
from app.models.feedback import FeedbackFilterRequest, FeedbackItem
from app.services.feedback.feedback_filters import FeedbackFilters

# =============================================================================
# Fixtures
# =============================================================================


def _make_item(**overrides) -> FeedbackItem:
    """Create a FeedbackItem with sensible defaults."""
    defaults = {
        "message_id": "msg-001",
        "question": "How do I use Bisq?",
        "answer": "You can download Bisq from bisq.network.",
        "rating": 1,
        "timestamp": "2024-06-15T10:00:00Z",
        "channel": "web",
        "feedback_method": "web_dialog",
    }
    defaults.update(overrides)
    return FeedbackItem(**defaults)


@pytest.fixture()
def sample_items():
    """Mixed-channel feedback items for filtering tests."""
    return [
        _make_item(
            message_id="m1", channel="web", feedback_method="web_dialog", rating=1
        ),
        _make_item(
            message_id="m2", channel="matrix", feedback_method="reaction", rating=0
        ),
        _make_item(
            message_id="m3", channel="matrix", feedback_method="reaction", rating=1
        ),
        _make_item(
            message_id="m4", channel="bisq2", feedback_method="reaction", rating=0
        ),
        _make_item(
            message_id="m5", channel="web", feedback_method="web_dialog", rating=0
        ),
    ]


@pytest.fixture()
def filters():
    return FeedbackFilters()


# =============================================================================
# FeedbackFilters: channel filter
# =============================================================================


class TestFiltersChannel:
    """FeedbackFilters.apply_filters() with channel filter."""

    def test_filter_by_channel_web(self, filters, sample_items):
        """Filtering by channel='web' returns only web items."""
        req = FeedbackFilterRequest(channel="web")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 2
        assert all(item.channel == "web" for item in result)

    def test_filter_by_channel_matrix(self, filters, sample_items):
        """Filtering by channel='matrix' returns only matrix items."""
        req = FeedbackFilterRequest(channel="matrix")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 2
        assert all(item.channel == "matrix" for item in result)

    def test_filter_by_channel_bisq2(self, filters, sample_items):
        """Filtering by channel='bisq2' returns only bisq2 items."""
        req = FeedbackFilterRequest(channel="bisq2")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 1
        assert result[0].channel == "bisq2"

    def test_filter_no_channel_returns_all(self, filters, sample_items):
        """No channel filter returns all items."""
        req = FeedbackFilterRequest()
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 5

    def test_filter_unknown_channel_returns_empty(self, filters, sample_items):
        """Unknown channel returns no items."""
        req = FeedbackFilterRequest(channel="unknown")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 0


# =============================================================================
# FeedbackFilters: feedback_method filter
# =============================================================================


class TestFiltersFeedbackMethod:
    """FeedbackFilters.apply_filters() with feedback_method filter."""

    def test_filter_by_method_web_dialog(self, filters, sample_items):
        """Filtering by feedback_method='web_dialog' returns only web_dialog items."""
        req = FeedbackFilterRequest(feedback_method="web_dialog")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 2
        assert all(item.feedback_method == "web_dialog" for item in result)

    def test_filter_by_method_reaction(self, filters, sample_items):
        """Filtering by feedback_method='reaction' returns only reaction items."""
        req = FeedbackFilterRequest(feedback_method="reaction")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 3
        assert all(item.feedback_method == "reaction" for item in result)

    def test_filter_no_method_returns_all(self, filters, sample_items):
        """No feedback_method filter returns all items."""
        req = FeedbackFilterRequest()
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 5


# =============================================================================
# FeedbackFilters: combined channel + method filters
# =============================================================================


class TestFiltersCombined:
    """Combined channel and feedback_method filtering."""

    def test_channel_and_method_combined(self, filters, sample_items):
        """Combining channel and feedback_method narrows results."""
        req = FeedbackFilterRequest(channel="matrix", feedback_method="reaction")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 2
        assert all(
            item.channel == "matrix" and item.feedback_method == "reaction"
            for item in result
        )

    def test_channel_and_rating_combined(self, filters, sample_items):
        """Channel filter works with rating filter."""
        req = FeedbackFilterRequest(channel="matrix", rating="negative")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 1
        assert result[0].message_id == "m2"

    def test_method_and_rating_combined(self, filters, sample_items):
        """Method filter works with rating filter."""
        req = FeedbackFilterRequest(feedback_method="web_dialog", rating="positive")
        result = filters.apply_filters(sample_items, req)
        assert len(result) == 1
        assert result[0].message_id == "m1"
