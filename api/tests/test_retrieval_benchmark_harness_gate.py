"""Tests for retrieval benchmark quality gates."""

import argparse
import json

from app.scripts.retrieval_benchmark_harness import gate_benchmark_summary


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
            "context_precision": {"mean": 0.70},
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
            "context_precision": {"mean": 0.70},
            "faithfulness": {"mean": 0.20},
            "answer_relevancy": {"mean": 0.58},
        },
    )
    args = _gate_args(summary_path)

    assert gate_benchmark_summary(args) == 1


def test_gate_fails_when_ragas_falls_back_to_simple_metrics(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "fallback_metrics_used": True,
                "metrics": {
                    "context_recall": {"mean": 0.50},
                    "context_precision": {"mean": 0.70},
                    "faithfulness": {"mean": 0.62},
                    "answer_relevancy": {"mean": 0.58},
                },
            }
        )
    )

    assert gate_benchmark_summary(_gate_args(summary_path)) == 1
