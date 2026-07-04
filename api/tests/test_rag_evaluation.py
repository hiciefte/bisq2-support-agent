"""Tests for RAG evaluation service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.rag.evaluation import EvaluationResult, RAGEvaluator
from tests.data.test_questions import TEST_QUESTIONS


@pytest.fixture
def mock_rag_service():
    """Create a mock RAG service."""
    mock = MagicMock()
    mock.query = AsyncMock(
        return_value={
            "answer": "This is a test answer.",
            "sources": [{"title": "Test Source", "content": "test"}],
        }
    )
    return mock


@pytest.fixture
def mock_version_detector():
    """Create a mock version detector."""
    mock = MagicMock()
    # detect_version returns (version, confidence, clarifying_question)
    mock.detect_version = AsyncMock(return_value=("Bisq 2", 0.8, None))
    return mock


@pytest.fixture
def evaluator(mock_rag_service, mock_version_detector):
    """Create evaluator with mocks."""
    return RAGEvaluator(mock_rag_service, mock_version_detector)


class TestEvaluatorInitialization:
    """Test RAGEvaluator initialization."""

    def test_init_with_rag_service(self, mock_rag_service):
        evaluator = RAGEvaluator(mock_rag_service)
        assert evaluator.rag == mock_rag_service
        assert evaluator.version_detector is None

    def test_init_with_version_detector(self, mock_rag_service, mock_version_detector):
        evaluator = RAGEvaluator(mock_rag_service, mock_version_detector)
        assert evaluator.version_detector == mock_version_detector


class TestVersionDetectionEvaluation:
    """Test version detection accuracy evaluation."""

    @pytest.mark.asyncio
    async def test_version_detection_requires_detector(self, mock_rag_service):
        evaluator = RAGEvaluator(mock_rag_service)
        with pytest.raises(ValueError, match="Version detector not provided"):
            await evaluator.run_version_detection_tests(TEST_QUESTIONS)

    @pytest.mark.asyncio
    async def test_version_detection_accuracy(self, evaluator, mock_version_detector):
        # Setup detector to return correct versions (version, confidence, clarifying_question)
        async def mock_detect(question, _history):
            if "dao" in question.lower() or "bsq" in question.lower():
                return ("Bisq 1", 0.9, None)
            elif "bisq easy" in question.lower() or "reputation" in question.lower():
                return ("Bisq 2", 0.9, None)
            else:
                return ("Bisq 2", 0.5, None)

        mock_version_detector.detect_version = mock_detect

        results = await evaluator.run_version_detection_tests(TEST_QUESTIONS[:5])

        assert isinstance(results, EvaluationResult)
        assert results.total_tests > 0
        assert 0 <= results.accuracy <= 1

    @pytest.mark.asyncio
    async def test_version_detection_unknown_handling(
        self, evaluator, mock_version_detector
    ):
        # For "Unknown" expected, should pass if confidence < 0.6
        mock_version_detector.detect_version = AsyncMock(
            return_value=("Bisq 2", 0.4, None)
        )

        test_data = [
            {"question": "How do I buy Bitcoin?", "expected_version": "Unknown"}
        ]

        results = await evaluator.run_version_detection_tests(test_data)
        assert results.passed == 1
        assert results.failed == 0

    @pytest.mark.asyncio
    async def test_version_detection_measures_latency(self, evaluator):
        results = await evaluator.run_version_detection_tests(
            [{"question": "Test?", "expected_version": "Bisq 2"}]
        )
        assert results.avg_latency_ms >= 0


class TestRAGEvaluation:
    """Test RAG response quality evaluation."""

    @pytest.mark.asyncio
    async def test_rag_test_success(self, evaluator):
        test_data = [{"question": "Test question", "expected_success": True}]

        results = await evaluator.run_rag_tests(test_data)

        assert results.total_tests == 1
        assert results.passed == 1

    @pytest.mark.asyncio
    async def test_rag_test_failure_no_sources(self, evaluator, mock_rag_service):
        mock_rag_service.query = AsyncMock(
            return_value={"answer": "Test", "sources": []}
        )

        test_data = [{"question": "Test question", "expected_success": True}]

        results = await evaluator.run_rag_tests(test_data)

        assert results.failed == 1
        assert len(results.failures) == 1

    @pytest.mark.asyncio
    async def test_rag_test_expected_failure(self, evaluator, mock_rag_service):
        mock_rag_service.query = AsyncMock(
            return_value={"answer": "Test", "sources": []}
        )

        test_data = [{"question": "Hello", "expected_success": False}]

        results = await evaluator.run_rag_tests(test_data)

        # Should pass because we expected no sources
        assert results.passed == 1

    @pytest.mark.asyncio
    async def test_rag_test_handles_exceptions(self, evaluator, mock_rag_service):
        mock_rag_service.query = AsyncMock(side_effect=Exception("Test error"))

        test_data = [{"question": "Test question", "expected_success": True}]

        results = await evaluator.run_rag_tests(test_data)

        assert results.failed == 1
        assert "error" in results.failures[0]

    @pytest.mark.asyncio
    async def test_rag_test_measures_latency(self, evaluator):
        test_data = [{"question": "Test question", "expected_success": True}]

        results = await evaluator.run_rag_tests(test_data)

        assert results.avg_latency_ms >= 0

    @pytest.mark.asyncio
    async def test_rag_test_with_conversation(self, evaluator):
        test_data = [
            {
                "conversation": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi!"},
                ],
                "question": "How are you?",
                "expected_success": True,
            }
        ]

        results = await evaluator.run_rag_tests(test_data)

        assert results.total_tests == 1


class TestEvaluationResults:
    """Test EvaluationResult dataclass."""

    def test_evaluation_result_creation(self):
        result = EvaluationResult(
            total_tests=100,
            passed=90,
            failed=10,
            accuracy=0.90,
            precision=0.85,
            recall=0.88,
            avg_latency_ms=50.0,
            failures=[{"question": "test", "error": "failed"}],
        )

        assert result.total_tests == 100
        assert result.accuracy == 0.90
        assert len(result.failures) == 1


class TestReportGeneration:
    """Test evaluation report generation."""

    def test_generate_report_basic(self, evaluator):
        results = EvaluationResult(
            total_tests=10,
            passed=9,
            failed=1,
            accuracy=0.9,
            precision=0.0,
            recall=0.0,
            avg_latency_ms=50.0,
            failures=[{"question": "test", "error": "failed"}],
        )

        report = evaluator.generate_report(results)

        assert "Total Tests: 10" in report
        assert "Passed: 9" in report
        assert "Failed: 1" in report
        assert "90.00%" in report
        assert "50.00ms" in report

    def test_generate_report_with_failures(self, evaluator):
        results = EvaluationResult(
            total_tests=10,
            passed=5,
            failed=5,
            accuracy=0.5,
            precision=0.0,
            recall=0.0,
            avg_latency_ms=100.0,
            failures=[
                {"question": "q1", "error": "error1"},
                {"question": "q2", "error": "error2"},
            ],
        )

        report = evaluator.generate_report(results)

        assert "FAILURES:" in report

    def test_generate_report_no_failures(self, evaluator):
        results = EvaluationResult(
            total_tests=10,
            passed=10,
            failed=0,
            accuracy=1.0,
            precision=0.0,
            recall=0.0,
            avg_latency_ms=25.0,
            failures=[],
        )

        report = evaluator.generate_report(results)

        assert "100.00%" in report
        assert "FAILURES:" not in report

    def test_report_limits_failures_shown(self, evaluator):
        # Create 20 failures, should only show first 10
        failures = [{"question": f"q{i}", "error": f"e{i}"} for i in range(20)]

        results = EvaluationResult(
            total_tests=20,
            passed=0,
            failed=20,
            accuracy=0.0,
            precision=0.0,
            recall=0.0,
            avg_latency_ms=100.0,
            failures=failures,
        )

        report = evaluator.generate_report(results)

        # Should contain "FAILURES:" section
        assert "FAILURES:" in report

        # Should only show first 10 failures (q0-q9), not q10-q19
        assert "q9" in report  # Last of first 10
        assert "q10" not in report  # First that should be excluded


class TestVersionDetectionPrecisionRecall:
    """Per-class precision/recall must be computed, not hardcoded 0.0."""

    @pytest.mark.asyncio
    async def test_known_confusion_matrix_yields_exact_precision_recall(
        self, mock_rag_service, mock_version_detector
    ):
        # Confusion matrix:
        #   expected Bisq 1 (3): detected [Bisq 1, Bisq 1, Bisq 2]
        #   expected Bisq 2 (2): detected [Bisq 2, Bisq 1]
        # precision(B1) = 2/3, recall(B1) = 2/3
        # precision(B2) = 1/2, recall(B2) = 1/2
        # macro precision = macro recall = (2/3 + 1/2) / 2 = 7/12
        detections = {
            "b1-a": "Bisq 1",
            "b1-b": "Bisq 1",
            "b1-c": "Bisq 2",
            "b2-a": "Bisq 2",
            "b2-b": "Bisq 1",
        }

        async def detect(question, _history):
            return (detections[question], 0.9, None)

        mock_version_detector.detect_version = detect
        evaluator = RAGEvaluator(mock_rag_service, mock_version_detector)

        test_data = [
            {"question": "b1-a", "expected_version": "Bisq 1"},
            {"question": "b1-b", "expected_version": "Bisq 1"},
            {"question": "b1-c", "expected_version": "Bisq 1"},
            {"question": "b2-a", "expected_version": "Bisq 2"},
            {"question": "b2-b", "expected_version": "Bisq 2"},
        ]

        results = await evaluator.run_version_detection_tests(test_data)

        assert results.precision == pytest.approx(7 / 12)
        assert results.recall == pytest.approx(7 / 12)

    @pytest.mark.asyncio
    async def test_perfect_detection_yields_unit_precision_recall(
        self, mock_rag_service, mock_version_detector
    ):
        mock_version_detector.detect_version = AsyncMock(
            return_value=("Bisq 2", 0.9, None)
        )
        evaluator = RAGEvaluator(mock_rag_service, mock_version_detector)

        test_data = [
            {"question": "q1", "expected_version": "Bisq 2"},
            {"question": "q2", "expected_version": "Bisq 2"},
        ]

        results = await evaluator.run_version_detection_tests(test_data)

        assert results.precision == pytest.approx(1.0)
        assert results.recall == pytest.approx(1.0)


class TestContentBasedGrading:
    """RAG grading must inspect answer text, not only source presence."""

    @pytest.mark.asyncio
    async def test_forbidden_keyword_fails_even_with_sources(
        self, evaluator, mock_rag_service
    ):
        mock_rag_service.query = AsyncMock(
            return_value={
                "answer": "In Bisq Easy you burn BSQ in the DAO to trade.",
                "sources": [{"title": "Doc", "content": "text"}],
            }
        )

        test_data = [
            {
                "question": "How does Bisq Easy work?",
                "expected_success": True,
                "forbidden_keywords": ["BSQ", "DAO"],
            }
        ]

        results = await evaluator.run_rag_tests(test_data)

        assert results.failed == 1
        assert results.passed == 0
        assert results.failures[0]["forbidden_keywords_found"] == ["BSQ", "DAO"]

    @pytest.mark.asyncio
    async def test_all_expected_keywords_present_passes(
        self, evaluator, mock_rag_service
    ):
        mock_rag_service.query = AsyncMock(
            return_value={
                "answer": "Bisq Easy uses Reputation instead of security deposits.",
                "sources": [{"title": "Doc", "content": "text"}],
            }
        )

        test_data = [
            {
                "question": "How does Bisq Easy work?",
                "expected_success": True,
                "expected_keywords": ["reputation", "bisq easy"],
            }
        ]

        results = await evaluator.run_rag_tests(test_data)

        assert results.passed == 1
        assert results.failed == 0

    @pytest.mark.asyncio
    async def test_missing_expected_keyword_fails(self, evaluator, mock_rag_service):
        mock_rag_service.query = AsyncMock(
            return_value={
                "answer": "You can trade bitcoin peer to peer.",
                "sources": [{"title": "Doc", "content": "text"}],
            }
        )

        test_data = [
            {
                "question": "How does Bisq Easy work?",
                "expected_success": True,
                "expected_keywords": ["reputation"],
            }
        ]

        results = await evaluator.run_rag_tests(test_data)

        assert results.failed == 1
        assert results.failures[0]["missing_keywords"] == ["reputation"]

    @pytest.mark.asyncio
    async def test_expected_failure_with_forbidden_keyword_is_true_negative(
        self, evaluator, mock_rag_service
    ):
        """expected_success=False + forbidden keyword in the answer means the
        prediction (failure) matches the expectation - the case must PASS.
        content_ok is already folded into predicted_success and must not be
        re-applied to the pass condition."""
        mock_rag_service.query = AsyncMock(
            return_value={
                "answer": "You burn BSQ in the DAO to trade on Bisq Easy.",
                "sources": [{"title": "Doc", "content": "text"}],
            }
        )

        test_data = [
            {
                "question": "Does Bisq Easy use the DAO?",
                "expected_success": False,
                "forbidden_keywords": ["DAO"],
            }
        ]

        results = await evaluator.run_rag_tests(test_data)

        assert results.passed == 1
        assert results.failed == 0
        assert results.failures == []

    @pytest.mark.asyncio
    async def test_legacy_case_without_keywords_passes_and_counts_shallow(
        self, evaluator
    ):
        """Datasets without keyword fields keep has_sources-only grading."""
        test_data = [{"question": "Test question", "expected_success": True}]

        results = await evaluator.run_rag_tests(test_data)

        assert results.passed == 1
        assert results.shallow_tests == 1

    @pytest.mark.asyncio
    async def test_content_checked_case_not_counted_shallow(
        self, evaluator, mock_rag_service
    ):
        mock_rag_service.query = AsyncMock(
            return_value={
                "answer": "Reputation matters.",
                "sources": [{"title": "Doc", "content": "text"}],
            }
        )

        test_data = [
            {
                "question": "Test question",
                "expected_success": True,
                "expected_keywords": ["reputation"],
            }
        ]

        results = await evaluator.run_rag_tests(test_data)

        assert results.shallow_tests == 0

    @pytest.mark.asyncio
    async def test_rag_precision_recall_computed_from_graded_outcomes(
        self, evaluator, mock_rag_service
    ):
        # Case 1: expected success, sources + clean answer -> TP
        # Case 2: expected success, sources but forbidden keyword -> FN
        # Case 3: expected failure, but sources returned -> FP
        responses = [
            {
                "answer": "Reputation based trading.",
                "sources": [{"title": "Doc", "content": "text"}],
            },
            {
                "answer": "Use the DAO to vote.",
                "sources": [{"title": "Doc", "content": "text"}],
            },
            {
                "answer": "Some hallucinated answer.",
                "sources": [{"title": "Doc", "content": "text"}],
            },
        ]
        mock_rag_service.query = AsyncMock(side_effect=responses)

        test_data = [
            {"question": "q1", "expected_success": True},
            {
                "question": "q2",
                "expected_success": True,
                "forbidden_keywords": ["DAO"],
            },
            {"question": "q3", "expected_success": False},
        ]

        results = await evaluator.run_rag_tests(test_data)

        # precision = TP / (TP + FP) = 1 / 2; recall = TP / (TP + FN) = 1 / 2
        assert results.precision == pytest.approx(0.5)
        assert results.recall == pytest.approx(0.5)
        assert results.passed == 1
        assert results.failed == 2


class TestIntegrationWithTestDataset:
    """Test evaluation with actual test dataset."""

    @pytest.mark.asyncio
    async def test_run_with_test_questions(self, evaluator):
        # Run with subset of test questions
        results = await evaluator.run_version_detection_tests(TEST_QUESTIONS[:10])

        assert results.total_tests > 0
        assert isinstance(results.accuracy, float)

    @pytest.mark.asyncio
    async def test_accuracy_threshold(self, evaluator, mock_version_detector):
        # Setup detector to be mostly correct
        call_count = [0]

        async def smart_detect(question, _history):
            call_count[0] += 1
            if "dao" in question.lower():
                return ("Bisq 1", 0.9, None)
            elif "bisq easy" in question.lower():
                return ("Bisq 2", 0.9, None)
            return ("Bisq 2", 0.5, None)

        mock_version_detector.detect_version = smart_detect

        results = await evaluator.run_version_detection_tests(TEST_QUESTIONS[:10])

        # Report should be generatable
        report = evaluator.generate_report(results)
        assert len(report) > 0
