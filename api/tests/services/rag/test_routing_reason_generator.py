"""Tests for RoutingReasonGenerator: human-readable routing explanations."""

import pytest
from app.services.rag.routing_reason_generator import RoutingReasonGenerator


@pytest.fixture()
def generator():
    return RoutingReasonGenerator()


class TestRoutingReasonGenerator:
    """Test routing reason generation from confidence, action, and source count."""

    def test_auto_send_high_confidence(self, generator):
        reason = generator.generate(confidence=0.96, action="auto_send", num_sources=3)
        assert "high confidence" in reason.lower()

    def test_needs_human_low_confidence(self, generator):
        reason = generator.generate(
            confidence=0.35, action="needs_human", num_sources=1
        )
        assert "low confidence" in reason.lower()

    def test_needs_human_no_sources(self, generator):
        reason = generator.generate(
            confidence=0.20, action="needs_human", num_sources=0
        )
        assert "no" in reason.lower() and "source" in reason.lower()

    def test_queue_medium_moderate(self, generator):
        reason = generator.generate(
            confidence=0.78, action="queue_medium", num_sources=2
        )
        assert "moderate" in reason.lower() or "review" in reason.lower()

    def test_reason_is_nonempty_string(self, generator):
        reason = generator.generate(confidence=0.50, action="auto_send", num_sources=1)
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_reason_max_length_500(self, generator):
        reason = generator.generate(
            confidence=0.50, action="needs_human", num_sources=0
        )
        assert len(reason) <= 500

    def test_includes_confidence_percentage(self, generator):
        reason = generator.generate(confidence=0.96, action="auto_send", num_sources=2)
        assert "96%" in reason

    def test_includes_source_count(self, generator):
        reason = generator.generate(confidence=0.85, action="auto_send", num_sources=3)
        assert "3" in reason and "source" in reason.lower()

    def test_with_detected_version(self, generator):
        reason = generator.generate(
            confidence=0.90,
            action="auto_send",
            num_sources=2,
            detected_version="Bisq 2",
            version_confidence=0.95,
        )
        assert "Bisq 2" in reason

    def test_unknown_action_fallback(self, generator):
        reason = generator.generate(
            confidence=0.50, action="unknown_action", num_sources=1
        )
        assert isinstance(reason, str)
        assert len(reason) > 0
