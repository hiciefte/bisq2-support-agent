"""Tests for response_builder: build_metadata routing_reason passthrough."""

from app.channels.response_builder import build_metadata


class TestBuildMetadataRoutingReason:
    """Test routing_reason flows through build_metadata."""

    def test_routing_reason_passed_through(self):
        rag_response = {
            "rag_strategy": "retrieval",
            "model_name": "gpt-4",
            "confidence": 0.80,
            "routing_action": "auto_send",
            "routing_reason": "High confidence (80%) \u2014 3 sources found",
        }
        meta = build_metadata(rag_response, processing_time_ms=100.0)
        assert meta.routing_reason == "High confidence (80%) \u2014 3 sources found"

    def test_routing_reason_defaults_none(self):
        rag_response = {
            "rag_strategy": "retrieval",
            "model_name": "gpt-4",
        }
        meta = build_metadata(rag_response, processing_time_ms=100.0)
        assert meta.routing_reason is None
