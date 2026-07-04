"""Evaluate RAG system performance on labeled test data."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Results from running evaluation suite.

    Attributes:
        total_tests: Number of graded test cases
        passed: Number of passing cases
        failed: Number of failing cases
        accuracy: passed / total
        precision: Version detection: macro-averaged one-vs-rest precision
            over concrete version classes. RAG tests: binary precision where
            the positive class is "system produced a grounded, content-valid
            answer".
        recall: Same semantics as precision, for recall.
        avg_latency_ms: Mean per-case latency in milliseconds
        failures: Per-case failure details
        shallow_tests: RAG tests graded WITHOUT content checks (legacy cases
            with no expected_keywords/forbidden_keywords); such cases only
            validate source presence.
    """

    total_tests: int
    passed: int
    failed: int
    accuracy: float
    precision: float
    recall: float
    avg_latency_ms: float
    failures: List[Dict[str, Any]]
    shallow_tests: int = field(default=0)


def _macro_precision_recall(
    confusion: List[Tuple[str, Optional[str]]],
) -> Tuple[float, float]:
    """Compute macro-averaged one-vs-rest precision/recall.

    Args:
        confusion: List of (expected_class, detected_class) pairs. A detected
            class of None means no prediction was produced (counts as a false
            negative for the expected class).

    Returns:
        (macro_precision, macro_recall). Classes with no predictions or no
        instances contribute 0.0 (zero-division convention).
    """
    if not confusion:
        return 0.0, 0.0

    classes = {expected for expected, _ in confusion} | {
        detected for _, detected in confusion if detected is not None
    }
    precisions: List[float] = []
    recalls: List[float] = []
    for cls in classes:
        tp = sum(1 for exp, det in confusion if exp == cls and det == cls)
        fp = sum(1 for exp, det in confusion if exp != cls and det == cls)
        fn = sum(1 for exp, det in confusion if exp == cls and det != cls)
        precisions.append(tp / (tp + fp) if (tp + fp) else 0.0)
        recalls.append(tp / (tp + fn) if (tp + fn) else 0.0)

    return sum(precisions) / len(precisions), sum(recalls) / len(recalls)


