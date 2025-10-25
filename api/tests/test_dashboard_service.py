"""
Tests for DashboardService with configurable time periods.

This test suite covers:
- Period timestamp calculation
- Configurable trend calculations
- API endpoint with period parameters
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from app.core.config import Settings
from app.services.dashboard_service import DashboardService


@pytest.fixture
def test_settings():
    """Create test settings."""
    settings = Settings()
    settings.DATA_DIR = "/tmp/test_data"
    settings.PROMETHEUS_URL = "http://localhost:9090"
    return settings


@pytest.fixture
def dashboard_service(test_settings):
    """Create DashboardService instance."""
    return DashboardService(settings=test_settings)


class TestPeriodTimestamps:
    """Test period timestamp calculations."""

    def test_get_period_timestamps_24h(self, dashboard_service):
        """Test 24-hour period timestamp calculation."""
        now = datetime(2025, 10, 24, 12, 0, 0, tzinfo=timezone.utc)

        current_start, current_end, previous_start, previous_end = (
            dashboard_service._get_period_timestamps("24h", now=now)
        )

        # Current period: last 24 hours
        assert current_start == datetime(2025, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
        assert current_end == now

        # Previous period: 24-48 hours ago
        assert previous_start == datetime(2025, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
        assert previous_end == datetime(2025, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

    def test_get_period_timestamps_7d(self, dashboard_service):
        """Test 7-day period timestamp calculation."""
        now = datetime(2025, 10, 24, 12, 0, 0, tzinfo=timezone.utc)

        current_start, current_end, previous_start, previous_end = (
            dashboard_service._get_period_timestamps("7d", now=now)
        )

        # Current period: last 7 days
        assert current_start == datetime(2025, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
        assert current_end == now

        # Previous period: 7-14 days ago
        assert previous_start == datetime(2025, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        assert previous_end == datetime(2025, 10, 17, 12, 0, 0, tzinfo=timezone.utc)

    def test_get_period_timestamps_30d(self, dashboard_service):
        """Test 30-day period timestamp calculation."""
        now = datetime(2025, 10, 24, 12, 0, 0, tzinfo=timezone.utc)

        current_start, current_end, previous_start, previous_end = (
            dashboard_service._get_period_timestamps("30d", now=now)
        )

        # Current period: last 30 days
        assert current_start == datetime(2025, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
        assert current_end == now

        # Previous period: 30-60 days ago
        assert previous_start == datetime(2025, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
        assert previous_end == datetime(2025, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

    def test_get_period_timestamps_custom(self, dashboard_service):
        """Test custom period timestamp calculation."""
        # Custom period: Oct 15-20 (5 days)
        start_date = "2025-10-15T00:00:00Z"
        end_date = "2025-10-20T00:00:00Z"

        current_start, current_end, previous_start, previous_end = (
            dashboard_service._get_period_timestamps(
                "custom", start_date=start_date, end_date=end_date
            )
        )

        # Current period: as specified
        assert current_start == datetime(2025, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert current_end == datetime(2025, 10, 20, 0, 0, 0, tzinfo=timezone.utc)

        # Previous period: 5 days before (Oct 10-15)
        assert previous_start == datetime(2025, 10, 10, 0, 0, 0, tzinfo=timezone.utc)
        assert previous_end == datetime(2025, 10, 15, 0, 0, 0, tzinfo=timezone.utc)

    def test_get_period_timestamps_invalid_period(self, dashboard_service):
        """Test invalid period raises ValueError."""
        with pytest.raises(ValueError, match="Invalid period"):
            dashboard_service._get_period_timestamps("invalid")

    def test_get_period_timestamps_custom_missing_dates(self, dashboard_service):
        """Test custom period without dates raises ValueError."""
        with pytest.raises(ValueError, match="start_date and end_date required"):
            dashboard_service._get_period_timestamps("custom")


class TestPeriodToHours:
    """Test period to hours conversion."""

    def test_period_to_hours_24h(self, dashboard_service):
        """Test 24h converts to 24 hours."""
        assert dashboard_service._period_to_hours("24h") == 24

    def test_period_to_hours_7d(self, dashboard_service):
        """Test 7d converts to 168 hours."""
        assert dashboard_service._period_to_hours("7d") == 168

    def test_period_to_hours_30d(self, dashboard_service):
        """Test 30d converts to 720 hours."""
        assert dashboard_service._period_to_hours("30d") == 720

    def test_period_to_hours_custom(self, dashboard_service):
        """Test custom period calculates hours from date range."""
        start_date = "2025-10-15T00:00:00Z"
        end_date = "2025-10-20T00:00:00Z"

        hours = dashboard_service._period_to_hours("custom", start_date, end_date)
        assert hours == 120  # 5 days = 120 hours

    def test_period_to_hours_invalid_period(self, dashboard_service):
        """Test invalid period raises ValueError."""
        with pytest.raises(ValueError, match="Invalid period"):
            dashboard_service._period_to_hours("invalid")


class TestConfigurableTrendCalculations:
    """Test trend calculations with configurable periods."""

    @pytest.mark.asyncio
    async def test_calculate_helpful_rate_trend_7d(self, dashboard_service):
        """Test helpful rate trend calculation with 7-day period."""
        # Mock repository method
        with patch.object(
            dashboard_service.feedback_service.repository,
            "get_feedback_stats_for_period",
        ) as mock_stats:
            # Current period: 80% helpful
            # Previous period: 75% helpful
            # Expected trend: +5.0%
            mock_stats.side_effect = [
                {"total": 100, "positive": 80, "negative": 20, "helpful_rate": 0.8},
                {"total": 100, "positive": 75, "negative": 25, "helpful_rate": 0.75},
            ]

            trend = await dashboard_service._calculate_helpful_rate_trend("7d")

            assert trend == pytest.approx(5.0, rel=0.01)
            assert mock_stats.call_count == 2

    @pytest.mark.asyncio
    async def test_calculate_negative_feedback_trend_30d(self, dashboard_service):
        """Test negative feedback trend calculation with 30-day period."""
        with patch.object(
            dashboard_service.feedback_service.repository,
            "get_feedback_stats_for_period",
        ) as mock_stats:
            # Current period: 30 negative
            # Previous period: 20 negative
            # Expected trend: +50.0% (30 is 50% more than 20)
            mock_stats.side_effect = [
                {"total": 100, "positive": 70, "negative": 30, "helpful_rate": 0.7},
                {"total": 100, "positive": 80, "negative": 20, "helpful_rate": 0.8},
            ]

            trend = await dashboard_service._calculate_negative_feedback_trend("30d")

            assert trend == pytest.approx(50.0, rel=0.01)
            assert mock_stats.call_count == 2

    @pytest.mark.asyncio
    async def test_calculate_response_time_trend_custom(self, dashboard_service):
        """Test response time trend with custom period."""
        start_date = "2025-10-15T00:00:00Z"
        end_date = "2025-10-20T00:00:00Z"

        # Mock Prometheus client
        with patch.object(
            dashboard_service.prometheus_client,
            "get_response_time_trend",
            return_value=0.5,  # 0.5s slower
        ) as mock_prom:
            trend = await dashboard_service._calculate_response_time_trend(
                "custom", start_date=start_date, end_date=end_date
            )

            assert trend == 0.5
            # Should call with 120 hours (5 days)
            mock_prom.assert_called_once_with(window_hours=120)


class TestDashboardOverviewWithPeriods:
    """Test dashboard overview endpoint with different periods."""

    @pytest.mark.asyncio
    async def test_get_dashboard_overview_default_7d(self, dashboard_service):
        """Test dashboard overview defaults to 7-day period."""
        with patch.multiple(
            dashboard_service,
            _calculate_helpful_rate_trend=AsyncMock(return_value=5.0),
            _calculate_negative_feedback_trend=AsyncMock(return_value=-10.0),
            _calculate_response_time_trend=AsyncMock(return_value=0.1),
            _get_feedback_items_for_faq=AsyncMock(return_value=[]),
            _get_average_response_time=AsyncMock(return_value=2.5),
            _get_total_query_count=AsyncMock(return_value=1000),
            _get_faq_creation_stats=AsyncMock(
                return_value={
                    "total_faqs": 50,
                    "total_created_from_feedback": 25,
                    "total_manual": 25,
                }
            ),
        ):
            with patch.object(
                dashboard_service.feedback_service,
                "get_feedback_stats_enhanced",
                return_value={
                    "total_feedback": 200,
                    "helpful_rate": 0.75,
                    "negative_count": 50,
                },
            ):
                result = await dashboard_service.get_dashboard_overview()

                # Should use 7d period by default
                dashboard_service._calculate_helpful_rate_trend.assert_called_once_with(
                    "7d", None, None
                )
                dashboard_service._calculate_negative_feedback_trend.assert_called_once_with(
                    "7d", None, None
                )
                dashboard_service._calculate_response_time_trend.assert_called_once_with(
                    "7d", None, None
                )

                # Result should include period info
                assert result["period"] == "7d"
                assert "period_label" in result

    @pytest.mark.asyncio
    async def test_get_dashboard_overview_custom_period(self, dashboard_service):
        """Test dashboard overview with custom period."""
        with patch.multiple(
            dashboard_service,
            _calculate_helpful_rate_trend=AsyncMock(return_value=2.0),
            _calculate_negative_feedback_trend=AsyncMock(return_value=5.0),
            _calculate_response_time_trend=AsyncMock(return_value=-0.2),
            _get_feedback_items_for_faq=AsyncMock(return_value=[]),
            _get_average_response_time=AsyncMock(return_value=2.0),
            _get_total_query_count=AsyncMock(return_value=500),
            _get_faq_creation_stats=AsyncMock(
                return_value={
                    "total_faqs": 30,
                    "total_created_from_feedback": 15,
                    "total_manual": 15,
                }
            ),
        ):
            with patch.object(
                dashboard_service.feedback_service,
                "get_feedback_stats_enhanced",
                return_value={
                    "total_feedback": 100,
                    "helpful_rate": 0.8,
                    "negative_count": 20,
                },
            ):
                result = await dashboard_service.get_dashboard_overview(
                    period="custom",
                    start_date="2025-10-15T00:00:00Z",
                    end_date="2025-10-20T00:00:00Z",
                )

                # Should use custom period
                dashboard_service._calculate_helpful_rate_trend.assert_called_once()
                assert result["period"] == "custom"
                assert result["period_start"] == "2025-10-15T00:00:00Z"
                assert result["period_end"] == "2025-10-20T00:00:00Z"
