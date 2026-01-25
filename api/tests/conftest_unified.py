"""
Pytest fixtures for the Unified FAQ Training Pipeline.

This module provides fixtures for testing the unified training system
that merges both Bisq 2 API and Matrix chat sources.

Fixtures:
- sample_bisq_conversation: Sample Bisq API conversation for testing
- sample_matrix_answer: Sample Matrix staff answer for testing
- sample_matrix_thread: Multi-turn Matrix conversation thread
- mock_comparison_result: Mock comparison result with various score levels
- unified_repository: UnifiedFAQCandidateRepository instance
- mock_rag_service: Mocked RAG service for testing
"""

import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# === Data Classes for Testing ===


@dataclass
class MockComparisonResult:
    """Mock comparison result for testing."""

    question_event_id: str
    embedding_similarity: float
    factual_alignment: float
    contradiction_score: float
    completeness: float
    hallucination_risk: float
    llm_reasoning: str
    final_score: float
    routing: str
    is_calibration: bool
    evaluation_status: str = "completed"


@dataclass
class MockQAPair:
    """Mock Q&A pair from Matrix export parser."""

    question_event_id: str
    question_text: str
    question_sender: str
    answer_event_id: str
    answer_text: str
    answer_sender: str
    thread_depth: int = 1
    has_followup: bool = False


# === Sample Data Fixtures ===


@pytest.fixture
def sample_bisq_conversation() -> Dict[str, Any]:
    """Sample Bisq API conversation for testing.

    Returns a complete conversation thread with multiple messages
    simulating a typical Bisq 2 support interaction.
    """
    return {
        "thread_id": "test-thread-123",
        "channel_id": "support-general",
        "timestamp": "2025-01-15T10:00:00Z",
        "messages": [
            {
                "msg_id": "msg1",
                "content": "How do I start trading on Bisq Easy?",
                "sender": "user123",
                "is_support": False,
                "timestamp": "2025-01-15T10:00:00Z",
            },
            {
                "msg_id": "msg2",
                "content": (
                    "To start trading on Bisq Easy, go to the Trade tab and select "
                    "'Trade wizard'. You can browse existing offers or create your own. "
                    "The maximum trade amount is $600 for new users."
                ),
                "sender": "support-staff",
                "is_support": True,
                "referenced_msg_id": "msg1",
                "timestamp": "2025-01-15T10:05:00Z",
            },
            {
                "msg_id": "msg3",
                "content": "What payment methods are available?",
                "sender": "user123",
                "is_support": False,
                "referenced_msg_id": "msg2",
                "timestamp": "2025-01-15T10:10:00Z",
            },
            {
                "msg_id": "msg4",
                "content": (
                    "Available payment methods depend on your region. Common options "
                    "include bank transfer, Revolut, and various national payment apps."
                ),
                "sender": "support-staff",
                "is_support": True,
                "referenced_msg_id": "msg3",
                "timestamp": "2025-01-15T10:15:00Z",
            },
        ],
    }


@pytest.fixture
def sample_matrix_answer() -> Dict[str, Any]:
    """Sample Matrix staff answer for testing.

    Returns a single staff answer event with all required fields.
    """
    return {
        "event_id": "$matrix_answer_123:matrix.org",
        "staff_answer": (
            "To trade on Bisq Easy, first ensure you have the latest version "
            "of Bisq 2 installed. Then navigate to Trade > Trade Wizard. "
            "New users can trade up to $600 per trade without providing ID."
        ),
        "reply_to_event_id": "$matrix_question_456:matrix.org",
        "staff_sender": "@bisq-support:matrix.org",
        "room_id": "!support-room:matrix.org",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def sample_matrix_question() -> Dict[str, Any]:
    """Sample Matrix user question for testing."""
    return {
        "event_id": "$matrix_question_456:matrix.org",
        "content": "How do I trade on Bisq Easy without identity verification?",
        "sender": "@user:matrix.org",
        "room_id": "!support-room:matrix.org",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def sample_matrix_thread() -> List[Dict[str, Any]]:
    """Multi-turn Matrix conversation thread for testing.

    Simulates a back-and-forth support conversation with follow-ups.
    """
    base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "event_id": "$q1:matrix.org",
            "type": "m.room.message",
            "sender": "@user:matrix.org",
            "origin_server_ts": int(base_time.timestamp() * 1000),
            "content": {
                "msgtype": "m.text",
                "body": "My trade has been stuck for 2 hours. What should I do?",
            },
        },
        {
            "event_id": "$a1:matrix.org",
            "type": "m.room.message",
            "sender": "@support:matrix.org",
            "origin_server_ts": int(base_time.timestamp() * 1000) + 300_000,  # +5min
            "content": {
                "msgtype": "m.text",
                "body": "Can you share your trade ID so I can look into it?",
                "m.relates_to": {"m.in_reply_to": {"event_id": "$q1:matrix.org"}},
            },
        },
        {
            "event_id": "$q2:matrix.org",
            "type": "m.room.message",
            "sender": "@user:matrix.org",
            "origin_server_ts": int(base_time.timestamp() * 1000) + 600_000,  # +10min
            "content": {
                "msgtype": "m.text",
                "body": "The trade ID is abc123-def456",
                "m.relates_to": {"m.in_reply_to": {"event_id": "$a1:matrix.org"}},
            },
        },
        {
            "event_id": "$a2:matrix.org",
            "type": "m.room.message",
            "sender": "@support:matrix.org",
            "origin_server_ts": int(base_time.timestamp() * 1000) + 900_000,  # +15min
            "content": {
                "msgtype": "m.text",
                "body": (
                    "I see the issue. The seller hasn't confirmed payment yet. "
                    "The standard timeout is 24 hours. If it's not resolved by then, "
                    "you can open a dispute using the 'Open Support Ticket' button."
                ),
                "m.relates_to": {"m.in_reply_to": {"event_id": "$q2:matrix.org"}},
            },
        },
    ]


