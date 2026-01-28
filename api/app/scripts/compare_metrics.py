#!/usr/bin/env python3
"""
Compare RAGAS metrics between baseline and new evaluation results.

This script loads baseline_scores.json and new_scores.json, computes the
differences, and prints a comparison table highlighting improvements and
regressions.

Usage:
    python -m api.app.scripts.compare_metrics [--baseline PATH] [--new PATH]
"""

import argparse
import json
import sys
from pathlib import Path

# ANSI color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Default paths
DEFAULT_BASELINE_PATH = "api/data/evaluation/baseline_scores.json"
DEFAULT_NEW_PATH = "api/data/evaluation/new_scores.json"


def load_results(path: str) -> dict:
    """Load evaluation results from JSON file.

    Args:
        path: Path to JSON file

    Returns:
        Evaluation results dict
    """
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {path}: {e}")
        sys.exit(1)


def format_change(baseline: float, new: float) -> str:
    """Format the change between baseline and new values.

    Args:
        baseline: Baseline metric value
        new: New metric value

    Returns:
        Formatted change string with color coding
    """
    diff = new - baseline
    pct_change = (diff / baseline * 100) if baseline > 0 else 0

    if diff > 0.01:
        arrow = "+"
        color = GREEN
    elif diff < -0.01:
        arrow = ""
        color = RED
    else:
        arrow = " "
        color = YELLOW

    return f"{color}{arrow}{diff:+.4f} ({pct_change:+.1f}%){RESET}"


def print_comparison(baseline: dict, new: dict) -> None:
    """Print a comparison table of metrics.

    Args:
        baseline: Baseline evaluation results
        new: New evaluation results
    """
    print("\n" + "=" * 80)
    print(f"{BOLD}RAG RETRIEVAL SYSTEM COMPARISON{RESET}")
    print("=" * 80)
    print()

    # System info
    print(f"Baseline system: {baseline.get('system', 'unknown')}")
    print(f"New system:      {new.get('system', 'unknown')}")
    print(f"Baseline date:   {baseline.get('timestamp', 'unknown')}")
    print(f"New date:        {new.get('timestamp', 'unknown')}")
    print(
        f"Samples:         {baseline.get('samples_count', 0)} -> {new.get('samples_count', 0)}"
    )
    print()

    # Metrics comparison
    baseline_metrics = baseline.get("metrics", {})
    new_metrics = new.get("metrics", {})

    print("-" * 80)
    print(f"{'Metric':<25} {'Baseline':>12} {'New':>12} {'Change':>25}")
    print("-" * 80)

    all_metrics = set(baseline_metrics.keys()) | set(new_metrics.keys())
    improvements = 0
    regressions = 0

    for metric in sorted(all_metrics):
        if metric.startswith("_"):
            continue

        baseline_val = baseline_metrics.get(metric, 0.0)
        new_val = new_metrics.get(metric, 0.0)
        change = format_change(baseline_val, new_val)

        print(f"{metric:<25} {baseline_val:>12.4f} {new_val:>12.4f} {change}")

        if new_val > baseline_val + 0.01:
            improvements += 1
        elif new_val < baseline_val - 0.01:
            regressions += 1

    print("-" * 80)

    # Response time comparison
    baseline_time = baseline.get("avg_response_time", 0)
    new_time = new.get("avg_response_time", 0)
    time_diff = new_time - baseline_time
    time_color = GREEN if time_diff < 0 else RED if time_diff > 0 else YELLOW

    print()
    print(
        f"Average response time: {baseline_time:.2f}s -> {new_time:.2f}s "
        f"({time_color}{time_diff:+.2f}s{RESET})"
    )

    # Summary
    print()
    print("=" * 80)
    print(f"{BOLD}SUMMARY{RESET}")
    print("-" * 80)
    print(f"  Improvements: {GREEN}{improvements}{RESET}")
    print(f"  Regressions:  {RED}{regressions}{RESET}")
    print(
        f"  Unchanged:    {len([m for m in all_metrics if not m.startswith('_')]) - improvements - regressions}"
    )
    print()

    # Overall assessment
    if improvements > regressions:
        print(f"{GREEN}{BOLD}OVERALL: IMPROVEMENT{RESET}")
        print(f"The new retrieval system shows improvement in {improvements} metrics.")
    elif regressions > improvements:
        print(f"{RED}{BOLD}OVERALL: REGRESSION{RESET}")
        print(f"The new retrieval system shows regression in {regressions} metrics.")
        print("Consider rolling back or investigating the cause.")
    else:
        print(f"{YELLOW}{BOLD}OVERALL: NEUTRAL{RESET}")
        print("The new retrieval system shows similar performance to baseline.")

    print("=" * 80)


