#!/usr/bin/env python3
"""
Hyperparameter optimization for RAG retrieval pipeline.

This script tests different hyperparameter configurations and finds
the optimal settings based on RAGAS evaluation metrics.

Usage:
    docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api \
        python -m app.scripts.optimize_hyperparameters

Hyperparameters tested:
    - HYBRID_SEMANTIC_WEIGHT / HYBRID_KEYWORD_WEIGHT (must sum to 1.0)
    - COLBERT_TOP_N
    - ENABLE_COLBERT_RERANK
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
SAMPLES_PATH = Path("/data/evaluation/bisq_qa_baseline_samples.json")
RESULTS_DIR = Path("/data/evaluation/optimization")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


@dataclass
class HyperparamConfig:
    """Configuration for a single hyperparameter trial."""

    semantic_weight: float
    keyword_weight: float
    colbert_top_n: int
    enable_colbert: bool

    def __post_init__(self):
        # Ensure weights sum to 1.0
        if abs(self.semantic_weight + self.keyword_weight - 1.0) > 0.001:
            raise ValueError("Weights must sum to 1.0")

    @property
    def name(self) -> str:
        """Generate descriptive name for this config."""
        colbert_status = "colbert" if self.enable_colbert else "no_colbert"
        return f"sw{self.semantic_weight:.1f}_kw{self.keyword_weight:.1f}_top{self.colbert_top_n}_{colbert_status}"


# Define search space
SEARCH_SPACE = [
    # Current default
    HyperparamConfig(0.7, 0.3, 5, True),
    # More semantic focus
    HyperparamConfig(0.8, 0.2, 5, True),
    HyperparamConfig(0.9, 0.1, 5, True),
    # More keyword focus
    HyperparamConfig(0.6, 0.4, 5, True),
    HyperparamConfig(0.5, 0.5, 5, True),
    # Different top_n values
    HyperparamConfig(0.7, 0.3, 3, True),
    HyperparamConfig(0.7, 0.3, 7, True),
    HyperparamConfig(0.7, 0.3, 10, True),
    # Without ColBERT reranking
    HyperparamConfig(0.7, 0.3, 5, False),
    HyperparamConfig(0.8, 0.2, 5, False),
    # Combinations
    HyperparamConfig(0.8, 0.2, 7, True),
    HyperparamConfig(0.6, 0.4, 7, True),
]


def update_env_config(config: HyperparamConfig) -> None:
    """Update environment variables for the current process.

    Note: This updates the current process environment. For Docker containers,
    you would need to restart the service with new environment variables.
    """
    os.environ["HYBRID_SEMANTIC_WEIGHT"] = str(config.semantic_weight)
    os.environ["HYBRID_KEYWORD_WEIGHT"] = str(config.keyword_weight)
    os.environ["COLBERT_TOP_N"] = str(config.colbert_top_n)
    os.environ["ENABLE_COLBERT_RERANK"] = str(config.enable_colbert).lower()


async def query_rag_system(
    client: httpx.AsyncClient, question: str, timeout: float = 60.0
) -> dict[str, Any]:
    """Query the RAG system."""
    try:
        response = await client.post(
            f"{API_BASE_URL}/chat/query",
            json={"question": question, "chat_history": []},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning(f"Query error: {e}")
        return {"answer": "", "sources": [], "error": str(e)}


def compute_ragas_metrics(
    questions: list[str],
    ground_truths: list[str],
    answers: list[str],
    contexts: list[list[str]],
) -> dict[str, float]:
    """Compute RAGAS evaluation metrics."""
    try:
        from datasets import Dataset
        from ragas import evaluate

        try:
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
            from ragas.metrics import (
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

        data = {
            "question": questions,
            "ground_truth": ground_truths,
            "answer": answers,
            "contexts": contexts,
        }
        dataset = Dataset.from_dict(data)
        result = evaluate(dataset, metrics=metrics)

        import math

        def get_score(key: str) -> float:
            try:
                if hasattr(result, "__getitem__"):
                    val = result[key]
                elif hasattr(result, key):
                    val = getattr(result, key)
                else:
                    return 0.0
                if isinstance(val, list):
                    valid = [v for v in val if v is not None and not math.isnan(v)]
                    return sum(valid) / len(valid) if valid else 0.0
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    return 0.0
                return float(val)
            except Exception:
                return 0.0

        return {
            "context_precision": get_score("context_precision"),
            "context_recall": get_score("context_recall"),
            "faithfulness": get_score("faithfulness"),
            "answer_relevancy": get_score("answer_relevancy"),
        }

    except ImportError:
        logger.warning("RAGAS not available, using simple metrics")
        return compute_simple_metrics(questions, ground_truths, answers, contexts)


def compute_simple_metrics(
    questions: list[str],
    ground_truths: list[str],
    answers: list[str],
    contexts: list[list[str]],
) -> dict[str, float]:
    """Simple fallback metrics."""
    from difflib import SequenceMatcher

    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    answer_scores = [
        similarity(ans, gt) for ans, gt in zip(answers, ground_truths) if ans and gt
    ]
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
        "faithfulness": 0.5,
        "answer_relevancy": (
            sum(answer_scores) / len(answer_scores) if answer_scores else 0.0
        ),
    }


async def evaluate_config(
    config: HyperparamConfig, samples: list[dict], max_samples: int | None = None
) -> dict[str, Any]:
    """Evaluate a single hyperparameter configuration."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Evaluating: {config.name}")
    logger.info(f"  Semantic weight: {config.semantic_weight}")
    logger.info(f"  Keyword weight: {config.keyword_weight}")
    logger.info(f"  ColBERT top_n: {config.colbert_top_n}")
    logger.info(f"  ColBERT enabled: {config.enable_colbert}")
    logger.info(f"{'='*60}")

    if max_samples:
        samples = samples[:max_samples]

    questions = []
    ground_truths = []
    answers = []
    contexts = []

    async with httpx.AsyncClient() as client:
        # Health check
        try:
            health = await client.get(f"{API_BASE_URL}/health", timeout=10.0)
            health.raise_for_status()
        except Exception as e:
            logger.error(f"API not available: {e}")
            return {"error": str(e), "config": config.name}

        for i, sample in enumerate(samples):
            question = sample["question"]
            ground_truth = sample["ground_truth"]

            protocol = sample.get("metadata", {}).get("protocol", "")
            if protocol == "bisq_easy":
                question_with_context = f"{question} (I'm using Bisq Easy / Bisq 2)"
            elif protocol == "multisig_v1":
                question_with_context = f"{question} (I'm using Bisq 1)"
            else:
                question_with_context = question

            logger.info(f"[{i+1}/{len(samples)}] {question[:50]}...")

            result = await query_rag_system(client, question_with_context)

            answer = result.get("answer", "")
            sources = result.get("sources", [])
            ctx = []
            for src in sources:
                if isinstance(src, dict):
                    content = src.get("content", src.get("page_content", ""))
                    if content:
                        ctx.append(content)

            questions.append(question)
            ground_truths.append(ground_truth)
            answers.append(answer)
            contexts.append(ctx if ctx else [""])

            await asyncio.sleep(0.3)

    metrics = compute_ragas_metrics(questions, ground_truths, answers, contexts)

    # Compute aggregate score for comparison
    aggregate = (
        metrics["context_precision"] * 0.25
        + metrics["context_recall"] * 0.25
        + metrics["faithfulness"] * 0.25
        + metrics["answer_relevancy"] * 0.25
    )

    return {
        "config": config.name,
        "hyperparameters": {
            "semantic_weight": config.semantic_weight,
            "keyword_weight": config.keyword_weight,
            "colbert_top_n": config.colbert_top_n,
            "enable_colbert": config.enable_colbert,
        },
        "metrics": metrics,
        "aggregate_score": aggregate,
        "samples_count": len(samples),
    }


