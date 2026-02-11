#!/usr/bin/env python3
"""
Run RAGAS evaluation for the current RAG system.

This script queries the RAG system (with configurable backend) and computes
RAGAS evaluation metrics for comparison with baseline results.

Usage:
    python -m api.app.scripts.run_ragas_evaluation [--backend qdrant] [--samples N]

Requires:
    - ragas>=0.2 (handles both new class-based API and older functional API)
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
DEFAULT_OUTPUT_PATH = "api/data/evaluation/new_scores.json"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DEFAULT_BYPASS_HOOKS = ["escalation"]


async def query_rag_system(
    client: httpx.AsyncClient,
    question: str,
    *,
    bypass_hooks: list[str] | None = None,
    timeout: float = 60.0,
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
        payload: dict[str, Any] = {"question": question, "chat_history": []}
        if bypass_hooks:
            payload["bypass_hooks"] = bypass_hooks

        response = await client.post(
            f"{API_BASE_URL}/chat/query",
            json=payload,
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
        logger.exception(f"Error querying: {e}")
        return {"answer": "", "sources": [], "error": str(e)}


def compute_ragas_metrics(
    questions: list[str],
    ground_truths: list[str],
    answers: list[str],
    contexts: list[list[str]],
    *,
    metric_names: list[str] | None = None,
    ragas_timeout: int | None = None,
    ragas_max_retries: int | None = None,
    ragas_max_wait: int | None = None,
    ragas_max_workers: int | None = None,
    ragas_batch_size: int | None = None,
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
    scores, _per_sample = compute_ragas_metrics_detailed(
        questions,
        ground_truths,
        answers,
        contexts,
        metric_names=metric_names,
        ragas_timeout=ragas_timeout,
        ragas_max_retries=ragas_max_retries,
        ragas_max_wait=ragas_max_wait,
        ragas_max_workers=ragas_max_workers,
        ragas_batch_size=ragas_batch_size,
    )
    return scores


def compute_ragas_metrics_detailed(
    questions: list[str],
    ground_truths: list[str],
    answers: list[str],
    contexts: list[list[str]],
    *,
    metric_names: list[str] | None = None,
    ragas_timeout: int | None = None,
    ragas_max_retries: int | None = None,
    ragas_max_wait: int | None = None,
    ragas_max_workers: int | None = None,
    ragas_batch_size: int | None = None,
) -> tuple[dict[str, float], list[dict[str, float | None]]]:
    """Compute RAGAS metrics and per-sample scores.

    Returns:
        (aggregate_scores, per_sample_scores)

    Notes:
        - The exact structure of RAGAS EvaluationResult differs by version.
          We prefer `result.to_pandas()` when available for stable per-row access.
    """
    try:
        from datasets import Dataset  # type: ignore[import-not-found]
        from langchain_openai import OpenAIEmbeddings  # type: ignore[import-not-found]
        from ragas import evaluate  # type: ignore[import-not-found]
        from ragas.run_config import RunConfig  # type: ignore[import-not-found]

        # Import metrics - handle both old and new API
        try:
            # New API (ragas >= 0.2)
            from ragas.metrics import (
                AnswerRelevancy,
                ContextPrecision,
                ContextRecall,
                Faithfulness,
            )

            available = {
                "context_precision": ContextPrecision,
                "context_recall": ContextRecall,
                "faithfulness": Faithfulness,
                "answer_relevancy": AnswerRelevancy,
            }

            requested = (
                [m.strip() for m in metric_names if m.strip()]
                if metric_names is not None
                else list(available.keys())
            )
            unknown = sorted(set(requested) - set(available.keys()))
            if unknown:
                raise ValueError(f"Unknown RAGAS metrics requested: {unknown}")

            metrics = [available[m]() for m in requested]
        except ImportError:
            # Old API (ragas < 0.2)
            from ragas.metrics import (  # type: ignore[import-not-found]
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )

            available = {
                "context_precision": context_precision,
                "context_recall": context_recall,
                "faithfulness": faithfulness,
                "answer_relevancy": answer_relevancy,
            }
            requested = (
                [m.strip() for m in metric_names if m.strip()]
                if metric_names is not None
                else list(available.keys())
            )
            unknown = sorted(set(requested) - set(available.keys()))
            if unknown:
                raise ValueError(f"Unknown RAGAS metrics requested: {unknown}")
            metrics = [available[m] for m in requested]

        # Create dataset in RAGAS format
        data = {
            "question": questions,
            "ground_truth": ground_truths,
            "answer": answers,
            "contexts": contexts,
        }
        dataset = Dataset.from_dict(data)

        # Provide embeddings explicitly. RAGAS may otherwise default to an embeddings
        # implementation that lacks `embed_query()` in our dependency set, causing
        # very slow retries and/or metric failures (answer_relevancy often ends up 0.0).
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

        run_config = None
        if any(
            v is not None
            for v in (
                ragas_timeout,
                ragas_max_retries,
                ragas_max_wait,
                ragas_max_workers,
            )
        ):
            # Fall back to RAGAS defaults for unspecified values.
            run_config = RunConfig(
                timeout=ragas_timeout if ragas_timeout is not None else 180,
                max_retries=ragas_max_retries if ragas_max_retries is not None else 10,
                max_wait=ragas_max_wait if ragas_max_wait is not None else 60,
                max_workers=ragas_max_workers if ragas_max_workers is not None else 16,
            )

        # Run evaluation
        logger.info("Computing RAGAS metrics...")
        result = evaluate(
            dataset,
            metrics=metrics,
            embeddings=embeddings,
            run_config=run_config,
            batch_size=ragas_batch_size,
        )

        import math

        # Extract per-sample scores.
        per_sample: list[dict[str, float | None]] = []
        # Normalize metric names we expect to appear in the result table.
        requested_metrics = (
            [m.strip() for m in metric_names if m.strip()]
            if metric_names is not None
            else [
                "context_precision",
                "context_recall",
                "faithfulness",
                "answer_relevancy",
            ]
        )

        try:
            if hasattr(result, "to_pandas"):
                df = result.to_pandas()
                for i in range(len(questions)):
                    row: dict[str, float | None] = {}
                    for m in requested_metrics:
                        if m in df.columns:
                            v = df.iloc[i][m]
                            if v is None or (isinstance(v, float) and math.isnan(v)):
                                row[m] = None
                            else:
                                row[m] = float(v)
                    per_sample.append(row)
            elif hasattr(result, "scores") and isinstance(result.scores, list):
                # RAGAS sometimes exposes per-row dicts here.
                for i in range(len(questions)):
                    raw = result.scores[i] if i < len(result.scores) else {}
                    row = {}
                    if isinstance(raw, dict):
                        for m in requested_metrics:
                            v = raw.get(m)
                            if v is None or (isinstance(v, float) and math.isnan(v)):
                                row[m] = None
                            else:
                                try:
                                    row[m] = float(v)
                                except Exception:
                                    row[m] = None
                    per_sample.append(row)
            else:
                per_sample = [{} for _ in range(len(questions))]
        except Exception:
            logger.exception("Failed to extract per-sample RAGAS scores")
            per_sample = [{} for _ in range(len(questions))]

        def get_score(key: str) -> float:
            try:
                # Prefer averaging per-sample scores (more robust across RAGAS versions).
                vals = [
                    r.get(key)
                    for r in per_sample
                    if r.get(key) is not None and not math.isnan(float(r.get(key)))  # type: ignore[arg-type]
                ]
                if vals:
                    return float(sum(float(v) for v in vals) / len(vals))

                if hasattr(result, "__getitem__"):
                    val = result[key]
                elif hasattr(result, key):
                    val = getattr(result, key)
                elif hasattr(result, "scores") and key in result.scores:
                    val = result.scores[key]
                else:
                    logger.warning(f"Could not find metric {key} in result")
                    return 0.0

                if isinstance(val, list):
                    valid_vals = [v for v in val if v is not None and not math.isnan(v)]
                    return sum(valid_vals) / len(valid_vals) if valid_vals else 0.0

                if val is None or (isinstance(val, float) and math.isnan(val)):
                    logger.warning(f"Metric {key} is NaN, returning 0.0")
                    return 0.0

                return float(val)
            except (KeyError, TypeError, AttributeError) as e:
                logger.warning(f"Error accessing metric {key}: {e}")
                return 0.0

        score_keys = requested_metrics
        scores = {k: get_score(k) for k in score_keys}

        logger.info(f"RAGAS result type: {type(result)}")
        logger.info(f"RAGAS result: {result}")

        return scores, per_sample

    except ImportError as e:
        logger.error(f"RAGAS not installed: {e}")
        logger.error("Install with: pip install ragas datasets")
        return compute_simple_metrics(questions, ground_truths, answers, contexts), [
            {} for _ in range(len(questions))
        ]
    except Exception as e:
        logger.exception(f"RAGAS evaluation failed: {e}")
        logger.warning("Falling back to simple metrics")
        return compute_simple_metrics(questions, ground_truths, answers, contexts), [
            {} for _ in range(len(questions))
        ]


def compute_simple_metrics(
    questions: list[str],
    ground_truths: list[str],
    answers: list[str],
    contexts: list[list[str]],
) -> dict[str, float]:
    """Compute simple fallback metrics when RAGAS is not available."""
    from difflib import SequenceMatcher

    logger.warning("Using simple metrics (RAGAS not available)")

    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    answer_scores = [
        similarity(ans, gt)
        for ans, gt in zip(answers, ground_truths, strict=False)
        if ans and gt
    ]

    context_scores = []
    for ctx_list, gt in zip(contexts, ground_truths, strict=False):
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
        "faithfulness": 0.5,
        "answer_relevancy": (
            sum(answer_scores) / len(answer_scores) if answer_scores else 0.0
        ),
        "_fallback_metrics": True,
    }


def _load_evaluation_samples(samples_path: str) -> list[dict[str, Any]]:
    """Load and validate evaluation sample records.

    Expected format: list of dicts with at least `question` and `ground_truth`.
    """
    with open(samples_path) as f:
        raw = json.load(f)

    # Guard against accidentally passing an evaluation result artifact as --samples.
    if isinstance(raw, dict):
        if "individual_results" in raw:
            logger.error(
                "Samples file appears to be an evaluation *result* JSON "
                "(contains 'individual_results')."
            )
            logger.error(
                "Use --score-existing for result files, or pass a sample list JSON."
            )
        else:
            logger.error(
                "Samples file must be a JSON list of sample objects, got JSON object."
            )
        sys.exit(1)

    if not isinstance(raw, list):
        logger.error("Samples file must be a JSON list, got %s", type(raw).__name__)
        sys.exit(1)

    samples: list[dict[str, Any]] = []
    prepopulated_contexts = 0
    for idx, sample in enumerate(raw):
        if not isinstance(sample, dict):
            logger.error(
                "Invalid sample at index %d: expected object, got %s",
                idx,
                type(sample).__name__,
            )
            sys.exit(1)
        if "question" not in sample or "ground_truth" not in sample:
            logger.error(
                "Invalid sample at index %d: missing required fields "
                "'question' and/or 'ground_truth'",
                idx,
            )
            sys.exit(1)

        sample_contexts = sample.get("contexts", [])
        if isinstance(sample_contexts, list) and any(
            str(c).strip() for c in sample_contexts
        ):
            prepopulated_contexts += 1

        samples.append(sample)

    if prepopulated_contexts > 0:
        logger.warning(
            "Sample file contains pre-populated contexts for %d samples. "
            "These are ignored during retrieval evaluation; contexts come from live API retrieval.",
            prepopulated_contexts,
        )

    return samples


async def run_evaluation(
    samples_path: str,
    output_path: str,
    backend: str,
    max_samples: int | None = None,
    simple_metrics: bool = False,
    metric_names: list[str] | None = None,
    ragas_timeout: int | None = None,
    ragas_max_retries: int | None = None,
    ragas_max_wait: int | None = None,
    ragas_max_workers: int | None = None,
    ragas_batch_size: int | None = None,
    bypass_hooks: list[str] | None = None,
) -> dict[str, Any]:
    """Run evaluation with specified backend.

    Args:
        samples_path: Path to baseline samples JSON
        output_path: Path to save results
        backend: Retriever backend name (qdrant)
        max_samples: Optional limit on number of samples

    Returns:
        Evaluation results dict
    """
    # Load samples
    samples_file = Path(samples_path)
    if not samples_file.exists():
        logger.error(f"Samples file not found: {samples_path}")
        logger.error(
            "Generate samples first with: python -m api.app.scripts.record_baseline_metrics"
        )
        sys.exit(1)

    samples = _load_evaluation_samples(samples_path)

    if max_samples:
        samples = samples[:max_samples]

    logger.info(f"Loaded {len(samples)} samples for evaluation")
    logger.info(f"Backend: {backend}")

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

            # Log retriever info if available
            if "rag" in health_data:
                rag_info = health_data["rag"]
                logger.info(
                    f"RAG retriever: {rag_info.get('retriever_backend', 'unknown')}"
                )
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to API at {API_BASE_URL}: {e}")
            logger.error("Start the API with: docker compose up api")
            sys.exit(1)
        except Exception as e:
            logger.error(f"API error: {type(e).__name__}: {e}")
            sys.exit(1)

        for i, sample in enumerate(samples):
            question = sample["question"]
            ground_truth = sample["ground_truth"]

            # Add protocol context
            protocol = sample.get("metadata", {}).get("protocol", "")
            if protocol == "bisq_easy":
                question_with_context = f"{question} (I'm using Bisq Easy / Bisq 2)"
            elif protocol == "multisig_v1":
                question_with_context = f"{question} (I'm using Bisq 1)"
            else:
                question_with_context = question

            logger.info(f"[{i+1}/{len(samples)}] Querying: {question[:60]}...")

            start_time = time.time()
            result = await query_rag_system(
                client,
                question_with_context,
                bypass_hooks=bypass_hooks,
            )
            elapsed = time.time() - start_time

            answer = result.get("answer", "")
            sources = result.get("sources", [])

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
            contexts.append(ctx if ctx else [""])

            individual_results.append(
                {
                    "question": question,
                    "ground_truth": ground_truth,
                    "answer": answer,
                    "contexts": ctx,
                    "metadata": sample.get("metadata", {}),
                    "response_time": elapsed,
                    "error": result.get("error"),
                }
            )

            await asyncio.sleep(0.5)

    # Compute metrics
    per_sample_metrics: list[dict[str, float | None]] = [
        {} for _ in range(len(samples))
    ]
    if simple_metrics:
        metrics = compute_simple_metrics(questions, ground_truths, answers, contexts)
    else:
        metrics, per_sample_metrics = compute_ragas_metrics_detailed(
            questions,
            ground_truths,
            answers,
            contexts,
            metric_names=metric_names,
            ragas_timeout=ragas_timeout,
            ragas_max_retries=ragas_max_retries,
            ragas_max_wait=ragas_max_wait,
            ragas_max_workers=ragas_max_workers,
            ragas_batch_size=ragas_batch_size,
        )

    # Attach per-sample scores (when available) so we can pinpoint regressions.
    for i, r in enumerate(individual_results):
        r["ragas"] = per_sample_metrics[i] if i < len(per_sample_metrics) else {}

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
        "system": backend,
        "samples_count": len(samples),
        "metrics": metrics,
        "per_sample_metrics_available": any(bool(x) for x in per_sample_metrics),
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
    print(f"EVALUATION RESULTS ({backend.upper()})")
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


async def run_evaluation_from_existing(
    input_results_path: str,
    output_path: str,
    backend: str,
    *,
    simple_metrics: bool = False,
    metric_names: list[str] | None = None,
    ragas_timeout: int | None = None,
    ragas_max_retries: int | None = None,
    ragas_max_wait: int | None = None,
    ragas_max_workers: int | None = None,
    ragas_batch_size: int | None = None,
) -> dict[str, Any]:
    """Compute (and attach) RAGAS metrics from a previously saved evaluation JSON.

    This does not query the running RAG system. It re-scores the stored
    (question, ground_truth, answer, contexts) tuples so we can compare runs
    apples-to-apples under the same RAGAS configuration.
    """
    input_path = Path(input_results_path)
    if not input_path.exists():
        logger.error(f"Input results file not found: {input_results_path}")
        sys.exit(1)

    with open(input_results_path) as f:
        data = json.load(f)

    individual_results = list(data.get("individual_results") or [])
    if not individual_results:
        logger.error(
            "Input results JSON has no individual_results; cannot compute per-sample metrics."
        )
        sys.exit(1)

    questions: list[str] = []
    ground_truths: list[str] = []
    answers: list[str] = []
    contexts: list[list[str]] = []

    for r in individual_results:
        questions.append(r.get("question", ""))
        ground_truths.append(r.get("ground_truth", ""))
        answers.append(r.get("answer", ""))
        ctx = r.get("contexts") or []
        if not isinstance(ctx, list):
            ctx = [str(ctx)]
        ctx = [c for c in (str(x) for x in ctx) if c]
        contexts.append(ctx if ctx else [""])

    per_sample_metrics: list[dict[str, float | None]] = [
        {} for _ in range(len(individual_results))
    ]
    if simple_metrics:
        metrics = compute_simple_metrics(questions, ground_truths, answers, contexts)
    else:
        metrics, per_sample_metrics = compute_ragas_metrics_detailed(
            questions,
            ground_truths,
            answers,
            contexts,
            metric_names=metric_names,
            ragas_timeout=ragas_timeout,
            ragas_max_retries=ragas_max_retries,
            ragas_max_wait=ragas_max_wait,
            ragas_max_workers=ragas_max_workers,
            ragas_batch_size=ragas_batch_size,
        )

    for i, r in enumerate(individual_results):
        r["ragas"] = per_sample_metrics[i] if i < len(per_sample_metrics) else {}

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": backend,
        "samples_count": len(individual_results),
        "metrics": metrics,
        "per_sample_metrics_available": any(bool(x) for x in per_sample_metrics),
        "avg_response_time": data.get("avg_response_time", 0.0),
        "input_results_path": input_results_path,
        "individual_results": individual_results,
    }

    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"Saved re-scored results to {output_path}")
    return results


def main():
    global API_BASE_URL

    parser = argparse.ArgumentParser(description="Run RAGAS evaluation")
    parser.add_argument(
        "--samples",
        type=str,
        default=DEFAULT_SAMPLES_PATH,
        help=f"Path to samples JSON (default: {DEFAULT_SAMPLES_PATH})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to save results (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="qdrant",
        choices=["qdrant"],
        help="Label for results (actual backend is configured server-side, default: qdrant)",
    )
    parser.add_argument(
        "--score-existing",
        type=str,
        default=None,
        help="Path to an existing evaluation JSON to re-score (does not query the API).",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Maximum number of samples to evaluate (default: all)",
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Use cheap string-overlap metrics and skip RAGAS (avoids extra LLM/embeddings calls).",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=API_BASE_URL,
        help=f"API base URL (default: {API_BASE_URL})",
    )
    parser.add_argument(
        "--bypass-hooks",
        type=str,
        default="escalation",
        help="Comma-separated gateway hook names to bypass during API querying "
        "(default: escalation). Use empty string to disable bypassing.",
    )
    parser.add_argument(
        "--ragas-timeout",
        type=int,
        default=None,
        help="RAGAS per-call timeout in seconds (default: RAGAS default).",
    )
    parser.add_argument(
        "--ragas-max-retries",
        type=int,
        default=None,
        help="RAGAS max retries for LLM/embeddings calls (default: RAGAS default).",
    )
    parser.add_argument(
        "--ragas-max-wait",
        type=int,
        default=None,
        help="RAGAS max wait between retries in seconds (default: RAGAS default).",
    )
    parser.add_argument(
        "--ragas-max-workers",
        type=int,
        default=None,
        help="RAGAS worker count for metric evaluation (default: RAGAS default).",
    )
    parser.add_argument(
        "--ragas-batch-size",
        type=int,
        default=None,
        help="RAGAS batch size (default: RAGAS default).",
    )
    parser.add_argument(
        "--metrics",
        type=str,
        default=None,
        help="Comma-separated RAGAS metric names (default: all). "
        "Valid: context_precision, context_recall, faithfulness, answer_relevancy",
    )

    args = parser.parse_args()
    API_BASE_URL = args.api_url

    metric_names = None
    if args.metrics:
        metric_names = [m.strip() for m in args.metrics.split(",") if m.strip()]

    if args.score_existing:
        asyncio.run(
            run_evaluation_from_existing(
                args.score_existing,
                args.output,
                args.backend,
                simple_metrics=args.simple,
                metric_names=metric_names,
                ragas_timeout=args.ragas_timeout,
                ragas_max_retries=args.ragas_max_retries,
                ragas_max_wait=args.ragas_max_wait,
                ragas_max_workers=args.ragas_max_workers,
                ragas_batch_size=args.ragas_batch_size,
            )
        )
        return

    bypass_hooks = None
    if isinstance(args.bypass_hooks, str) and args.bypass_hooks.strip():
        bypass_hooks = [h.strip() for h in args.bypass_hooks.split(",") if h.strip()]

    asyncio.run(
        run_evaluation(
            args.samples,
            args.output,
            args.backend,
            args.max_samples,
            simple_metrics=args.simple,
            metric_names=metric_names,
            ragas_timeout=args.ragas_timeout,
            ragas_max_retries=args.ragas_max_retries,
            ragas_max_wait=args.ragas_max_wait,
            ragas_max_workers=args.ragas_max_workers,
            ragas_batch_size=args.ragas_batch_size,
            bypass_hooks=bypass_hooks,
        )
    )


if __name__ == "__main__":
    main()
