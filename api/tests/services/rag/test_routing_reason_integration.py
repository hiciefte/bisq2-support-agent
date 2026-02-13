"""Test routing_reason is present in the RAG service return dict."""

from app.services.rag.routing_reason_generator import RoutingReasonGenerator


class TestRoutingReasonInRAGResponse:
    """Verify RoutingReasonGenerator is available on RAG service."""

    def test_rag_service_has_routing_reason_generator(self, rag_service):
        """SimplifiedRAGService should have a routing_reason_generator attribute."""
        assert hasattr(rag_service, "routing_reason_generator")
        assert isinstance(rag_service.routing_reason_generator, RoutingReasonGenerator)
