#!/usr/bin/env python3
"""Validate and atomically persist sanitized release quality reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = 2
MODEL_ID_PATTERN = re.compile(r"^openai:[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
SAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{0,80}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")

PER_SAMPLE_FAILURE_CODES = frozenset(
    {
        "answer_length_ratio_above_max",
        "diagnostic_question_present_mismatch",
        "empty_answer",
        "leading_greeting_avoided_mismatch",
        "remedy_term_overlap_below_min",
        "request_failed",
        "required_answer_term_missing",
        "required_mcp_tool_missing",
        "review_answer_not_replaced",
        "review_draft_unavailable",
        "review_delivery_required",
        "routing_action_not_allowed",
        "scam_warning_present_mismatch",
        "wiki_link_present_mismatch",
    }
)
AGGREGATE_FAILURE_CODES = frozenset(
    {
        "answer_length_ratio_above_max",
        "diagnostic_expected_coverage_missing",
        "diagnostic_question_rate_below_min",
        "greeting_avoidance_rate_below_min",
        "per_sample_answer_length_ratio_above_max",
        "per_sample_gate_failed",
        "quality_report_unavailable_or_invalid",
        "remedy_term_coverage_missing",
        "remedy_term_overlap_below_min",
        "scam_warning_negative_coverage_missing",
        "scam_warning_positive_coverage_missing",
        "scam_warning_precision_below_min",
        "scam_warning_recall_below_min",
        "troubleshooting_coverage_missing",
        "wiki_link_coverage_missing",
        "wiki_link_recall_below_min",
    }
)
REQUEST_ERROR_CODES = frozenset(
    {"http_error", "invalid_response", "request_failed", "timeout"}
)
EVALUATION_SOURCES = frozenset({"delivered", "review_draft", "unavailable"})
DIRECT_EVALUATION_ROUTING_ACTIONS = frozenset({"auto_send", "needs_clarification"})

METRIC_KEYS = frozenset(
    {
        "answer_length_ratio",
        "greeting_avoidance_rate",
        "scam_warning_precision",
        "scam_warning_recall",
        "wiki_link_recall",
        "diagnostic_question_rate",
        "remedy_term_overlap",
    }
)
THRESHOLD_KEYS = frozenset(
    {
        "max_answer_length_ratio",
        "min_greeting_avoidance_rate",
        "min_scam_warning_precision",
        "min_scam_warning_recall",
        "min_wiki_link_recall",
        "min_diagnostic_question_rate",
        "min_remedy_term_overlap",
    }
)
COVERAGE_KEYS = frozenset(
    {
        "samples",
        "scam_warning_warranted",
        "scam_warning_not_warranted",
        "staff_linked_wiki",
        "troubleshooting",
        "diagnostic_expected",
        "remedy_term_samples",
        "remedy_terms_expected",
    }
)
DIVERGENCE_KEYS = frozenset(
    {
        "answer_too_long",
        "leading_greeting",
        "scam_warning_missing",
        "scam_warning_false_positive",
        "wiki_link_missing",
        "diagnostic_question_missing",
        "remedy_term_missing",
    }
)
PER_SAMPLE_KEYS = frozenset(
    {
        "case_id",
        "answer_length_ratio",
        "leading_greeting_avoided",
        "scam_warning_warranted",
        "scam_warning_present",
        "staff_linked_wiki",
        "wiki_link_present",
        "troubleshooting",
        "diagnostic_expected",
        "diagnostic_question_present",
        "remedy_terms_expected",
        "remedy_terms_matched",
        "remedy_term_overlap",
        "divergences",
        "case_kind",
        "response_contract",
        "gate",
    }
)
PER_SAMPLE_BOOLEAN_KEYS = frozenset(
    {
        "leading_greeting_avoided",
        "scam_warning_warranted",
        "scam_warning_present",
        "staff_linked_wiki",
        "wiki_link_present",
        "troubleshooting",
        "diagnostic_expected",
        "diagnostic_question_present",
    }
)


def model_sha256(model_id: str) -> str:
    """Return the marker-safe identity for a validated release model."""
    if not MODEL_ID_PATTERN.fullmatch(model_id):
        raise ValueError("Release model ID is invalid")
    return hashlib.sha256(model_id.encode("utf-8")).hexdigest()


def _exact_object(value: Any, keys: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} has an unsupported schema")
    return value


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{context} must be finite")
    return resolved


def validate_aggregate_thresholds(value: Any) -> dict[str, Any]:
    """Validate the complete release aggregate-threshold contract."""
    thresholds = _exact_object(value, THRESHOLD_KEYS, "Aggregate thresholds")
    for key, value in thresholds.items():
        resolved = _finite_number(value, f"Aggregate threshold {key}")
        if key == "max_answer_length_ratio":
            if resolved <= 0:
                raise ValueError("Maximum answer-length ratio must be positive")
        elif not 0 <= resolved <= 1:
            raise ValueError(f"Aggregate threshold {key} is outside its safe range")
    return thresholds


def _nonnegative_integer(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a nonnegative integer")
    return value


def _failure_list(value: Any, allowed_codes: frozenset[str], context: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or item not in allowed_codes for item in value
    ):
        raise ValueError(f"{context} contains an unsupported failure code")
    if len(value) != len(set(value)):
        raise ValueError(f"{context} contains duplicate failure codes")
    return value


def _validate_per_sample(value: Any) -> None:
    sample = _exact_object(value, PER_SAMPLE_KEYS, "Per-sample report")
    case_id = sample["case_id"]
    if not isinstance(case_id, str) or not SAFE_ID_PATTERN.fullmatch(case_id):
        raise ValueError("Per-sample case ID is invalid")
    if sample["case_kind"] not in {"standard", "live_data", "escalation"}:
        raise ValueError("Per-sample case kind is invalid")

    if _finite_number(sample["answer_length_ratio"], "Answer length ratio") < 0:
        raise ValueError("Answer length ratio must be nonnegative")
    overlap = _finite_number(sample["remedy_term_overlap"], "Remedy overlap")
    if not 0 <= overlap <= 1:
        raise ValueError("Remedy overlap is outside its safe range")
    for key in PER_SAMPLE_BOOLEAN_KEYS:
        if not isinstance(sample[key], bool):
            raise ValueError(f"Per-sample {key} must be boolean")
    expected_remedies = _nonnegative_integer(
        sample["remedy_terms_expected"], "Expected remedy terms"
    )
    matched_remedies = _nonnegative_integer(
        sample["remedy_terms_matched"], "Matched remedy terms"
    )
    if matched_remedies > expected_remedies:
        raise ValueError("Matched remedy terms exceed the reviewed expectation")

    divergences = sample["divergences"]
    if (
        not isinstance(divergences, list)
        or len(divergences) != len(set(divergences))
        or any(item not in DIVERGENCE_KEYS for item in divergences)
    ):
        raise ValueError("Per-sample divergences are invalid")

    response = _exact_object(
        sample["response_contract"],
        frozenset(
            {
                "request_error",
                "requires_human",
                "routing_action",
                "mcp_tools",
                "evaluation_source",
            }
        ),
        "Response contract",
    )
    request_error = response["request_error"]
    if request_error is not None and request_error not in REQUEST_ERROR_CODES:
        raise ValueError("Response request error is unsafe")
    if not isinstance(response["requires_human"], bool):
        raise ValueError("Response requires_human must be boolean")
    if response["evaluation_source"] not in EVALUATION_SOURCES:
        raise ValueError("Response evaluation source is unsafe")
    routing_action = response["routing_action"]
    if not isinstance(routing_action, str) or not SAFE_TOKEN_PATTERN.fullmatch(
        routing_action
    ):
        raise ValueError("Response routing action is unsafe")
    evaluation_source = response["evaluation_source"]
    review_routed = (
        response["requires_human"]
        or routing_action not in DIRECT_EVALUATION_ROUTING_ACTIONS
    )
    if request_error is not None and evaluation_source != "unavailable":
        raise ValueError("Failed response evaluation source is inconsistent")
    if request_error is None and not review_routed and evaluation_source != "delivered":
        raise ValueError("Direct response evaluation source is inconsistent")
    if (
        request_error is None
        and review_routed
        and evaluation_source not in {"review_draft", "unavailable"}
    ):
        raise ValueError("Review response evaluation source is inconsistent")
    tools = response["mcp_tools"]
    if (
        not isinstance(tools, list)
        or len(tools) != len(set(tools))
        or any(
            not isinstance(tool, str) or not SAFE_ID_PATTERN.fullmatch(tool)
            for tool in tools
        )
    ):
        raise ValueError("Response MCP tool list is unsafe")

    gate = _exact_object(
        sample["gate"], frozenset({"passed", "failures"}), "Per-sample gate"
    )
    if not isinstance(gate["passed"], bool):
        raise ValueError("Per-sample gate result must be boolean")
    failures = _failure_list(
        gate["failures"], PER_SAMPLE_FAILURE_CODES, "Per-sample gate"
    )
    if (request_error is not None) != ("request_failed" in failures):
        raise ValueError("Response request error must match its gate failure")
    if (
        request_error is None
        and review_routed
        and evaluation_source == "unavailable"
        and "review_draft_unavailable" not in failures
    ):
        raise ValueError("Unavailable review draft must fail explicitly")
    if gate["passed"] == bool(failures):
        raise ValueError("Per-sample gate result does not match its failures")


def validate_release_ai_quality_report(
    report: Any,
    *,
    expected_commit: str | None = None,
    expected_model_sha256: str | None = None,
) -> dict[str, Any]:
    """Reject fields or release bindings outside the sanitized schema."""
    top = _exact_object(
        report,
        frozenset(
            {
                "schema_version",
                "generated_at",
                "release_commit",
                "sample_set",
                "generation",
                "metrics",
                "coverage",
                "divergence_counts",
                "per_sample",
                "gate",
            }
        ),
        "Release quality report",
    )
    if (
        type(top["schema_version"]) is not int
        or top["schema_version"] != REPORT_SCHEMA_VERSION
    ):
        raise ValueError("Release quality report schema version is unsupported")
    generated_at = top["generated_at"]
    if not isinstance(generated_at, str):
        raise ValueError("Release quality report timestamp is invalid")
    try:
        parsed_timestamp = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise ValueError("Release quality report timestamp is invalid") from exc
    if parsed_timestamp.tzinfo is None:
        raise ValueError("Release quality report timestamp requires a timezone")
    commit = top["release_commit"]
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("Release quality report commit is invalid")
    if expected_commit is not None:
        if not COMMIT_PATTERN.fullmatch(expected_commit):
            raise ValueError("Expected release commit is invalid")
        if commit != expected_commit:
            raise ValueError("Release quality report commit does not match")

    sample_set = _exact_object(
        top["sample_set"], frozenset({"version", "sha256"}), "Sample set"
    )
    version = sample_set["version"]
    if not isinstance(version, str) or not SAFE_ID_PATTERN.fullmatch(version):
        raise ValueError("Sample-set version is invalid")
    sample_sha = sample_set["sha256"]
    if not isinstance(sample_sha, str) or not SHA_PATTERN.fullmatch(sample_sha):
        raise ValueError("Sample-set digest is invalid")

    generation = _exact_object(
        top["generation"],
        frozenset({"model_sha256", "temperature", "prompt_sha256"}),
        "Generation manifest",
    )
    model_hash = generation["model_sha256"]
    if not isinstance(model_hash, str) or not SHA_PATTERN.fullmatch(model_hash):
        raise ValueError("Generation model digest is invalid")
    if expected_model_sha256 is not None:
        if not SHA_PATTERN.fullmatch(expected_model_sha256):
            raise ValueError("Expected model digest is invalid")
        if model_hash != expected_model_sha256:
            raise ValueError("Generation model digest does not match")
    if _finite_number(generation["temperature"], "Generation temperature") != 0:
        raise ValueError("Generation temperature must be zero")
    prompt_sha = generation["prompt_sha256"]
    if not isinstance(prompt_sha, str) or not SHA_PATTERN.fullmatch(prompt_sha):
        raise ValueError("Prompt digest is invalid")

    metrics = _exact_object(top["metrics"], METRIC_KEYS, "Aggregate metrics")
    for key, value in metrics.items():
        _finite_number(value, f"Aggregate metric {key}")
    coverage = _exact_object(top["coverage"], COVERAGE_KEYS, "Coverage")
    for key, value in coverage.items():
        _nonnegative_integer(value, f"Coverage {key}")
    divergences = _exact_object(
        top["divergence_counts"], DIVERGENCE_KEYS, "Divergence counts"
    )
    for key, value in divergences.items():
        _nonnegative_integer(value, f"Divergence count {key}")

    per_sample = top["per_sample"]
    if not isinstance(per_sample, list):
        raise ValueError("Per-sample report must be a list")
    for sample in per_sample:
        _validate_per_sample(sample)
    if coverage["samples"] != len(per_sample):
        raise ValueError("Coverage count does not match per-sample results")

    gate = _exact_object(
        top["gate"],
        frozenset({"passed", "failures", "aggregate_thresholds"}),
        "Aggregate gate",
    )
    if not isinstance(gate["passed"], bool):
        raise ValueError("Aggregate gate result must be boolean")
    failures = _failure_list(
        gate["failures"], AGGREGATE_FAILURE_CODES, "Aggregate gate"
    )
    if gate["passed"] == bool(failures):
        raise ValueError("Aggregate gate result does not match its failures")
    validate_aggregate_thresholds(gate["aggregate_thresholds"])
    if gate["passed"] and (
        not per_sample or not all(row["gate"]["passed"] for row in per_sample)
    ):
        raise ValueError("Passing aggregate gate contains a failed or missing case")
    return top


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Validate and replace a JSON report without exposing partial output."""
    validate_release_ai_quality_report(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def build_infrastructure_failure_report(
    commit: str, expected_model_sha256: str
) -> dict[str, Any]:
    """Create a text-free report when the evaluator could not produce one."""
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("Release commit is invalid")
    if not SHA_PATTERN.fullmatch(expected_model_sha256):
        raise ValueError("Expected model digest is invalid")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_commit": commit,
        "sample_set": {"version": "unavailable", "sha256": "0" * 64},
        "generation": {
            "model_sha256": expected_model_sha256,
            "temperature": 0.0,
            "prompt_sha256": "0" * 64,
        },
        "metrics": {key: 0.0 for key in METRIC_KEYS},
        "coverage": {key: 0 for key in COVERAGE_KEYS},
        "divergence_counts": {key: 0 for key in DIVERGENCE_KEYS},
        "per_sample": [],
        "gate": {
            "passed": False,
            "failures": ["quality_report_unavailable_or_invalid"],
            "aggregate_thresholds": {
                key: 1.0 if key == "max_answer_length_ratio" else 0.0
                for key in THRESHOLD_KEYS
            },
        },
    }


