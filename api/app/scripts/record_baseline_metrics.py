#!/usr/bin/env python3
"""
Record baseline RAGAS metrics for the current RAG system.

This script queries the current Qdrant-based RAG system with baseline
test samples and computes RAGAS evaluation metrics.

Usage:
    python -m api.app.scripts.record_baseline_metrics [--samples N] [--output PATH]

Requires:
    - ragas>=0.1.21
    - datasets>=2.21.0
    - Running API service (docker compose up api)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Default paths
DEFAULT_SAMPLES_PATH = (
    "api/data/evaluation/matrix_realistic_qa_samples_30_20260211.json"
)
DEFAULT_OUTPUT_PATH = "api/data/evaluation/baseline_scores.json"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


async def query_rag_system(
    client: httpx.AsyncClient, question: str, timeout: float = 60.0
) -> dict[str, Any]:
    """Query the RAG system via HTTP API.

    Args:
        client: HTTP client
        question: Question to ask
        timeout: Request timeout in seconds

    Returns:
        Dict with answer, sources, and response_time
    """
    try:
        response = await client.post(
            f"{API_BASE_URL}/chat/query",
            json={"question": question, "chat_history": []},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException:
        logger.warning(f"Timeout querying: {question[:50]}...")
        return {"answer": "", "sources": [], "error": "timeout"}
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error {e.response.status_code}: {question[:50]}...")
        return {"answer": "", "sources": [], "error": str(e)}
    except Exception as e:
        logger.error(f"Error querying: {e}")
        return {"answer": "", "sources": [], "error": str(e)}


def compute_ragas_metrics(
    questions: list[str],
    ground_truths: list[str],
    answers: list[str],
    contexts: list[list[str]],
) -> dict[str, float]:
    """Compute RAGAS evaluation metrics.

    Args:
        questions: List of questions
        ground_truths: List of expected answers
        answers: List of generated answers
        contexts: List of retrieved context chunks per question

    Returns:
        Dict with metric scores
    """
    try:
        from datasets import Dataset  # type: ignore[import-not-found]
        from langchain_openai import OpenAIEmbeddings  # type: ignore[import-not-found]
        from ragas import evaluate  # type: ignore[import-not-found]

        # Import metrics - handle both old and new API
        try:
            # New API (ragas >= 0.2)
            from ragas.metrics import (
                AnswerRelevancy,
                ContextPrecision,
                ContextRecall,
                Faithfulness,
            )

            metrics = [
                ContextPrecision(),
                ContextRecall(),
                Faithfulness(),
                AnswerRelevancy(),
            ]
        except ImportError:
            # Old API (ragas < 0.2)
            from ragas.metrics import (  # type: ignore[import-not-found]
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )

            metrics = [
                context_precision,
                context_recall,
                faithfulness,
                answer_relevancy,
            ]

        # Create dataset in RAGAS format
        data = {
            "question": questions,
            "ground_truth": ground_truths,
            "answer": answers,
            "contexts": contexts,
        }
        dataset = Dataset.from_dict(data)

        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

        # Run evaluation
        logger.info("Computing RAGAS metrics...")
        result = evaluate(dataset, metrics=metrics, embeddings=embeddings)

        # Extract scores - handle EvaluationResult object
        import math

        def get_score(key: str) -> float:
            # Try different ways to access the result
            try:
                # Try dict-like access
                if hasattr(result, "__getitem__"):
                    val = result[key]
                elif hasattr(result, key):
                    val = getattr(result, key)
                elif hasattr(result, "scores") and key in result.scores:
                    val = result.scores[key]
                else:
                    logger.warning(f"Could not find metric {key} in result")
                    return 0.0

                # Handle list vs scalar
                if isinstance(val, list):
                    valid_vals = [v for v in val if v is not None and not math.isnan(v)]
                    return sum(valid_vals) / len(valid_vals) if valid_vals else 0.0

                # Handle nan
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    logger.warning(f"Metric {key} is NaN, returning 0.0")
                    return 0.0

                return float(val)
            except (KeyError, TypeError, AttributeError) as e:
                logger.warning(f"Error accessing metric {key}: {e}")
                return 0.0

        scores = {
            "context_precision": get_score("context_precision"),
            "context_recall": get_score("context_recall"),
            "faithfulness": get_score("faithfulness"),
            "answer_relevancy": get_score("answer_relevancy"),
        }

        # Log the raw result for debugging
        logger.info(f"RAGAS result type: {type(result)}")
        logger.info(f"RAGAS result: {result}")

        return scores

    except ImportError as e:
        logger.error(f"RAGAS not installed: {e}")
        logger.error("Install with: pip install ragas datasets")
        return compute_simple_metrics(questions, ground_truths, answers, contexts)
    except Exception as e:
        logger.error(f"RAGAS evaluation failed: {e}")
        logger.warning("Falling back to simple metrics")
        return compute_simple_metrics(questions, ground_truths, answers, contexts)


def compute_simple_metrics(
    questions: list[str],
    ground_truths: list[str],
    answers: list[str],
    contexts: list[list[str]],
) -> dict[str, float]:
    """Compute simple fallback metrics when RAGAS is not available.

    Uses basic text similarity as a proxy for quality metrics.
    """
    from difflib import SequenceMatcher

    logger.warning("Using simple metrics (RAGAS not available)")

    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    # Answer relevancy: how similar is answer to ground truth
    answer_scores = [
        similarity(ans, gt) for ans, gt in zip(answers, ground_truths) if ans and gt
    ]

    # Context recall: does any context chunk contain key terms from ground truth
    context_scores = []
    for ctx_list, gt in zip(contexts, ground_truths):
        if not ctx_list or not gt:
            context_scores.append(0.0)
            continue
        gt_words = set(gt.lower().split())
        max_overlap = 0.0
        for ctx in ctx_list:
            ctx_words = set(ctx.lower().split())
            overlap = len(gt_words & ctx_words) / len(gt_words) if gt_words else 0
            max_overlap = max(max_overlap, overlap)
        context_scores.append(max_overlap)

    return {
        "context_precision": (
            sum(context_scores) / len(context_scores) if context_scores else 0.0
        ),
        "context_recall": (
            sum(context_scores) / len(context_scores) if context_scores else 0.0
        ),
        "faithfulness": 0.5,  # Cannot compute without RAGAS
        "answer_relevancy": (
            sum(answer_scores) / len(answer_scores) if answer_scores else 0.0
        ),
        "_fallback_metrics": True,
    }


async def run_evaluation(
    samples_path: str, output_path: str, max_samples: int | None = None
) -> dict[str, Any]:
    """Run baseline evaluation.

    Args:
        samples_path: Path to baseline samples JSON
        output_path: Path to save results
        max_samples: Optional limit on number of samples

    Returns:
        Evaluation results dict
    """
    # Load samples
    with open(samples_path) as f:
        samples = json.load(f)

    if max_samples:
        samples = samples[:max_samples]

    logger.info(f"Loaded {len(samples)} baseline samples")

    # Query RAG system for each sample
    questions = []
    ground_truths = []
    answers = []
    contexts = []
    individual_results = []

    async with httpx.AsyncClient() as client:
        # Check if API is running
        try:
            health = await client.get(f"{API_BASE_URL}/health", timeout=10.0)
            health.raise_for_status()
            health_data = health.json()
            logger.info(f"API health check passed: {health_data.get('status')}")
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to API at {API_BASE_URL}: {e}")
            logger.error("Start the API with: docker compose up api")
            sys.exit(1)
        except httpx.TimeoutException as e:
            logger.error(f"API timeout at {API_BASE_URL}: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"API error at {API_BASE_URL}: {type(e).__name__}: {e}")
            logger.error("Start the API with: docker compose up api")
            sys.exit(1)

        for i, sample in enumerate(samples):
            question = sample["question"]
            ground_truth = sample["ground_truth"]

            # Add protocol context to prevent version clarification requests
            protocol = sample.get("metadata", {}).get("protocol", "")
            if protocol == "bisq_easy":
                question_with_context = f"{question} (I'm using Bisq Easy / Bisq 2)"
            elif protocol == "multisig_v1":
                question_with_context = f"{question} (I'm using Bisq 1)"
            else:
                question_with_context = question

            logger.info(f"[{i+1}/{len(samples)}] Querying: {question[:60]}...")

            start_time = time.time()
            result = await query_rag_system(client, question_with_context)
            elapsed = time.time() - start_time

            answer = result.get("answer", "")
            sources = result.get("sources", [])

            # Extract context strings from sources
            ctx = []
            for src in sources:
                if isinstance(src, dict):
                    content = src.get("content", src.get("page_content", ""))
                    if content:
                        ctx.append(content)
                elif isinstance(src, str):
                    ctx.append(src)

            questions.append(question)
            ground_truths.append(ground_truth)
            answers.append(answer)
            contexts.append(ctx if ctx else [""])  # RAGAS requires non-empty

            individual_results.append(
                {
                    "question": question,
                    "ground_truth": ground_truth,
                    "answer": answer,
                    "contexts": ctx,
                    "response_time": elapsed,
                    "error": result.get("error"),
                }
            )

            # Small delay to avoid overwhelming the API
            await asyncio.sleep(0.5)

    # Compute metrics
    metrics = compute_ragas_metrics(questions, ground_truths, answers, contexts)

    # Compute average response time
    response_times = [
        r["response_time"] for r in individual_results if r["response_time"]
    ]
    avg_response_time = (
        sum(response_times) / len(response_times) if response_times else 0
    )

    # Build results
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": "qdrant",
        "samples_count": len(samples),
        "metrics": metrics,
        "avg_response_time": avg_response_time,
        "individual_results": individual_results,
    }

    # Save results
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"Saved results to {output_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("BASELINE EVALUATION RESULTS")
    print("=" * 60)
    print(f"Samples evaluated: {len(samples)}")
    print(f"Avg response time: {avg_response_time:.2f}s")
    print()
    print("RAGAS Metrics:")
    for metric, value in metrics.items():
        if not metric.startswith("_"):
            print(f"  {metric}: {value:.4f}")
    print("=" * 60)

    return results


def main():
    global API_BASE_URL

    parser = argparse.ArgumentParser(description="Record baseline RAGAS metrics")
    parser.add_argument(
        "--samples",
        type=str,
        default=DEFAULT_SAMPLES_PATH,
        help=f"Path to baseline samples JSON (default: {DEFAULT_SAMPLES_PATH})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to save results (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Maximum number of samples to evaluate (default: all)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=API_BASE_URL,
        help=f"API base URL (default: {API_BASE_URL})",
    )

    args = parser.parse_args()
    API_BASE_URL = args.api_url

    asyncio.run(run_evaluation(args.samples, args.output, args.max_samples))


if __name__ == "__main__":
    main()
