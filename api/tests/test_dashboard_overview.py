from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dashboard_overview_feedback_items_have_string_explanation(test_settings):
    """
    Regression test: feedback items selected for FAQ creation may have no explicit
    explanation (but still qualify via has_no_source_response). Dashboard overview
    must still validate against FeedbackForFAQItem.explanation: str.
    """
    from app.models.feedback import DashboardOverviewResponse, FeedbackItem
    from app.services.dashboard_service import DashboardService

    svc = DashboardService(settings=test_settings)

    # Stub dependencies to keep this test self-contained.
    svc._get_faq_creation_stats = AsyncMock(  # type: ignore[assignment]
        return_value={
            "total_faqs": 0,
            "total_created_from_feedback": 0,
            "total_manual": 0,
        }
    )
    svc._get_total_query_count = AsyncMock(return_value=0)  # type: ignore[assignment]
    svc._calculate_helpful_rate_trend = AsyncMock(return_value=0.0)  # type: ignore[assignment]
    svc._calculate_response_time_trend = AsyncMock(return_value=0.0)  # type: ignore[assignment]
    svc._get_average_response_time = AsyncMock(return_value=1.0)  # type: ignore[assignment]

    # Feedback item: negative, explanation=None, qualifies via has_no_source_response.
    item = FeedbackItem(
        message_id="m1",
        question="How do I do X?",
        answer="I don't have enough information in the sources to answer reliably.",
        rating=0,
        timestamp="2025-01-01T00:00:00Z",
        metadata={"issues": ["missing_information"]},
        processed=0,
    )
    svc.feedback_service.get_negative_feedback_for_faq_creation = MagicMock(  # type: ignore[assignment]
        return_value=[item]
    )

    # Period feedback stats are read via repository call on a thread.
    svc.feedback_service.repository.get_feedback_stats_for_period = MagicMock(  # type: ignore[assignment]
        return_value={"helpful_rate": 0.5}
    )
    svc.feedback_service.get_total_feedback_count = MagicMock(return_value=0)  # type: ignore[assignment]

    data = await svc.get_dashboard_overview(period="30d")

    # Must validate response model (no 500 on /admin/dashboard/overview).
    parsed = DashboardOverviewResponse(**data)
    assert parsed.feedback_items_for_faq_count == 1
    assert parsed.feedback_items_for_faq[0].explanation

    # Cleanup singleton-backed DB connections to avoid ResourceWarning noise.
    try:
        svc.faq_service.repository.close()
    except Exception:
        pass
    try:
        from app.db.database import get_database

        get_database().reset()
    except Exception:
        pass