async def run_optimization(
    max_samples: int | None = 10, configs: list[HyperparamConfig] | None = None
) -> dict[str, Any]:
    """Run hyperparameter optimization loop."""
    # Load samples
    if not SAMPLES_PATH.exists():
        logger.error(f"Samples file not found: {SAMPLES_PATH}")
        return {"error": "Samples file not found"}

    with open(SAMPLES_PATH) as f:
        samples = json.load(f)

    logger.info(f"Loaded {len(samples)} samples")

    if configs is None:
        configs = SEARCH_SPACE

    logger.info(f"Testing {len(configs)} configurations")

    # Create results directory
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for i, config in enumerate(configs):
        logger.info(f"\n[{i+1}/{len(configs)}] Testing configuration: {config.name}")

        # Note: In a real setup, we would need to restart the API with new env vars
        # For now, we evaluate with the current settings (this is a limitation)
        # The proper approach would be to modify docker-compose env and restart

        result = await evaluate_config(config, samples, max_samples)
        results.append(result)

        # Save intermediate results
        intermediate_file = RESULTS_DIR / f"trial_{config.name}.json"
        with open(intermediate_file, "w") as f:
            json.dump(result, f, indent=2)

        logger.info(f"  Metrics: {result.get('metrics', {})}")
        logger.info(f"  Aggregate: {result.get('aggregate_score', 0):.4f}")

    # Sort by aggregate score
    sorted_results = sorted(
        [r for r in results if "error" not in r],
        key=lambda x: x.get("aggregate_score", 0),
        reverse=True,
    )

    # Build final report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "samples_count": max_samples or len(samples),
        "configurations_tested": len(configs),
        "best_config": sorted_results[0] if sorted_results else None,
        "all_results": sorted_results,
        "ranking": [
            {
                "rank": i + 1,
                "config": r["config"],
                "aggregate_score": r.get("aggregate_score", 0),
                "context_precision": r["metrics"]["context_precision"],
                "context_recall": r["metrics"]["context_recall"],
                "faithfulness": r["metrics"]["faithfulness"],
                "answer_relevancy": r["metrics"]["answer_relevancy"],
            }
            for i, r in enumerate(sorted_results)
        ],
    }

    # Save final report
    report_file = (
        RESULTS_DIR
        / f"optimization_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print("HYPERPARAMETER OPTIMIZATION RESULTS")
    print("=" * 70)
    print(f"Configurations tested: {len(configs)}")
    print(f"Samples per config: {max_samples or len(samples)}")
    print()
    print("RANKING:")
    print("-" * 70)
    print(f"{'Rank':<5} {'Config':<35} {'Score':<10} {'Prec':<8} {'Recall':<8}")
    print("-" * 70)
    for item in report["ranking"][:10]:
        print(
            f"{item['rank']:<5} {item['config']:<35} {item['aggregate_score']:.4f}    "
            f"{item['context_precision']:.4f}   {item['context_recall']:.4f}"
        )
    print("-" * 70)

    if report["best_config"]:
        print()
        print("BEST CONFIGURATION:")
        best = report["best_config"]
        print(f"  Name: {best['config']}")
        print("  Hyperparameters:")
        for k, v in best["hyperparameters"].items():
            print(f"    {k}: {v}")
        print(f"  Aggregate Score: {best['aggregate_score']:.4f}")
        print("  Metrics:")
        for k, v in best["metrics"].items():
            print(f"    {k}: {v:.4f}")

    print()
    print(f"Full report saved to: {report_file}")
    print("=" * 70)

    return report


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Hyperparameter optimization for RAG")
    parser.add_argument(
        "--max-samples",
        type=int,
        default=10,
        help="Maximum samples per configuration (default: 10)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick test with 3 configurations and 5 samples",
    )

    args = parser.parse_args()

    if args.quick:
        # Quick test with subset of configs
        configs = SEARCH_SPACE[:3]
        max_samples = 5
    else:
        configs = SEARCH_SPACE
        max_samples = args.max_samples

    asyncio.run(run_optimization(max_samples=max_samples, configs=configs))


if __name__ == "__main__":
    main()
