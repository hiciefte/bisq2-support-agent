"""
Tests for Prometheus metrics endpoint.

Ensures that:
1. /metrics endpoint is accessible (internal-only via nginx)
2. Feedback analytics metrics are exposed and updated
3. Tor metrics are exposed
4. Metrics format is valid Prometheus format
"""

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestMetricsEndpoint:
    """Test suite for /metrics endpoint."""

    def test_metrics_endpoint_accessible(self, client):
        """Test that /metrics endpoint is accessible."""
        response = client.get("/metrics")
        assert response.status_code == 200
        # Prometheus format includes version
        assert "text/plain" in response.headers["content-type"]

    def test_metrics_prometheus_format(self, client):
        """Test that metrics are in valid Prometheus format."""
        response = client.get("/metrics")
        content = response.text

        # Check for Prometheus format markers
        assert "# HELP" in content
        assert "# TYPE" in content

        # Validate format: lines should be comments, empty, or metric lines
        for line in content.split("\n"):
            if line.strip() == "":
                continue
            if line.startswith("#"):
                continue
            # Metric line format: metric_name{labels} value timestamp
            # or: metric_name value timestamp
            # or: metric_name value
            parts = line.split()
            assert len(parts) >= 2, f"Invalid metric line: {line}"

    def test_feedback_metrics_exposed(self, client):
        """Test that feedback analytics metrics are exposed."""
        response = client.get("/metrics")
        content = response.text

        # Check for feedback metrics
        required_metrics = [
            "bisq_feedback_total",
            "bisq_feedback_helpful",
            "bisq_feedback_unhelpful",
            "bisq_feedback_helpful_rate",
        ]

        for metric in required_metrics:
            assert metric in content, f"Missing required metric: {metric}"

    def test_feedback_metrics_have_values(self, client):
        """Test that feedback metrics are updated with actual values."""
        response = client.get("/metrics")
        content = response.text

        # Extract metric values
        metrics = {}
        for line in content.split("\n"):
            if line.startswith("bisq_feedback_"):
                # Parse metric line: metric_name value
                parts = line.split()
                if len(parts) >= 2:
                    metric_name = parts[0].split("{")[0]  # Remove labels if present
                    metric_value = float(parts[1] if "{" not in parts[0] else parts[-1])
                    metrics[metric_name] = metric_value

        # Verify metrics exist
        assert "bisq_feedback_total" in metrics
        assert "bisq_feedback_helpful" in metrics
        assert "bisq_feedback_unhelpful" in metrics
        assert "bisq_feedback_helpful_rate" in metrics

        # Note: Values can be 0 if no feedback exists, which is valid
        # The important thing is the metrics are present and numeric
        assert isinstance(metrics["bisq_feedback_total"], float)

    def test_source_effectiveness_metrics_exposed(self, client):
        """Test that source effectiveness metrics are exposed with labels."""
        response = client.get("/metrics")
        content = response.text

        # Check for source metrics (these use labels)
        assert "bisq_source_total" in content
        assert "bisq_source_helpful" in content
        assert "bisq_source_helpful_rate" in content

    def test_issue_count_metrics_exposed(self, client):
        """Test that issue count metrics are exposed with labels."""
        response = client.get("/metrics")
        content = response.text

        # Check for issue metrics (these use labels)
        assert "bisq_issue_count" in content

    def test_tor_metrics_exposed(self, client):
        """Test that Tor-related metrics are exposed."""
        response = client.get("/metrics")
        content = response.text

        # Check for Tor metrics
        tor_metrics = [
            "tor_connection_status",
            "tor_hidden_service_configured",
            "tor_cookie_secure_mode",
            "tor_requests_total",
            "tor_request_duration_seconds",
        ]

        for metric in tor_metrics:
            assert metric in content, f"Missing Tor metric: {metric}"

    def test_system_metrics_exposed(self, client):
        """Test that standard system metrics are exposed."""
        response = client.get("/metrics")
        content = response.text

        # Standard Python/process metrics from prometheus_client
        # Note: Some process_ metrics may not be available in all environments
        system_metrics = [
            "python_info",
            "python_gc_",  # GC metrics are always present
        ]

        for metric in system_metrics:
            assert metric in content, f"Missing system metric: {metric}"

    def test_metrics_idempotent(self, client):
        """Test that calling /metrics multiple times doesn't break anything."""
        # Call metrics endpoint multiple times
        for _ in range(3):
            response = client.get("/metrics")
            assert response.status_code == 200

        # Verify content is still valid
        content = response.text
        assert "bisq_feedback_total" in content
        assert "tor_connection_status" in content


class TestMetricsErrorHandling:
    """Test error handling in metrics endpoint."""

    def test_metrics_endpoint_handles_errors_gracefully(self, client, monkeypatch):
        """Test that metrics endpoint continues to work even if feedback analytics fails."""
        from app.routes.admin import feedback

        # Mock get_feedback_analytics to raise an error
        async def mock_get_feedback_analytics():
            raise Exception("Test error in feedback analytics")

        monkeypatch.setattr(
            feedback, "get_feedback_analytics", mock_get_feedback_analytics
        )

        # Metrics endpoint should still return 200 with other metrics
        response = client.get("/metrics")
        assert response.status_code == 200

        content = response.text

        # System and Tor metrics should still be present
        assert "tor_connection_status" in content
        assert "python_info" in content

        # Feedback metrics might be missing or zero, but endpoint should not crash


class TestMetricsConsistency:
    """Test that metrics values are consistent and logical."""

    def test_feedback_total_equals_sum_of_helpful_and_unhelpful(self, client):
        """Test that total feedback equals helpful + unhelpful."""
        response = client.get("/metrics")
        content = response.text

        # Extract metric values
        total = None
        helpful = None
        unhelpful = None

        for line in content.split("\n"):
            if line.startswith("bisq_feedback_total "):
                total = float(line.split()[1])
            elif line.startswith("bisq_feedback_helpful "):
                helpful = float(line.split()[1])
            elif line.startswith("bisq_feedback_unhelpful "):
                unhelpful = float(line.split()[1])

        # All metrics should be present
        assert total is not None, "bisq_feedback_total not found"
        assert helpful is not None, "bisq_feedback_helpful not found"
        assert unhelpful is not None, "bisq_feedback_unhelpful not found"

        # Logical consistency: total should equal helpful + unhelpful
        assert total == helpful + unhelpful, (
            f"Inconsistent feedback counts: total={total}, "
            f"helpful={helpful}, unhelpful={unhelpful}"
        )

    def test_helpful_rate_calculation_correct(self, client):
        """Test that helpful rate is calculated correctly."""
        response = client.get("/metrics")
        content = response.text

        # Extract metric values
        total = None
        helpful = None
        rate = None

        for line in content.split("\n"):
            if line.startswith("bisq_feedback_total "):
                total = float(line.split()[1])
            elif line.startswith("bisq_feedback_helpful "):
                helpful = float(line.split()[1])
            elif line.startswith("bisq_feedback_helpful_rate "):
                rate = float(line.split()[1])

        assert total is not None
        assert helpful is not None
        assert rate is not None

        # Calculate expected rate (as percentage)
        if total > 0:
            expected_rate = (helpful / total) * 100
            assert (
                abs(rate - expected_rate) < 0.01
            ), f"Incorrect helpful rate: expected={expected_rate}, actual={rate}"
        else:
            # If no feedback, rate should be 0
            assert rate == 0.0