def print_detailed_comparison(baseline: dict, new: dict) -> None:
    """Print detailed per-question comparison.

    Args:
        baseline: Baseline evaluation results
        new: New evaluation results
    """
    baseline_results = {
        r["question"]: r for r in baseline.get("individual_results", [])
    }
    new_results = {r["question"]: r for r in new.get("individual_results", [])}

    print()
    print(f"{BOLD}DETAILED QUESTION-LEVEL ANALYSIS{RESET}")
    print("-" * 80)

    # Find questions with significant changes
    significant_improvements = []
    significant_regressions = []

    for question, new_result in new_results.items():
        if question not in baseline_results:
            continue

        baseline_result = baseline_results[question]

        # Compare response times
        time_diff = new_result["response_time"] - baseline_result["response_time"]

        # Compare context quality (simple heuristic: context length)
        baseline_ctx_len = sum(len(c) for c in baseline_result.get("contexts", []))
        new_ctx_len = sum(len(c) for c in new_result.get("contexts", []))

        if new_ctx_len > baseline_ctx_len * 1.2 and time_diff < 0:
            significant_improvements.append(
                {
                    "question": question,
                    "time_diff": time_diff,
                    "ctx_change": new_ctx_len - baseline_ctx_len,
                }
            )
        elif new_ctx_len < baseline_ctx_len * 0.8 or time_diff > 2.0:
            significant_regressions.append(
                {
                    "question": question,
                    "time_diff": time_diff,
                    "ctx_change": new_ctx_len - baseline_ctx_len,
                }
            )

    if significant_improvements:
        print(f"\n{GREEN}Top Improvements:{RESET}")
        for item in significant_improvements[:5]:
            print(f"  - {item['question'][:60]}...")
            print(
                f"    Time: {item['time_diff']:+.2f}s, Context: {item['ctx_change']:+d} chars"
            )

    if significant_regressions:
        print(f"\n{RED}Potential Regressions:{RESET}")
        for item in significant_regressions[:5]:
            print(f"  - {item['question'][:60]}...")
            print(
                f"    Time: {item['time_diff']:+.2f}s, Context: {item['ctx_change']:+d} chars"
            )

    if not significant_improvements and not significant_regressions:
        print("No significant per-question changes detected.")


def main():
    parser = argparse.ArgumentParser(description="Compare RAGAS metrics")
    parser.add_argument(
        "--baseline",
        type=str,
        default=DEFAULT_BASELINE_PATH,
        help=f"Path to baseline scores (default: {DEFAULT_BASELINE_PATH})",
    )
    parser.add_argument(
        "--new",
        type=str,
        default=DEFAULT_NEW_PATH,
        help=f"Path to new scores (default: {DEFAULT_NEW_PATH})",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed per-question analysis",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output comparison as JSON (machine-readable)",
    )

    args = parser.parse_args()

    baseline = load_results(args.baseline)
    new = load_results(args.new)

    if args.json:
        # Machine-readable output
        baseline_metrics = baseline.get("metrics", {})
        new_metrics = new.get("metrics", {})

        comparison = {
            "baseline_system": baseline.get("system"),
            "new_system": new.get("system"),
            "metrics": {},
        }

        for metric in set(baseline_metrics.keys()) | set(new_metrics.keys()):
            if metric.startswith("_"):
                continue
            baseline_val = baseline_metrics.get(metric, 0.0)
            new_val = new_metrics.get(metric, 0.0)
            comparison["metrics"][metric] = {
                "baseline": baseline_val,
                "new": new_val,
                "diff": new_val - baseline_val,
                "pct_change": (
                    (new_val - baseline_val) / baseline_val * 100 if baseline_val else 0
                ),
            }

        print(json.dumps(comparison, indent=2))
    else:
        print_comparison(baseline, new)

        if args.detailed:
            print_detailed_comparison(baseline, new)


if __name__ == "__main__":
    main()