class RAGEvaluator:
    """Evaluate RAG system performance on labeled test data."""

    def __init__(self, rag_service, version_detector=None):
        self.rag = rag_service
        self.version_detector = version_detector

    async def run_version_detection_tests(
        self, test_data: List[Dict]
    ) -> EvaluationResult:
        """Test version detection accuracy."""
        if not self.version_detector:
            raise ValueError("Version detector not provided")

        passed = 0
        failed = 0
        failures = []
        latencies = []
        # (expected, detected) pairs for concrete version classes only.
        # "Unknown" (confidence-calibration check) and "General" (auto-pass)
        # have pass semantics that do not map to class-prediction correctness.
        confusion: List[Tuple[str, Optional[str]]] = []

        for test in test_data:
            if "expected_version" not in test:
                continue

            question = test.get("question", "")
            history = test.get("conversation", [])
            expected = test["expected_version"]
            is_concrete_class = expected not in ("Unknown", "General")

            start = time.perf_counter()
            detected = None
            confidence = 0.0
            try:
                detected, confidence, _clarifying_question = (
                    await self.version_detector.detect_version(question, history)
                )
            except Exception as e:
                failed += 1
                failures.append({"question": question, "error": str(e)})
                if is_concrete_class:
                    confusion.append((expected, None))
                continue
            finally:
                # Always capture latency, even on exception
                latency = (time.perf_counter() - start) * 1000
                latencies.append(latency)

            if is_concrete_class:
                confusion.append((expected, detected))

            # Handle "Unknown" expected as either version with low confidence
            if expected == "Unknown":
                if confidence < 0.6:
                    passed += 1
                else:
                    failed += 1
                    failures.append(
                        {
                            "question": question,
                            "expected": expected,
                            "detected": detected,
                            "confidence": confidence,
                        }
                    )
            elif expected == "General":
                # General questions can be answered by any version
                passed += 1
            elif detected == expected:
                passed += 1
            else:
                failed += 1
                failures.append(
                    {
                        "question": question,
                        "expected": expected,
                        "detected": detected,
                        "confidence": confidence,
                    }
                )

        precision, recall = _macro_precision_recall(confusion)
        total = passed + failed
        return EvaluationResult(
            total_tests=total,
            passed=passed,
            failed=failed,
            accuracy=passed / total if total > 0 else 0,
            precision=precision,
            recall=recall,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
            failures=failures,
        )

    @staticmethod
    def _grade_answer_content(
        test: Dict, answer: str
    ) -> Tuple[bool, bool, Dict[str, List[str]]]:
        """Grade answer text against per-case keyword expectations.

        Supports optional test-case keys:
        - expected_keywords: all must appear in the answer (case-insensitive)
        - forbidden_keywords: none may appear (e.g. Bisq 1 terms in a
          Bisq Easy answer)

        Returns:
            (content_ok, content_checked, detail) where content_checked is
            False for legacy cases without keyword constraints (graded
            "shallow", i.e. source presence only) and detail lists the
            offending keywords.
        """
        expected_keywords = test.get("expected_keywords") or []
        forbidden_keywords = test.get("forbidden_keywords") or []
        content_checked = bool(expected_keywords or forbidden_keywords)

        answer_lower = answer.lower()
        missing = [kw for kw in expected_keywords if kw.lower() not in answer_lower]
        found_forbidden = [
            kw for kw in forbidden_keywords if kw.lower() in answer_lower
        ]

        content_ok = not missing and not found_forbidden
        detail: Dict[str, List[str]] = {}
        if missing:
            detail["missing_keywords"] = missing
        if found_forbidden:
            detail["forbidden_keywords_found"] = found_forbidden
        return content_ok, content_checked, detail

    async def run_rag_tests(self, test_data: List[Dict]) -> EvaluationResult:
        """Test RAG response quality.

        Grading combines source presence with content checks: a case with
        correct sources but a content violation (missing expected keyword or
        forbidden keyword present) FAILS. Legacy cases without keyword fields
        keep the original has_sources-only grading and are counted in
        shallow_tests.
        """
        passed = 0
        failed = 0
        shallow = 0
        failures = []
        latencies = []
        # Binary confusion counts: positive = "system produced a grounded,
        # content-valid answer" (has sources AND content checks pass).
        true_positives = 0
        false_positives = 0
        false_negatives = 0

        for test in test_data:
            question = test.get("question", "")
            history = test.get("conversation", [])
            expected_success = test.get("expected_success", True)

            start = time.perf_counter()
            try:
                response = await self.rag.query(question=question, chat_history=history)

                # Check for hallucination indicators
                answer = response.get("answer", "")
                has_sources = len(response.get("sources", [])) > 0

                content_ok, content_checked, content_detail = (
                    self._grade_answer_content(test, answer)
                )
                if not content_checked:
                    shallow += 1

                predicted_success = has_sources and content_ok
                if expected_success and predicted_success:
                    true_positives += 1
                elif not expected_success and predicted_success:
                    false_positives += 1
                elif expected_success and not predicted_success:
                    false_negatives += 1

                if predicted_success == expected_success and content_ok:
                    passed += 1
                else:
                    failed += 1
                    failure: Dict[str, Any] = {
                        "question": question,
                        "answer": answer[:200],
                        "has_sources": has_sources,
                        "expected_success": expected_success,
                    }
                    failure.update(content_detail)
                    failures.append(failure)

            except Exception as e:
                failed += 1
                if expected_success:
                    false_negatives += 1
                failures.append({"question": question, "error": str(e)})
            finally:
                # Always capture latency, even on exception
                latency = (time.perf_counter() - start) * 1000
                latencies.append(latency)

        predicted_positive = true_positives + false_positives
        expected_positive = true_positives + false_negatives
        total = passed + failed
        return EvaluationResult(
            total_tests=total,
            passed=passed,
            failed=failed,
            accuracy=passed / total if total > 0 else 0,
            precision=(
                true_positives / predicted_positive if predicted_positive else 0.0
            ),
            recall=true_positives / expected_positive if expected_positive else 0.0,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
            failures=failures,
            shallow_tests=shallow,
        )

    def generate_report(self, results: EvaluationResult) -> str:
        """Generate human-readable evaluation report."""
        report = [
            "=" * 50,
            "RAG EVALUATION REPORT",
            "=" * 50,
            f"Total Tests: {results.total_tests}",
            f"Passed: {results.passed}",
            f"Failed: {results.failed}",
            f"Accuracy: {results.accuracy:.2%}",
            f"Precision: {results.precision:.2%}",
            f"Recall: {results.recall:.2%}",
            f"Avg Latency: {results.avg_latency_ms:.2f}ms",
        ]

        if results.shallow_tests:
            report.append(f"Shallow Tests (no content checks): {results.shallow_tests}")

        report.append("")

        if results.failures:
            report.append("FAILURES:")
            for failure in results.failures[:10]:  # Show first 10
                report.append(f"  - {failure}")

        return "\n".join(report)
