"""
Tests for FAQ timestamp functionality - Service layer.

Tests cover:
- ISO 8601 date string parsing in service layer
- Date range filtering via API endpoints
- FAQ stats endpoint with date filters

Note: Migration script tests were removed as the JSONL-based migration
has been completed and SQLite is now the authoritative FAQ storage.
"""

from datetime import datetime, timedelta, timezone

from app.models.faq import FAQItem


class TestFAQServiceDateParsing:
    """Test ISO 8601 date string parsing in FAQService."""

    def test_parse_valid_iso_8601_date(self, faq_service):
        """Test parsing valid ISO 8601 date strings."""
        # Valid ISO 8601 with Z suffix
        date_str = "2024-01-15T10:30:00Z"
        result = faq_service.get_faqs_paginated(verified_from=date_str)

        # Should not raise error and return results
        assert result is not None
        assert hasattr(result, "faqs")

    def test_parse_iso_8601_without_z(self, faq_service):
        """Test parsing ISO 8601 without Z suffix."""
        # Valid ISO 8601 with timezone offset
        date_str = "2024-01-15T10:30:00+00:00"
        result = faq_service.get_faqs_paginated(verified_from=date_str)

        # Should not raise error
        assert result is not None
        assert hasattr(result, "faqs")

    def test_parse_invalid_date_format_logs_warning(self, faq_service, caplog):
        """Test that invalid date format logs warning and continues."""
        # Invalid date format
        invalid_date = "not-a-date"

        result = faq_service.get_faqs_paginated(verified_from=invalid_date)

        # Should log warning but not raise error
        assert "Invalid verified_from date format" in caplog.text
        assert result is not None

    def test_parse_date_range_both_dates(self, faq_service):
        """Test parsing both verified_from and verified_to dates."""
        from_date = "2024-01-01T00:00:00Z"
        to_date = "2024-12-31T23:59:59Z"

        result = faq_service.get_faqs_paginated(
            verified_from=from_date, verified_to=to_date
        )

        # Should not raise error
        assert result is not None
        assert hasattr(result, "faqs")

    def test_none_dates_pass_through(self, faq_service):
        """Test that None dates are handled correctly."""
        result = faq_service.get_faqs_paginated(verified_from=None, verified_to=None)

        # Should not raise error
        assert result is not None
        assert hasattr(result, "faqs")


class TestFAQStatsEndpoint:
    """Test FAQ statistics endpoint with date filtering."""

    def test_stats_returns_correct_structure(self, faq_service):
        """Test that stats have the correct structure."""
        # Add some verified FAQs
        for i in range(3):
            faq = FAQItem(
                question=f"Question {i}?",
                answer=f"Answer {i}",
                category="test",
                source="manual",
                verified=True,
            )
            faq_service.add_faq(faq)

        # Get stats
        result = faq_service.get_faqs_paginated(verified=True)

        # Verify structure
        assert result.total_count >= 3
        assert hasattr(result, "faqs")
        assert hasattr(result, "page")
        assert hasattr(result, "page_size")

    def test_stats_with_date_range(self, faq_service):
        """Test stats filtering by date range."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        # Add verified FAQ with specific timestamp
        faq = FAQItem(
            question="Test question?",
            answer="Test answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=yesterday,
        )
        faq_service.add_faq(faq)

        # Get stats for date range
        result = faq_service.get_faqs_paginated(
            verified=True,
            verified_from=yesterday.isoformat(),
            verified_to=now.isoformat(),
        )

        # Should include the FAQ
        assert result.total_count >= 1

    def test_stats_by_category_breakdown(self, faq_service):
        """Test stats with category filtering."""
        # Add FAQs with different categories
        for category in ["backup", "security", "trading"]:
            faq = FAQItem(
                question=f"{category} question?",
                answer=f"{category} answer",
                category=category,
                source="manual",
                verified=True,
            )
            faq_service.add_faq(faq)

        # Get stats for specific category
        result = faq_service.get_faqs_paginated(verified=True, categories=["backup"])

        # Should only include backup FAQs
        assert all(faq.category == "backup" for faq in result.faqs)


class TestFAQTimestampIntegration:
    """Integration tests for FAQ timestamp functionality across layers."""

    def test_end_to_end_timestamp_flow(self, faq_service):
        """Test complete flow from creation to verification with timestamps."""
        # Create unverified FAQ
        faq = FAQItem(
            question="Integration test?",
            answer="Integration answer",
            category="test",
            source="manual",
            verified=False,
        )

        # Add FAQ (should auto-populate created_at, updated_at)
        added_faq = faq_service.add_faq(faq)
        assert added_faq.created_at is not None
        assert added_faq.updated_at is not None
        assert added_faq.verified_at is None

        # Verify FAQ (should set verified_at)
        all_faqs = faq_service.get_all_faqs()
        current_faq = next(faq for faq in all_faqs if faq.id == added_faq.id)

        updated_faq = FAQItem(
            **current_faq.model_dump(exclude={"id"}, exclude_none=False)
        )
        updated_faq.verified = True

        verified_faq = faq_service.update_faq(added_faq.id, updated_faq)
        assert verified_faq.verified_at is not None
        assert verified_faq.created_at == added_faq.created_at  # Preserved
        assert verified_faq.updated_at > added_faq.updated_at  # Updated

    def test_date_range_query_across_layers(self, faq_service):
        """Test date range filtering works from service to repository."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        # Add verified FAQ with yesterday's timestamp
        faq = FAQItem(
            question="Yesterday FAQ?",
            answer="Yesterday answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=yesterday,
        )
        faq_service.add_faq(faq)

        # Query with ISO 8601 date string
        result = faq_service.get_faqs_paginated(
            verified=True,
            verified_from=yesterday.isoformat(),
            verified_to=now.isoformat(),
        )

        # Should include the FAQ
        assert result.total_count >= 1
        assert any("Yesterday" in faq.question for faq in result.faqs)