def ensure_safe_report(path: Path, commit: str, expected_model_sha256: str) -> bool:
    """Validate an artifact or replace it with a safe failing report."""
    try:
        with path.open(encoding="utf-8") as handle:
            validate_release_ai_quality_report(
                json.load(handle),
                expected_commit=commit,
                expected_model_sha256=expected_model_sha256,
            )
    except (OSError, ValueError, json.JSONDecodeError):
        write_json_atomic(
            path,
            build_infrastructure_failure_report(commit, expected_model_sha256),
        )
        with path.open(encoding="utf-8") as handle:
            validate_release_ai_quality_report(
                json.load(handle),
                expected_commit=commit,
                expected_model_sha256=expected_model_sha256,
            )
        return False
    return True


def report_passed(path: Path, commit: str, expected_model_sha256: str) -> bool:
    """Return the pass result only after independently validating bindings."""
    with path.open(encoding="utf-8") as handle:
        report = validate_release_ai_quality_report(
            json.load(handle),
            expected_commit=commit,
            expected_model_sha256=expected_model_sha256,
        )
    return report["gate"]["passed"] is True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate release quality reports")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ensure = subparsers.add_parser("ensure")
    ensure.add_argument("--report", type=Path, required=True)
    ensure.add_argument("--commit", required=True)
    ensure.add_argument("--model-sha256", required=True)
    require_pass = subparsers.add_parser("require-pass")
    require_pass.add_argument("--report", type=Path, required=True)
    require_pass.add_argument("--commit", required=True)
    require_pass.add_argument("--model-sha256", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "ensure":
        try:
            unchanged = ensure_safe_report(args.report, args.commit, args.model_sha256)
        except (OSError, ValueError, json.JSONDecodeError):
            print("Could not prove release AI-quality report safety", flush=True)
            return 1
        if unchanged:
            print("Validated sanitized release AI-quality report")
        else:
            print("Replaced missing or invalid release AI-quality report", flush=True)
        return 0
    if args.command == "require-pass":
        try:
            passed = report_passed(args.report, args.commit, args.model_sha256)
        except (OSError, ValueError, json.JSONDecodeError):
            print("Release AI-quality report is not safely bound", flush=True)
            return 1
        if not passed:
            print("Release AI-quality report records a failing gate", flush=True)
            return 1
        print("Release AI-quality report records a passing gate")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
