"""Tests for EscalationMetrics model and DashboardService.get_escalation_metrics()."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.feedback import EscalationMetrics


class TestEscalationMetricsModel:
    """Test EscalationMetrics pydantic model with computed rate."""

    def test_rate_computed_from_counts(self):
        """escalation_rate = (queue_medium + needs_human) / total * 100."""
        m = EscalationMetrics(
            auto_send_count=85,
            queue_medium_count=5,
            needs_human_count=10,
        )
        assert m.total_routing_decisions == 100
        assert m.escalation_rate == 15.0

    def test_zero_total_zero_rate(self):
        """No routing decisions -> 0% rate."""
        m = EscalationMetrics()
        assert m.total_routing_decisions == 0
        assert m.escalation_rate == 0.0

    def test_all_fields_present(self):
        """All expected fields exist."""
        m = EscalationMetrics(
            auto_send_count=50,
            queue_medium_count=30,
            needs_human_count=20,
        )
        assert hasattr(m, "total_routing_decisions")
        assert hasattr(m, "auto_send_count")
        assert hasattr(m, "queue_medium_count")
        assert hasattr(m, "needs_human_count")
        assert hasattr(m, "escalation_rate")
        assert m.escalation_rate == 50.0

    def test_all_auto_send_zero_rate(self):
        """100% auto-send -> 0% escalation rate."""
        m = EscalationMetrics(
            auto_send_count=200,
            queue_medium_count=0,
            needs_human_count=0,
        )
        assert m.escalation_rate == 0.0


class TestDashboardEscalationMetrics:
    """Test DashboardService.get_escalation_metrics()."""

    @pytest.mark.asyncio
    async def test_returns_metrics_from_prometheus(self):
        """get_escalation_metrics queries Prometheus and returns model."""
        from app.services.dashboard_service import DashboardService

        mock_settings = MagicMock()
        mock_settings.FEEDBACK_DIR_PATH = "/tmp/feedback"
        mock_settings.DATA_DIR = "/tmp/data"
        mock_settings.PROMETHEUS_URL = "http://localhost:9090"

        with patch.object(DashboardService, "__init__", lambda self, **kw: None):
            svc = DashboardService.__new__(DashboardService)
            svc.prometheus_client = AsyncMock()
            # Simulate Prometheus returning routing decision counts by action label
            svc.prometheus_client.query = AsyncMock(
                return_value={
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [
                            {"metric": {"action": "auto_send"}, "value": [0, "850"]},
                            {"metric": {"action": "queue_medium"}, "value": [0, "50"]},
                            {"metric": {"action": "needs_human"}, "value": [0, "100"]},
                        ],
                    },
                }
            )

            result = await svc.get_escalation_metrics()
            assert isinstance(result, EscalationMetrics)
            assert result.auto_send_count == 850
            assert result.queue_medium_count == 50
            assert result.needs_human_count == 100
            assert result.escalation_rate == 15.0

    @pytest.mark.asyncio
    async def test_prometheus_unavailable_returns_zeros(self):
        """When Prometheus is down, return empty metrics."""
        from app.services.dashboard_service import DashboardService

        with patch.object(DashboardService, "__init__", lambda self, **kw: None):
            svc = DashboardService.__new__(DashboardService)
            svc.prometheus_client = AsyncMock()
            svc.prometheus_client.query = AsyncMock(return_value=None)

            result = await svc.get_escalation_metrics()
            assert isinstance(result, EscalationMetrics)
            assert result.total_routing_decisions == 0
            assert result.escalation_rate == 0.0
