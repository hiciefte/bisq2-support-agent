#!/usr/bin/env python3
"""Retrieval benchmark harness for repeated RAGAS runs and A/B comparisons.

Usage examples:

Run repeated evaluation:
    python -m app.scripts.retrieval_benchmark_harness run \
      --samples /data/evaluation/bisq2_realistic_qa_samples.json \
      --backend qdrant \
      --run-name qdrant_current \
      --repeats 3 \
      --output-dir /data/evaluation/benchmarks

Compare two benchmark summaries:
    python -m app.scripts.retrieval_benchmark_harness compare \
      --baseline /data/evaluation/benchmarks/chromadb_initial.summary.json \
      --candidate /data/evaluation/benchmarks/qdrant_current.summary.json \
      --output /data/evaluation/benchmarks/chromadb_vs_qdrant.compare.json
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any

# Keep import behavior consistent with existing evaluation scripts.
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from app.scripts.run_ragas_evaluation import API_BASE_URL, run_evaluation  # noqa: E402

DEFAULT_OUTPUT_DIR = "api/data/evaluation/benchmarks"


def _safe_mean(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _safe_stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(stdev(values))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(float(value))


def _file_sha256(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _parse_csv_arg(value: str | None) -> list[str] | None:
    if value is None:
        return None
    if not value.strip():
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def _aggregate_runs(
    run_results: list[dict[str, Any]],
    *,
    run_name: str,
    backend: str,
    samples_path: str,
    samples_sha256: str,
    run_output_paths: list[str],
    kb_manifest_path: str | None = None,
    kb_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    metric_runs: dict[str, list[float]] = defaultdict(list)
    response_time_runs: list[float] = []

    # question -> metric -> values across repeats
    per_question_values: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    per_question_metadata: dict[str, dict[str, Any]] = {}

    # protocol -> metric -> values across runs/questions
    slice_values: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    slice_question_counts: dict[str, int] = defaultdict(int)

    for result in run_results:
        for metric, value in (result.get("metrics") or {}).items():
            if metric.startswith("_"):
                continue
            if _is_number(value):
                metric_runs[metric].append(float(value))

        rt = result.get("avg_response_time")
        if _is_number(rt):
            response_time_runs.append(float(rt))

        for row in result.get("individual_results") or []:
            question = str(row.get("question", ""))
            if not question:
                continue

            metadata = row.get("metadata")
            if isinstance(metadata, dict):
                per_question_metadata.setdefault(question, metadata)
            else:
                per_question_metadata.setdefault(question, {})

            ragas = row.get("ragas") or {}
            if isinstance(ragas, dict):
                for metric, value in ragas.items():
                    if _is_number(value):
                        fv = float(value)
                        per_question_values[question][metric].append(fv)
                        protocol = str(
                            (per_question_metadata.get(question) or {}).get(
                                "protocol", "unknown"
                            )
                        )
                        slice_values[protocol][metric].append(fv)

            protocol_for_count = str(
                (per_question_metadata.get(question) or {}).get("protocol", "unknown")
            )
            slice_question_counts[protocol_for_count] += 1

    metrics_summary = {
        metric: {
            "mean": _safe_mean(values),
            "stdev": _safe_stdev(values),
            "runs": values,
        }
        for metric, values in sorted(metric_runs.items())
    }

    per_question_summary = []
    for question in sorted(per_question_values.keys()):
        metric_summary = {}
        for metric, values in sorted(per_question_values[question].items()):
            metric_summary[metric] = {
                "mean": _safe_mean(values),
                "stdev": _safe_stdev(values),
                "runs": values,
            }
        per_question_summary.append(
            {
                "question": question,
                "metadata": per_question_metadata.get(question, {}),
                "metrics": metric_summary,
            }
        )

    slice_summary: dict[str, Any] = {}
    for protocol in sorted(slice_values.keys()):
        metric_summary = {}
        for metric, values in sorted(slice_values[protocol].items()):
            metric_summary[metric] = {
                "mean": _safe_mean(values),
                "stdev": _safe_stdev(values),
                "count": len(values),
            }
        slice_summary[protocol] = {
            "question_count_across_runs": slice_question_counts.get(protocol, 0),
            "metrics": metric_summary,
        }

    samples_count = run_results[0].get("samples_count") if run_results else 0
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_name": run_name,
        "backend": backend,
        "samples_path": samples_path,
        "samples_sha256": samples_sha256,
        "knowledge_base_manifest_path": kb_manifest_path,
        "knowledge_base_manifest_sha256": kb_manifest_sha256,
        "samples_count": samples_count,
        "repeats": len(run_results),
        "run_outputs": run_output_paths,
        "metrics": metrics_summary,
        "avg_response_time": {
            "mean": _safe_mean(response_time_runs),
            "stdev": _safe_stdev(response_time_runs),
            "runs": response_time_runs,
        },
        "slice_metrics": slice_summary,
        "per_question": per_question_summary,
    }


async def run_benchmark(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    samples_sha = _file_sha256(args.samples)
    kb_manifest_sha = _file_sha256(args.kb_manifest) if args.kb_manifest else None
    metric_names = _parse_csv_arg(args.metrics)
    bypass_hooks = _parse_csv_arg(args.bypass_hooks)
    run_output_paths: list[str] = []
    run_results: list[dict[str, Any]] = []

    run_name = args.run_name
    for idx in range(args.repeats):
        run_idx = idx + 1
        run_output = output_dir / f"{run_name}.run{run_idx:02d}.json"
        run_output_paths.append(str(run_output))

        print(
            f"[run {run_idx}/{args.repeats}] backend={args.backend} "
            f"samples={args.samples} -> {run_output}"
        )
        started = time.time()
        result = await run_evaluation(
            samples_path=args.samples,
            output_path=str(run_output),
            backend=args.backend,
            max_samples=args.max_samples,
            simple_metrics=args.simple,
            metric_names=metric_names,
            ragas_timeout=args.ragas_timeout,
            ragas_max_retries=args.ragas_max_retries,
            ragas_max_wait=args.ragas_max_wait,
            ragas_max_workers=args.ragas_max_workers,
            ragas_batch_size=args.ragas_batch_size,
            bypass_hooks=bypass_hooks,
        )
        elapsed = time.time() - started
        run_results.append(result)
        print(f"[run {run_idx}/{args.repeats}] completed in {elapsed:.1f}s")

        if args.sleep_between > 0 and run_idx < args.repeats:
            await asyncio.sleep(args.sleep_between)

    summary = _aggregate_runs(
        run_results,
        run_name=run_name,
        backend=args.backend,
        samples_path=args.samples,
        samples_sha256=samples_sha,
        run_output_paths=run_output_paths,
        kb_manifest_path=args.kb_manifest,
        kb_manifest_sha256=kb_manifest_sha,
    )

    summary_path = output_dir / f"{run_name}.summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Saved summary: {summary_path}")
    print("Metric means:")
    for metric, stats in summary["metrics"].items():
        print(f"  {metric}: {stats['mean']:.4f} ± {stats['stdev']:.4f}")
    print(
        "  avg_response_time: "
        f"{summary['avg_response_time']['mean']:.2f}s ± {summary['avg_response_time']['stdev']:.2f}s"
    )

    return 0


def _index_per_question(summary: dict[str, Any]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in summary.get("per_question") or []:
        q = row.get("question")
        if not q:
            continue
        metrics = {}
        for metric, stats in (row.get("metrics") or {}).items():
            m = stats.get("mean")
            if _is_number(m):
                metrics[metric] = float(m)
        out[q] = metrics
    return out


def compare_benchmarks(args: argparse.Namespace) -> int:
    with open(args.baseline) as f:
        baseline = json.load(f)
    with open(args.candidate) as f:
        candidate = json.load(f)

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "baseline": args.baseline,
        "candidate": args.candidate,
        "metric_deltas": {},
        "slice_metric_deltas": {},
        "avg_response_time_delta": {},
        "faithfulness_per_question_deltas": [],
        "gates": {"passed": True, "failures": []},
    }

    # Overall metric deltas.
    baseline_metrics = baseline.get("metrics") or {}
    candidate_metrics = candidate.get("metrics") or {}
    shared_metrics = sorted(
        set(baseline_metrics.keys()) & set(candidate_metrics.keys())
    )
    for metric in shared_metrics:
        b = baseline_metrics[metric]["mean"]
        c = candidate_metrics[metric]["mean"]
        if _is_number(b) and _is_number(c):
            report["metric_deltas"][metric] = {
                "baseline_mean": float(b),
                "candidate_mean": float(c),
                "delta": float(c) - float(b),
            }

    # Slice-level metric deltas by protocol.
    base_slices = baseline.get("slice_metrics") or {}
    cand_slices = candidate.get("slice_metrics") or {}
    for protocol in sorted(set(base_slices.keys()) & set(cand_slices.keys())):
        base_m = (base_slices[protocol] or {}).get("metrics") or {}
        cand_m = (cand_slices[protocol] or {}).get("metrics") or {}
        shared = sorted(set(base_m.keys()) & set(cand_m.keys()))
        for metric in shared:
            b = base_m[metric]["mean"]
            c = cand_m[metric]["mean"]
            if _is_number(b) and _is_number(c):
                report["slice_metric_deltas"].setdefault(protocol, {})[metric] = {
                    "baseline_mean": float(b),
                    "candidate_mean": float(c),
                    "delta": float(c) - float(b),
                }

    # Latency delta.
    b_rt = (baseline.get("avg_response_time") or {}).get("mean", 0.0)
    c_rt = (candidate.get("avg_response_time") or {}).get("mean", 0.0)
    rt_delta = float(c_rt) - float(b_rt)
    rt_delta_pct = (rt_delta / float(b_rt) * 100.0) if float(b_rt) > 0 else 0.0
    report["avg_response_time_delta"] = {
        "baseline_mean": float(b_rt),
        "candidate_mean": float(c_rt),
        "delta_seconds": rt_delta,
        "delta_percent": rt_delta_pct,
    }

    # Per-question faithfulness delta.
    base_q = _index_per_question(baseline)
    cand_q = _index_per_question(candidate)
    for question in sorted(set(base_q.keys()) & set(cand_q.keys())):
        if (
            "faithfulness" not in base_q[question]
            or "faithfulness" not in cand_q[question]
        ):
            continue
        b = base_q[question]["faithfulness"]
        c = cand_q[question]["faithfulness"]
        report["faithfulness_per_question_deltas"].append(
            {
                "question": question,
                "baseline": b,
                "candidate": c,
                "delta": c - b,
            }
        )
    report["faithfulness_per_question_deltas"].sort(key=lambda x: x["delta"])

    # Gates.
    for metric, row in report["metric_deltas"].items():
        if row["delta"] < -args.max_overall_drop:
            report["gates"]["passed"] = False
            report["gates"]["failures"].append(
                f"overall {metric} drop {row['delta']:.4f} < -{args.max_overall_drop:.4f}"
            )

    for protocol, metric_rows in report["slice_metric_deltas"].items():
        for metric, row in metric_rows.items():
            if row["delta"] < -args.max_slice_drop:
                report["gates"]["passed"] = False
                report["gates"]["failures"].append(
                    f"slice {protocol}/{metric} drop {row['delta']:.4f} < -{args.max_slice_drop:.4f}"
                )

    if rt_delta_pct > args.max_latency_increase_pct:
        report["gates"]["passed"] = False
        report["gates"]["failures"].append(
            "latency increase "
            f"{rt_delta_pct:.2f}% > {args.max_latency_increase_pct:.2f}%"
        )

    output_path = args.output
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Saved compare report: {output_path}")
    for metric, row in report["metric_deltas"].items():
        print(
            f"{metric}: {row['baseline_mean']:.4f} -> {row['candidate_mean']:.4f} ({row['delta']:+.4f})"
        )
    print(
        "avg_response_time: "
        f"{b_rt:.2f}s -> {c_rt:.2f}s ({rt_delta:+.2f}s, {rt_delta_pct:+.1f}%)"
    )
    print(f"gates_passed: {report['gates']['passed']}")
    if report["gates"]["failures"]:
        print("gate_failures:")
        for failure in report["gates"]["failures"]:
            print(f"  - {failure}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retrieval benchmark harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run repeated benchmark evaluations")
    run_parser.add_argument(
        "--samples", type=str, required=True, help="Path to sample JSON"
    )
    run_parser.add_argument(
        "--backend", type=str, required=True, choices=["chromadb", "qdrant", "hybrid"]
    )
    run_parser.add_argument(
        "--run-name", type=str, required=True, help="Name prefix for output files"
    )
    run_parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR)
    run_parser.add_argument("--repeats", type=int, default=3)
    run_parser.add_argument("--sleep-between", type=float, default=1.0)
    run_parser.add_argument("--max-samples", type=int, default=None)
    run_parser.add_argument("--simple", action="store_true")
    run_parser.add_argument("--metrics", type=str, default=None)
    run_parser.add_argument("--bypass-hooks", type=str, default="escalation")
    run_parser.add_argument("--api-url", type=str, default=API_BASE_URL)
    run_parser.add_argument(
        "--kb-manifest",
        type=str,
        default=None,
        help="Optional knowledge-base snapshot manifest JSON path for reproducibility tracking.",
    )
    run_parser.add_argument("--ragas-timeout", type=int, default=None)
    run_parser.add_argument("--ragas-max-retries", type=int, default=None)
    run_parser.add_argument("--ragas-max-wait", type=int, default=None)
    run_parser.add_argument("--ragas-max-workers", type=int, default=None)
    run_parser.add_argument("--ragas-batch-size", type=int, default=None)

    compare_parser = subparsers.add_parser(
        "compare", help="Compare two benchmark summaries"
    )
    compare_parser.add_argument("--baseline", type=str, required=True)
    compare_parser.add_argument("--candidate", type=str, required=True)
    compare_parser.add_argument("--output", type=str, required=True)
    compare_parser.add_argument("--max-overall-drop", type=float, default=0.02)
    compare_parser.add_argument("--max-slice-drop", type=float, default=0.05)
    compare_parser.add_argument("--max-latency-increase-pct", type=float, default=20.0)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Keep API URL handling aligned with run_ragas_evaluation.
    os.environ["API_BASE_URL"] = (
        args.api_url if hasattr(args, "api_url") else API_BASE_URL
    )

    if args.command == "run":
        return asyncio.run(run_benchmark(args))
    if args.command == "compare":
        return compare_benchmarks(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
