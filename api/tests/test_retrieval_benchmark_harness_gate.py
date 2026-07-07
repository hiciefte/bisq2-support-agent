"""Tests for retrieval benchmark quality gates."""

import argparse
import json

from app.scripts.retrieval_benchmark_harness import gate_benchmark_summary
from app.scripts.run_ragas_evaluation import compute_retrieval_rank_metrics


def _write_summary(tmp_path, metrics):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"metrics": metrics}))
    return path


def _gate_args(summary_path):
    return argparse.Namespace(
        summary=str(summary_path),
        min_recall_at_k=0.38,
        min_mrr=0.60,
        min_faithfulness=0.40,
        min_answer_relevancy=0.55,
    )


def test_gate_passes_when_all_quality_floors_met(tmp_path):
    summary_path = _write_summary(
        tmp_path,
        {
            "context_recall": {"mean": 0.50},
            "mrr": {"mean": 0.70},
            "faithfulness": {"mean": 0.62},
            "answer_relevancy": {"mean": 0.58},
        },
    )
    args = _gate_args(summary_path)

    assert gate_benchmark_summary(args) == 0


def test_gate_fails_when_answer_quality_regresses(tmp_path):
    summary_path = _write_summary(
        tmp_path,
        {
            "context_recall": {"mean": 0.50},
            "mrr": {"mean": 0.70},
            "faithfulness": {"mean": 0.20},
            "answer_relevancy": {"mean": 0.58},
        },
    )
    args = _gate_args(summary_path)

    assert gate_benchmark_summary(args) == 1


def test_gate_fails_when_answer_relevancy_regresses(tmp_path):
    summary_path = _write_summary(
        tmp_path,
        {
            "context_recall": {"mean": 0.50},
            "mrr": {"mean": 0.70},
            "faithfulness": {"mean": 0.62},
            "answer_relevancy": {"mean": 0.30},
        },
    )

    assert gate_benchmark_summary(_gate_args(summary_path)) == 1


def test_gate_fails_when_ragas_falls_back_to_simple_metrics(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "fallback_metrics_used": True,
                "metrics": {
                    "context_recall": {"mean": 0.50},
                    "mrr": {"mean": 0.70},
                    "faithfulness": {"mean": 0.62},
                    "answer_relevancy": {"mean": 0.58},
                },
            }
        )
    )

    assert gate_benchmark_summary(_gate_args(summary_path)) == 1


def test_gate_fails_when_required_metric_is_missing(tmp_path, capsys):
    summary_path = _write_summary(
        tmp_path,
        {
            "context_recall": {"mean": 0.50},
            "faithfulness": {"mean": 0.62},
            "answer_relevancy": {"mean": 0.58},
        },
    )

    assert gate_benchmark_summary(_gate_args(summary_path)) == 1
    captured = capsys.readouterr()
    assert "mrr: none of mrr, mean_reciprocal_rank present" in captured.out


def test_retrieval_rank_metrics_use_first_relevant_context_rank():
    metrics, per_sample = compute_retrieval_rank_metrics(
        [
            "The seller confirms payment and releases bitcoin after the buyer sends fiat.",
            "DAO state must be rebuilt before checking the failed trade again.",
        ],
        [
            [
                "Unrelated network fee explanation.",
                "The seller releases bitcoin after payment is confirmed.",
            ],
            ["General Bisq Easy onboarding text."],
        ],
    )

    assert metrics == {"recall_at_k": 0.5, "mrr": 0.25}
    assert per_sample == [
        {"recall_at_k": 1.0, "mrr": 0.5},
        {"recall_at_k": 0.0, "mrr": 0.0},
    ]