@pytest.fixture
def mock_comparison_result_high() -> MockComparisonResult:
    """Mock comparison result with high score (AUTO_APPROVE)."""
    return MockComparisonResult(
        question_event_id="$test_question_high",
        embedding_similarity=0.95,
        factual_alignment=0.98,
        contradiction_score=0.02,
        completeness=0.95,
        hallucination_risk=0.03,
        llm_reasoning="Excellent alignment between staff and generated answers.",
        final_score=0.95,
        routing="AUTO_APPROVE",
        is_calibration=False,
    )


@pytest.fixture
def mock_comparison_result_medium() -> MockComparisonResult:
    """Mock comparison result with medium score (SPOT_CHECK)."""
    return MockComparisonResult(
        question_event_id="$test_question_medium",
        embedding_similarity=0.85,
        factual_alignment=0.82,
        contradiction_score=0.10,
        completeness=0.80,
        hallucination_risk=0.12,
        llm_reasoning="Good alignment with minor differences in completeness.",
        final_score=0.82,
        routing="SPOT_CHECK",
        is_calibration=True,
    )


@pytest.fixture
def mock_comparison_result_low() -> MockComparisonResult:
    """Mock comparison result with low score (FULL_REVIEW)."""
    return MockComparisonResult(
        question_event_id="$test_question_low",
        embedding_similarity=0.60,
        factual_alignment=0.55,
        contradiction_score=0.30,
        completeness=0.50,
        hallucination_risk=0.35,
        llm_reasoning="Significant differences - staff provides more context.",
        final_score=0.55,
        routing="FULL_REVIEW",
        is_calibration=True,
    )


# === Repository Fixtures ===


