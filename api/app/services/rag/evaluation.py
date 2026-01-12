"""Evaluate RAG system performance on labeled test data."""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Results from running evaluation suite."""

    total_tests: int
    passed: int
    failed: int
    accuracy: float
    precision: float
    recall: float
    avg_latency_ms: float
    failures: List[Dict[str, Any]]


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

        for test in test_data:
            if "expected_version" not in test:
                continue

            question = test.get("question", "")
            history = test.get("conversation", [])
            expected = test["expected_version"]

            start = time.perf_counter()
            try:
                detected, confidence, _clarifying_question = (
                    await self.version_detector.detect_version(question, history)
                )
            except Exception as e:
                failed += 1
                failures.append({"question": question, "error": str(e)})
                continue
            latency = (time.perf_counter() - start) * 1000
            latencies.append(latency)

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

        total = passed + failed
        return EvaluationResult(
            total_tests=total,
            passed=passed,
            failed=failed,
            accuracy=passed / total if total > 0 else 0,
            precision=0.0,  # TODO: Calculate per-class precision
            recall=0.0,  # TODO: Calculate per-class recall
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
            failures=failures,
        )

    async def run_rag_tests(self, test_data: List[Dict]) -> EvaluationResult:
        """Test RAG response quality."""
        passed = 0
        failed = 0
        failures = []
        latencies = []

        for test in test_data:
            question = test.get("question", "")
            history = test.get("conversation", [])
            expected_success = test.get("expected_success", True)

            start = time.perf_counter()
            try:
                response = await self.rag.query(question=question, chat_history=history)
                latency = (time.perf_counter() - start) * 1000
                latencies.append(latency)

                # Check for hallucination indicators
                answer = response.get("answer", "")
                has_sources = len(response.get("sources", [])) > 0

                if expected_success and has_sources:
                    passed += 1
                elif not expected_success and not has_sources:
                    passed += 1
                else:
                    failed += 1
                    failures.append(
                        {
                            "question": question,
                            "answer": answer[:200],
                            "has_sources": has_sources,
                            "expected_success": expected_success,
                        }
                    )

            except Exception as e:
                failed += 1
                failures.append({"question": question, "error": str(e)})

        total = passed + failed
        return EvaluationResult(
            total_tests=total,
            passed=passed,
            failed=failed,
            accuracy=passed / total if total > 0 else 0,
            precision=0.0,
            recall=0.0,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
            failures=failures,
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
            f"Avg Latency: {results.avg_latency_ms:.2f}ms",
            "",
        ]

        if results.failures:
            report.append("FAILURES:")
            for failure in results.failures[:10]:  # Show first 10
                report.append(f"  - {failure}")

        return "\n".join(report)
