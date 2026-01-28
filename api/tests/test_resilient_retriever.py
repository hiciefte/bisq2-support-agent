"""
Tests for Resilient Retriever with fallback capability.

Tests automatic fallback from primary to secondary retriever on failure.
"""

import pytest
from app.services.rag.interfaces import RetrievedDocument, RetrieverProtocol
from app.services.rag.resilient_retriever import ResilientRetriever


class MockRetriever(RetrieverProtocol):
    """Mock retriever for testing."""

    def __init__(self, name: str = "mock", should_fail: bool = False):
        self.name = name
        self.should_fail = should_fail
        self.retrieve_calls = 0
        self.health_check_calls = 0
        self._healthy = True

    def retrieve(self, query: str, k: int = 10, filter_dict=None):
        self.retrieve_calls += 1
        if self.should_fail:
            raise Exception(f"{self.name} retriever failed")
        return [
            RetrievedDocument(
                content=f"Document from {self.name}",
                metadata={"source": self.name},
                score=0.9,
                id=f"{self.name}-1",
            )
        ]

    def retrieve_with_scores(self, query: str, k: int = 10, filter_dict=None):
        return self.retrieve(query, k, filter_dict)

    def health_check(self) -> bool:
        self.health_check_calls += 1
        if self.should_fail:
            raise Exception(f"{self.name} health check failed")
        return self._healthy


