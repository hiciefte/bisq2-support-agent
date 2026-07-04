"""Tests for consistent verified_at date-range parsing in FAQService.

Regression tests for a drift where ``get_faqs_paginated`` extended a
date-only ``verified_to`` to end-of-day while ``get_filtered_faqs`` did
not, so the admin list path and the stats/aggregation path returned
different result sets for the same date range.
"""

from datetime import datetime, timezone

import pytest
from app.models.faq import FAQItem
from app.services.faq_service import FAQService


@pytest.fixture
def service(test_settings, tmp_path):
    """FAQService backed by an isolated SQLite database."""
    test_settings.DATA_DIR = str(tmp_path)
    faq_service = FAQService(settings=test_settings)
    yield faq_service
    faq_service.repository.close()


def _add_verified_faq(service, verified_at, question="How do I trade Bitcoin?"):
    """Add a verified FAQ with a controlled verified_at timestamp."""
    return service.repository.add_faq(
        FAQItem(
            question=question,
            answer="Use the trade view to create offers",
            category="Trading",
            source="Manual",
            verified=True,
            protocol="bisq_easy",
            verified_at=verified_at,
        )
    )


class TestParseVerifiedRange:
    """Unit tests for the shared _parse_verified_range helper."""

    def test_naive_verified_to_is_extended_to_end_of_day_utc(self):
        from app.services.faq_service import _parse_verified_range

        _, verified_to = _parse_verified_range(None, "2026-07-03")

        assert verified_to == datetime(
            2026, 7, 3, 23, 59, 59, 999999, tzinfo=timezone.utc
        )

    def test_naive_verified_from_assumes_utc_without_end_of_day(self):
        from app.services.faq_service import _parse_verified_range

        verified_from, _ = _parse_verified_range("2026-07-01", None)

        assert verified_from == datetime(2026, 7, 1, tzinfo=timezone.utc)

    def test_z_suffix_is_normalized_to_utc(self):
        from app.services.faq_service import _parse_verified_range

        verified_from, verified_to = _parse_verified_range(
            "2026-07-01T08:00:00Z", "2026-07-03T12:00:00Z"
        )

        assert verified_from == datetime(2026, 7, 1, 8, tzinfo=timezone.utc)
        assert verified_to == datetime(2026, 7, 3, 12, tzinfo=timezone.utc)

    def test_timezone_aware_verified_to_is_preserved(self):
        from app.services.faq_service import _parse_verified_range

        _, verified_to = _parse_verified_range(None, "2026-07-03T12:00:00+00:00")

        assert verified_to == datetime(2026, 7, 3, 12, tzinfo=timezone.utc)

    def test_invalid_values_are_treated_as_absent(self):
        from app.services.faq_service import _parse_verified_range

        assert _parse_verified_range("not-a-date", "also-not-a-date") == (None, None)

    def test_none_values_pass_through(self):
        from app.services.faq_service import _parse_verified_range

        assert _parse_verified_range(None, None) == (None, None)


class TestVerifiedRangePathConsistency:
    """Both service paths must interpret the same date range identically."""

    def test_date_only_verified_to_includes_same_day_faqs_in_both_paths(self, service):
        _add_verified_faq(service, datetime(2026, 7, 3, 15, 30, tzinfo=timezone.utc))

        paginated = service.get_faqs_paginated(
            page=1,
            page_size=10,
            verified_from="2026-07-01",
            verified_to="2026-07-03",
        )
        filtered = service.get_filtered_faqs(
            verified_from="2026-07-01", verified_to="2026-07-03"
        )

        # Admin list path already included same-day FAQs
        assert paginated.total_count == 1
        # Stats/aggregation path must agree (used to drop same-day FAQs)
        assert len(filtered) == 1

    def test_paths_agree_for_timezone_aware_upper_bound(self, service):
        _add_verified_faq(service, datetime(2026, 7, 3, 15, 30, tzinfo=timezone.utc))

        bounds = {
            "verified_from": "2026-07-01T00:00:00+00:00",
            "verified_to": "2026-07-03T12:00:00+00:00",
        }
        paginated = service.get_faqs_paginated(page=1, page_size=10, **bounds)
        filtered = service.get_filtered_faqs(**bounds)

        # verified_at (15:30) is after the explicit 12:00 upper bound
        assert paginated.total_count == 0
        assert len(filtered) == 0

    def test_paths_agree_for_z_suffixed_bounds(self, service):
        _add_verified_faq(service, datetime(2026, 7, 3, 15, 30, tzinfo=timezone.utc))

        bounds = {
            "verified_from": "2026-07-01T00:00:00Z",
            "verified_to": "2026-07-03T23:59:59Z",
        }
        paginated = service.get_faqs_paginated(page=1, page_size=10, **bounds)
        filtered = service.get_filtered_faqs(**bounds)

        assert paginated.total_count == 1
        assert len(filtered) == 1