@pytest.fixture
def unified_temp_dir():
    """Create a temporary directory for unified repository tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def unified_repository(unified_temp_dir):
    """Create a UnifiedFAQCandidateRepository instance.

    Note: This fixture will fail until the repository is implemented.
    The tests are written TDD-style before implementation.
    """
    try:
        from app.services.training.unified_repository import (
            UnifiedFAQCandidateRepository,
        )

        return UnifiedFAQCandidateRepository(unified_temp_dir)
    except ImportError:
        pytest.skip("UnifiedFAQCandidateRepository not yet implemented")


# === Service Mocks ===


@pytest.fixture
def mock_rag_service():
    """Create a mocked RAG service for testing.

    Returns a mock that simulates RAG query responses without
    making actual API calls.
    """
    mock = MagicMock()
    mock.query = AsyncMock(
        return_value={
            "response": (
                "To trade on Bisq Easy, navigate to Trade > Trade Wizard. "
                "New users have a limit of $600 per trade. No identity verification "
                "is required for trades under this limit."
            ),
            "sources": [
                {"type": "wiki", "title": "Bisq Easy Trading Guide"},
                {"type": "faq", "title": "Trading Limits"},
            ],
            "retrieval_confidence": 0.85,
        }
    )
    mock.setup = AsyncMock()
    return mock


@pytest.fixture
def mock_faq_service():
    """Create a mocked FAQ service for testing."""
    mock = MagicMock()
    mock.add_faq = MagicMock(
        return_value=MagicMock(id="faq_test_123", question="Test Q", answer="Test A")
    )
    return mock


@pytest.fixture
def mock_comparison_engine():
    """Create a mocked comparison engine for testing."""
    mock = MagicMock()
    mock.compare = AsyncMock(
        return_value=MockComparisonResult(
            question_event_id="$test",
            embedding_similarity=0.85,
            factual_alignment=0.90,
            contradiction_score=0.05,
            completeness=0.80,
            hallucination_risk=0.10,
            llm_reasoning="Good alignment",
            final_score=0.85,
            routing="SPOT_CHECK",
            is_calibration=True,
        )
    )
    mock.is_calibration_mode = False
    mock.calibration_count = 0
    mock.calibration_samples_required = 100
    return mock


@pytest.fixture
def mock_substantive_filter():
    """Create a mocked substantive filter for testing."""
    mock = MagicMock()
    mock.filter_single = AsyncMock(return_value=(True, None))
    mock.filter_answers = AsyncMock(
        return_value=(
            [
                MockQAPair(
                    question_event_id="$q1",
                    question_text="How do I trade?",
                    question_sender="@user:matrix.org",
                    answer_event_id="$a1",
                    answer_text="Go to Trade > Trade Wizard...",
                    answer_sender="@support:matrix.org",
                )
            ],
            [],
        )
    )
    return mock


# === Pipeline Service Fixtures ===


@pytest_asyncio.fixture
async def unified_pipeline_service(
    test_settings,
    mock_rag_service,
    mock_faq_service,
):
    """Create a UnifiedPipelineService instance for testing.

    Note: This fixture will fail until the service is implemented.
    """
    try:
        from app.services.training.unified_pipeline_service import (
            UnifiedPipelineService,
        )

        service = UnifiedPipelineService(
            settings=test_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
        )
        return service
    except ImportError:
        pytest.skip("UnifiedPipelineService not yet implemented")


# === Sample Unified Candidates ===


@pytest.fixture
def sample_unified_candidate_bisq() -> Dict[str, Any]:
    """Sample unified candidate from Bisq 2 source."""
    return {
        "source": "bisq2",
        "source_event_id": "msg_bisq_123",
        "source_timestamp": datetime.now(timezone.utc).isoformat(),
        "question_text": "How do I start trading on Bisq Easy?",
        "staff_answer": (
            "To start trading, go to Trade > Trade Wizard. "
            "New users can trade up to $600 per trade."
        ),
        "generated_answer": (
            "Navigate to the Trade tab and select Trade Wizard to begin. "
            "The limit for new users is $600."
        ),
        "staff_sender": "support-staff",
        "embedding_similarity": 0.92,
        "factual_alignment": 0.95,
        "contradiction_score": 0.03,
        "completeness": 0.90,
        "hallucination_risk": 0.05,
        "final_score": 0.92,
        "llm_reasoning": "High alignment, both mention Trade Wizard and $600 limit.",
        "routing": "AUTO_APPROVE",
        "review_status": "pending",
        "is_calibration_sample": False,
    }


@pytest.fixture
def sample_unified_candidate_matrix() -> Dict[str, Any]:
    """Sample unified candidate from Matrix source."""
    return {
        "source": "matrix",
        "source_event_id": "$matrix_answer_789:matrix.org",
        "source_timestamp": datetime.now(timezone.utc).isoformat(),
        "question_text": "What is the trade timeout period?",
        "staff_answer": (
            "The standard timeout is 24 hours. If the trade isn't completed "
            "by then, you can open a dispute."
        ),
        "generated_answer": (
            "Trades have a 24-hour timeout. After this period, you may "
            "open a support ticket."
        ),
        "staff_sender": "@support:matrix.org",
        "embedding_similarity": 0.88,
        "factual_alignment": 0.85,
        "contradiction_score": 0.08,
        "completeness": 0.82,
        "hallucination_risk": 0.10,
        "final_score": 0.83,
        "llm_reasoning": "Good alignment, minor wording differences.",
        "routing": "SPOT_CHECK",
        "review_status": "pending",
        "is_calibration_sample": True,
    }


# === Helper Functions ===


def create_mock_shadow_response(
    event_id: str,
    question_text: str,
    messages: Optional[List[Dict]] = None,
) -> MagicMock:
    """Create a mock ShadowResponse for testing."""
    mock = MagicMock()
    mock.id = event_id
    mock.synthesized_question = question_text
    mock.messages = messages or [
        {"content": question_text, "sender_type": "user"},
    ]
    mock.detected_version = "bisq2"
    mock.created_at = datetime.now(timezone.utc)
    return mock