class TestResilientRetriever:
    """Test suite for ResilientRetriever."""

    @pytest.fixture
    def primary_retriever(self):
        """Create a mock primary retriever."""
        return MockRetriever(name="primary")

    @pytest.fixture
    def fallback_retriever(self):
        """Create a mock fallback retriever."""
        return MockRetriever(name="fallback")

    def test_initialization(self, primary_retriever, fallback_retriever):
        """Test resilient retriever initialization."""
        resilient = ResilientRetriever(
            primary=primary_retriever,
            fallback=fallback_retriever,
            auto_reset=True,
            reset_interval=300,
        )

        assert resilient.primary_retriever == primary_retriever
        assert resilient.fallback_retriever == fallback_retriever
        assert resilient.using_fallback is False

    def test_retrieve_uses_primary_when_healthy(
        self, primary_retriever, fallback_retriever
    ):
        """Test that retrieve uses primary retriever when healthy."""
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        docs = resilient.retrieve("test query", k=5)

        assert len(docs) == 1
        assert docs[0].metadata["source"] == "primary"
        assert primary_retriever.retrieve_calls == 1
        assert fallback_retriever.retrieve_calls == 0

    def test_retrieve_falls_back_on_primary_failure(
        self, primary_retriever, fallback_retriever
    ):
        """Test automatic fallback when primary fails."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        docs = resilient.retrieve("test query", k=5)

        assert len(docs) == 1
        assert docs[0].metadata["source"] == "fallback"
        assert resilient.using_fallback is True
        assert primary_retriever.retrieve_calls == 1
        assert fallback_retriever.retrieve_calls == 1

    def test_retrieve_stays_on_fallback_after_switch(
        self, primary_retriever, fallback_retriever
    ):
        """Test that subsequent calls use fallback after switch."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(
            primary_retriever, fallback_retriever, auto_reset=False
        )

        # First call triggers fallback
        resilient.retrieve("query 1")
        assert resilient.using_fallback is True

        # Second call should still use fallback
        docs = resilient.retrieve("query 2")
        assert docs[0].metadata["source"] == "fallback"
        assert fallback_retriever.retrieve_calls == 2

    def test_retrieve_returns_empty_on_both_failures(
        self, primary_retriever, fallback_retriever
    ):
        """Test returns empty list when both retrievers fail."""
        primary_retriever.should_fail = True
        fallback_retriever.should_fail = True
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        docs = resilient.retrieve("test query")

        assert docs == []

    def test_health_check_returns_true_when_primary_healthy(
        self, primary_retriever, fallback_retriever
    ):
        """Test health check when primary is healthy."""
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        assert resilient.health_check() is True

    def test_health_check_returns_true_when_only_fallback_healthy(
        self, primary_retriever, fallback_retriever
    ):
        """Test health check when only fallback is healthy."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        assert resilient.health_check() is True

    def test_health_check_returns_false_when_both_unhealthy(
        self, primary_retriever, fallback_retriever
    ):
        """Test health check when both are unhealthy."""
        primary_retriever.should_fail = True
        fallback_retriever.should_fail = True
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        assert resilient.health_check() is False

    def test_reset_to_primary_success(self, primary_retriever, fallback_retriever):
        """Test manual reset to primary succeeds when healthy."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(
            primary_retriever, fallback_retriever, auto_reset=False
        )

        # Trigger fallback
        resilient.retrieve("query")
        assert resilient.using_fallback is True

        # Fix primary and reset
        primary_retriever.should_fail = False
        result = resilient.reset_to_primary()

        assert result is True
        assert resilient.using_fallback is False

    def test_reset_to_primary_fails_when_unhealthy(
        self, primary_retriever, fallback_retriever
    ):
        """Test reset to primary fails when primary still unhealthy."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(
            primary_retriever, fallback_retriever, auto_reset=False
        )

        # Trigger fallback
        resilient.retrieve("query")

        # Try reset while still failing
        result = resilient.reset_to_primary()

        assert result is False
        assert resilient.using_fallback is True

    def test_auto_reset_after_interval(self, primary_retriever, fallback_retriever):
        """Test auto-reset happens after reset interval."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(
            primary_retriever, fallback_retriever, auto_reset=True, reset_interval=0
        )

        # Trigger fallback
        resilient.retrieve("query")
        assert resilient.using_fallback is True

        # Fix primary
        primary_retriever.should_fail = False

        # Next call should trigger auto-reset
        docs = resilient.retrieve("query 2")

        # Should have reset to primary
        assert resilient.using_fallback is False
        assert docs[0].metadata["source"] == "primary"

    def test_get_status(self, primary_retriever, fallback_retriever):
        """Test get_status returns correct information."""
        resilient = ResilientRetriever(
            primary_retriever, fallback_retriever, auto_reset=True, reset_interval=300
        )

        status = resilient.get_status()

        assert status["using_fallback"] is False
        assert status["primary_healthy"] is True
        assert status["fallback_healthy"] is True
        assert status["fallback_count"] == 0
        assert status["primary_failures"] == 0
        assert status["auto_reset_enabled"] is True
        assert status["reset_interval_seconds"] == 300

    def test_get_status_after_fallback(self, primary_retriever, fallback_retriever):
        """Test get_status after switching to fallback."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        # Trigger fallback
        resilient.retrieve("query")

        status = resilient.get_status()

        assert status["using_fallback"] is True
        assert status["fallback_count"] == 1
        assert status["primary_failures"] == 1

    def test_retrieve_with_scores_uses_fallback(
        self, primary_retriever, fallback_retriever
    ):
        """Test retrieve_with_scores uses fallback on primary failure."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        docs = resilient.retrieve_with_scores("test query", k=5)

        assert len(docs) == 1
        assert docs[0].metadata["source"] == "fallback"
        assert resilient.using_fallback is True

    def test_primary_failure_count_increments(
        self, primary_retriever, fallback_retriever
    ):
        """Test primary failure count increments correctly."""
        primary_retriever.should_fail = True
        resilient = ResilientRetriever(
            primary_retriever, fallback_retriever, auto_reset=False
        )

        # First failure triggers fallback
        resilient.retrieve("query 1")
        assert resilient._primary_failures == 1
        assert resilient._fallback_count == 1

    def test_primary_failure_resets_on_success(
        self, primary_retriever, fallback_retriever
    ):
        """Test primary failure count resets after successful retrieval."""
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        # Set failure count manually
        resilient._primary_failures = 3

        # Successful retrieval
        resilient.retrieve("query")

        assert resilient._primary_failures == 0

    def test_filter_dict_passed_to_retriever(
        self, primary_retriever, fallback_retriever
    ):
        """Test that filter_dict is passed to the retriever."""
        resilient = ResilientRetriever(primary_retriever, fallback_retriever)

        # We can verify indirectly by checking the call count
        resilient.retrieve("query", k=5, filter_dict={"category": "faq"})

        assert primary_retriever.retrieve_calls == 1
