#!/usr/bin/env python3
"""Generate and gate fresh release-candidate support answers.

The checked-in sample set contains reviewed questions, staff answers, labels, and
case-specific safety floors, but never generated answers. This harness queries
the running release-candidate API, reuses the staff-alignment behavior scorer,
and writes a sanitized report containing case IDs and metrics only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from app.channels.constants import REVIEW_QUEUE_ACTIONS
from app.scripts.release_ai_quality_report import (
    MODEL_ID_PATTERN,
    model_sha256,
    validate_aggregate_thresholds,
    write_json_atomic,
)
from app.scripts.retrieval_benchmark_harness import (
    DEFAULT_BEHAVIOR_THRESHOLDS,
    build_staff_alignment_behavior_summary,
)

FRESH_GATE_SCHEMA_VERSION = 1
SAMPLE_SET_SCHEMA_VERSION = 1
DEFAULT_SAMPLES_PATH = "api/data/evaluation/release_ai_quality_samples_v1.json"
DEFAULT_OUTPUT_PATH = "api/data/evaluation/release_ai_quality.summary.json"
DEFAULT_API_BASE_URL = "http://localhost:8000"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90.0

_SAFE_VERSION_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
_SAFE_MODEL_RE = MODEL_ID_PATTERN
_SAFE_TOOL_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
_SAFE_ROUTING_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
_SAFE_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_SAFE_ANSWER_TERM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.%-]{0,39}$")

_PROMPT_INPUTS = (
    "prompts/runtime_policy.py",
    "prompts/soul.py",
    "prompts/soul_default.md",
    "services/rag/prompt_manager.py",
)
_CASE_KINDS = frozenset({"standard", "live_data", "escalation"})
_REQUIRED_CASE_KINDS = frozenset({"live_data", "escalation"})
_SAMPLE_SET_KEYS = frozenset(
    {
        "schema_version",
        "sample_set_version",
        "reviewed",
        "sanitized",
        "aggregate_thresholds",
        "samples",
    }
)
_BEHAVIOR_LABEL_KEYS = frozenset(
    {
        "reviewed",
        "scam_warning_warranted",
        "staff_linked_wiki",
        "troubleshooting",
        "diagnostic_expected",
        "remedy_terms",
    }
)
_RELEASE_FLOOR_KEYS = frozenset(
    {
        "expected_metrics",
        "max_answer_length_ratio",
        "min_remedy_term_overlap",
        "delivery",
        "allowed_routing_actions",
        "required_mcp_tools",
        "required_answer_terms",
    }
)
_PER_CASE_BOOLEAN_METRICS = frozenset(
    {
        "leading_greeting_avoided",
        "scam_warning_present",
        "wiki_link_present",
        "diagnostic_question_present",
    }
)
_PER_CASE_METRIC_FAILURE_CODES = {
    metric: f"{metric}_mismatch" for metric in _PER_CASE_BOOLEAN_METRICS
}
_AGGREGATE_METRIC_GATES = (
    (
        "answer_length_ratio",
        "max_answer_length_ratio",
        "maximum",
        "answer_length_ratio_above_max",
    ),
    (
        "greeting_avoidance_rate",
        "min_greeting_avoidance_rate",
        "minimum",
        "greeting_avoidance_rate_below_min",
    ),
    (
        "scam_warning_precision",
        "min_scam_warning_precision",
        "minimum",
        "scam_warning_precision_below_min",
    ),
    (
        "scam_warning_recall",
        "min_scam_warning_recall",
        "minimum",
        "scam_warning_recall_below_min",
    ),
    (
        "wiki_link_recall",
        "min_wiki_link_recall",
        "minimum",
        "wiki_link_recall_below_min",
    ),
    (
        "diagnostic_question_rate",
        "min_diagnostic_question_rate",
        "minimum",
        "diagnostic_question_rate_below_min",
    ),
    (
        "remedy_term_overlap",
        "min_remedy_term_overlap",
        "minimum",
        "remedy_term_overlap_below_min",
    ),
)
_AGGREGATE_COVERAGE_FAILURE_CODES = {
    "scam_warning_warranted": "scam_warning_positive_coverage_missing",
    "scam_warning_not_warranted": "scam_warning_negative_coverage_missing",
    "staff_linked_wiki": "wiki_link_coverage_missing",
    "troubleshooting": "troubleshooting_coverage_missing",
    "diagnostic_expected": "diagnostic_expected_coverage_missing",
    "remedy_term_samples": "remedy_term_coverage_missing",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prompt_bundle_sha256() -> str:
    app_dir = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for relative_path in _PROMPT_INPUTS:
        prompt_path = app_dir / relative_path
        if not prompt_path.is_file():
            raise ValueError(f"Prompt input is unavailable: {relative_path}")
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(prompt_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _release_commit() -> str:
    commit = os.getenv("RELEASE_AI_QUALITY_COMMIT", "").strip().lower()
    if not commit:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        commit = result.stdout.strip().lower()
    if not _SAFE_COMMIT_RE.fullmatch(commit):
        raise ValueError("Could not resolve a safe release commit identifier")
    return commit


def _validated_model_id() -> str:
    model_id = os.getenv("OPENAI_MODEL", "").strip()
    if not _SAFE_MODEL_RE.fullmatch(model_id):
        raise ValueError("OPENAI_MODEL must be explicitly set to a safe model ID")
    return model_id


def _require_zero_temperature() -> float:
    raw_temperature = os.getenv("LLM_TEMPERATURE", "").strip()
    try:
        temperature = float(raw_temperature)
    except ValueError as exc:
        raise ValueError("LLM_TEMPERATURE must be explicitly set to 0") from exc
    if temperature != 0.0:
        raise ValueError("LLM_TEMPERATURE must be 0 for release evaluation")
    return temperature


def _validate_api_url(api_url: str) -> str:
    normalized = api_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("API URL must be an HTTP(S) origin without credentials")
    return normalized


def _validate_behavior_labels(labels: Any) -> None:
    if (
        not isinstance(labels, dict)
        or set(labels) != _BEHAVIOR_LABEL_KEYS
        or labels.get("reviewed") is not True
    ):
        raise ValueError("Every release case requires reviewed behavior labels")
    for key in (
        "scam_warning_warranted",
        "staff_linked_wiki",
        "troubleshooting",
        "diagnostic_expected",
    ):
        if not isinstance(labels.get(key), bool):
            raise ValueError(f"Behavior label {key} must be boolean")
    remedy_terms = labels.get("remedy_terms")
    if not isinstance(remedy_terms, list) or any(
        not isinstance(term, str) or not term.strip() for term in remedy_terms
    ):
        raise ValueError("Behavior remedy_terms must be non-empty strings")


def _validate_release_floor(floor: Any) -> None:
    if not isinstance(floor, dict) or set(floor) != _RELEASE_FLOOR_KEYS:
        raise ValueError("Every release case requires a release_gate object")

    expected = floor.get("expected_metrics")
    if (
        not isinstance(expected, dict)
        or expected.get("leading_greeting_avoided") is not True
    ):
        raise ValueError(
            "Every release case must require leading_greeting_avoided=true"
        )
    unknown_metrics = set(expected).difference(_PER_CASE_BOOLEAN_METRICS)
    if unknown_metrics:
        raise ValueError(
            "Unknown per-case metrics: " + ", ".join(sorted(unknown_metrics))
        )
    if any(not isinstance(value, bool) for value in expected.values()):
        raise ValueError("Per-case expected metrics must be boolean")

    max_length = floor.get("max_answer_length_ratio")
    if (
        isinstance(max_length, bool)
        or not isinstance(max_length, (int, float))
        or not math.isfinite(float(max_length))
        or max_length <= 0
    ):
        raise ValueError("max_answer_length_ratio must be greater than zero")
    min_overlap = floor.get("min_remedy_term_overlap")
    if (
        isinstance(min_overlap, bool)
        or not isinstance(min_overlap, (int, float))
        or not math.isfinite(float(min_overlap))
        or not 0 <= min_overlap <= 1
    ):
        raise ValueError("min_remedy_term_overlap must be between zero and one")

    delivery = floor.get("delivery", "any")
    if delivery not in {"any", "review"}:
        raise ValueError("release_gate.delivery must be any or review")

    allowed_routing = floor.get("allowed_routing_actions", [])
    if not isinstance(allowed_routing, list) or any(
        not isinstance(action, str) or not _SAFE_ROUTING_RE.fullmatch(action)
        for action in allowed_routing
    ):
        raise ValueError("allowed_routing_actions contains an invalid action")

    required_tools = floor.get("required_mcp_tools", [])
    if not isinstance(required_tools, list) or any(
        not isinstance(tool, str) or not _SAFE_TOOL_RE.fullmatch(tool)
        for tool in required_tools
    ):
        raise ValueError("required_mcp_tools contains an invalid tool name")

    required_answer_terms = floor.get("required_answer_terms", [])
    if not isinstance(required_answer_terms, list) or any(
        not isinstance(term, str) or not _SAFE_ANSWER_TERM_RE.fullmatch(term)
        for term in required_answer_terms
    ):
        raise ValueError("required_answer_terms contains an invalid term")


def load_release_sample_set(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load and strictly validate a reviewed, answer-free release sample set."""
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    if (
        not isinstance(raw, dict)
        or set(raw) != _SAMPLE_SET_KEYS
        or type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != SAMPLE_SET_SCHEMA_VERSION
    ):
        raise ValueError("Unsupported release sample-set schema")
    if raw.get("reviewed") is not True or raw.get("sanitized") is not True:
        raise ValueError("Release sample set must be reviewed and sanitized")

    version = raw.get("sample_set_version")
    if not isinstance(version, str) or not _SAFE_VERSION_RE.fullmatch(version):
        raise ValueError("Release sample set requires a safe version")

    thresholds = raw.get("aggregate_thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != set(
        DEFAULT_BEHAVIOR_THRESHOLDS
    ):
        raise ValueError("Release sample set must pin every aggregate threshold")
    validate_aggregate_thresholds(thresholds)

    samples = raw.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("Release sample set must contain cases")

    case_ids: set[str] = set()
    case_kinds: set[str] = set()
    allowed_case_keys = {"case_id", "question", "ground_truth", "metadata"}
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != allowed_case_keys:
            raise ValueError("Release cases contain unsupported or generated fields")
        if "answer" in sample or "generated_answer" in sample:
            raise ValueError("Release sample inputs must not contain generated answers")

        case_id = sample.get("case_id")
        if not isinstance(case_id, str) or not _SAFE_VERSION_RE.fullmatch(case_id):
            raise ValueError("Every release case requires a safe case_id")
        if case_id in case_ids:
            raise ValueError(f"Duplicate release case_id: {case_id}")
        case_ids.add(case_id)

        for text_key in ("question", "ground_truth"):
            value = sample.get(text_key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Release case {case_id} requires {text_key}")

        metadata = sample.get("metadata")
        if not isinstance(metadata, dict) or set(metadata) != {
            "sanitized",
            "case_kind",
            "behavior_labels",
            "release_gate",
        }:
            raise ValueError(f"Release case {case_id} requires metadata")
        if metadata.get("sanitized") is not True:
            raise ValueError(f"Release case {case_id} must be marked sanitized")
        case_kind = metadata.get("case_kind")
        if case_kind not in _CASE_KINDS:
            raise ValueError(f"Release case {case_id} has an invalid case_kind")
        case_kinds.add(case_kind)
        _validate_behavior_labels(metadata.get("behavior_labels"))
        _validate_release_floor(metadata.get("release_gate"))
        release_floor = metadata["release_gate"]
        if case_kind == "live_data" and not release_floor["required_mcp_tools"]:
            raise ValueError(f"Live-data case {case_id} must require an MCP tool")
        if case_kind == "live_data" and not release_floor["required_answer_terms"]:
            raise ValueError(f"Live-data case {case_id} must require answer evidence")
        if case_kind == "escalation" and release_floor["delivery"] != "review":
            raise ValueError(f"Escalation case {case_id} must require review delivery")

    missing_kinds = _REQUIRED_CASE_KINDS.difference(case_kinds)
    if missing_kinds:
        raise ValueError(
            "Release sample coverage is missing: " + ", ".join(sorted(missing_kinds))
        )

    return raw, samples


def _source_urls(response: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    sources = response.get("sources", [])
    if not isinstance(sources, list):
        return urls
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def _mcp_tool_names(response: dict[str, Any]) -> list[str]:
    names: list[str] = []
    tools = response.get("mcp_tools_used", [])
    if not isinstance(tools, list):
        return names
    for tool in tools:
        name = tool.get("tool") if isinstance(tool, dict) else None
        if isinstance(name, str) and _SAFE_TOOL_RE.fullmatch(name):
            names.append(name)
    return sorted(set(names))


async def generate_fresh_rows(
    client: httpx.AsyncClient,
    *,
    api_url: str,
    samples: list[dict[str, Any]],
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """Query the full chat pipeline and return transient scorer rows."""
    readiness = await client.get(f"{api_url}/health/ready", timeout=10.0)
    readiness.raise_for_status()
    readiness_data = readiness.json()
    if readiness_data.get("status") != "ready":
        raise RuntimeError("Release-candidate API is not ready")

    rows: list[dict[str, Any]] = []
    for sample in samples:
        case_id = str(sample["case_id"])
        request_error: str | None = None
        response_data: dict[str, Any] = {}
        try:
            response = await client.post(
                f"{api_url}/chat/query",
                json={"question": sample["question"], "chat_history": []},
                timeout=timeout_seconds,
            )
            if response.status_code >= 400:
                request_error = "http_error"
            else:
                parsed = response.json()
                if not isinstance(parsed, dict):
                    request_error = "invalid_response"
                else:
                    response_data = parsed
        except httpx.TimeoutException:
            request_error = "timeout"
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            request_error = "request_failed"

        answer = response_data.get("answer")
        if not isinstance(answer, str):
            answer = ""

        routing_action = response_data.get("routing_action")
        if not isinstance(routing_action, str) or not _SAFE_ROUTING_RE.fullmatch(
            routing_action
        ):
            routing_action = ""

        rows.append(
            {
                "case_id": case_id,
                "question": sample["question"],
                "ground_truth": sample["ground_truth"],
                "answer": answer,
                "source_urls": _source_urls(response_data),
                "metadata": sample["metadata"],
                "release_response": {
                    "request_error": request_error,
                    "requires_human": response_data.get("requires_human") is True,
                    "routing_action": routing_action,
                    "mcp_tools": _mcp_tool_names(response_data),
                },
            }
        )
        print(f"Generated fresh release answer for case {case_id}")
    return rows


def _score_release_contract(
    row: dict[str, Any], behavior_score: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    floor = row["metadata"]["release_gate"]
    response = row["release_response"]
    failures: list[str] = []

    if response["request_error"] is not None:
        failures.append("request_failed")
    if not str(row.get("answer", "")).strip():
        failures.append("empty_answer")

    for metric_name, expected in sorted(floor["expected_metrics"].items()):
        actual = behavior_score[metric_name]
        if actual is not expected:
            failures.append(_PER_CASE_METRIC_FAILURE_CODES[metric_name])

    max_ratio = float(floor["max_answer_length_ratio"])
    if float(behavior_score["answer_length_ratio"]) > max_ratio:
        failures.append("answer_length_ratio_above_max")

    min_overlap = float(floor["min_remedy_term_overlap"])
    if float(behavior_score["remedy_term_overlap"]) < min_overlap:
        failures.append("remedy_term_overlap_below_min")

    routing_action = response["routing_action"]
    if floor.get("delivery") == "review" and not (
        response["requires_human"] or routing_action in REVIEW_QUEUE_ACTIONS
    ):
        failures.append("review_delivery_required")

    allowed_routing = set(floor.get("allowed_routing_actions", []))
    if allowed_routing and routing_action not in allowed_routing:
        failures.append("routing_action_not_allowed")

    actual_tools = set(response["mcp_tools"])
    missing_tools = set(floor.get("required_mcp_tools", [])).difference(actual_tools)
    if missing_tools:
        failures.append("required_mcp_tool_missing")

    normalized_answer = str(row.get("answer", "")).casefold()
    if any(
        re.search(rf"(?<!\w){re.escape(term.casefold())}(?!\w)", normalized_answer)
        is None
        for term in floor.get("required_answer_terms", [])
    ):
        failures.append("required_answer_term_missing")

    safe_contract = {
        "request_error": response["request_error"],
        "requires_human": response["requires_human"],
        "routing_action": routing_action,
        "mcp_tools": response["mcp_tools"],
    }
    return safe_contract, list(dict.fromkeys(failures))


def _aggregate_failure_codes(behavior: dict[str, Any]) -> list[str]:
    metrics = behavior["metrics"]
    coverage = behavior["coverage"]
    thresholds = behavior["gate"]["thresholds"]
    failures: list[str] = []

    for metric_name, threshold_name, bound, failure_code in _AGGREGATE_METRIC_GATES:
        value = float(metrics[metric_name])
        threshold = float(thresholds[threshold_name])
        passed = value <= threshold if bound == "maximum" else value >= threshold
        if not passed:
            failures.append(failure_code)

    for coverage_name, failure_code in _AGGREGATE_COVERAGE_FAILURE_CODES.items():
        if int(coverage[coverage_name]) == 0:
            failures.append(failure_code)

    if int(behavior["divergence_counts"]["answer_too_long"]) > 0:
        failures.append("per_sample_answer_length_ratio_above_max")

    return failures


def build_release_gate_summary(
    rows: list[dict[str, Any]],
    *,
    sample_manifest: dict[str, Any],
    sample_sha256: str,
    model_id: str,
    temperature: float,
    prompt_sha256: str,
    commit: str,
) -> dict[str, Any]:
    """Score fresh rows and return a report safe for build artifacts."""
    behavior = build_staff_alignment_behavior_summary(
        rows,
        thresholds={
            key: float(value)
            for key, value in sample_manifest["aggregate_thresholds"].items()
        },
        input_sha256=sample_sha256,
    )

    per_sample: list[dict[str, Any]] = []
    any_case_failed = False
    for row, behavior_score in zip(rows, behavior["per_sample"], strict=True):
        safe_contract, failures = _score_release_contract(row, behavior_score)
        any_case_failed = any_case_failed or bool(failures)
        per_sample.append(
            {
                **behavior_score,
                "case_kind": row["metadata"]["case_kind"],
                "response_contract": safe_contract,
                "gate": {"passed": not failures, "failures": failures},
            }
        )

    failures = _aggregate_failure_codes(behavior)
    if any_case_failed:
        failures.append("per_sample_gate_failed")
    return {
        "schema_version": FRESH_GATE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_commit": commit,
        "sample_set": {
            "version": sample_manifest["sample_set_version"],
            "sha256": sample_sha256,
        },
        "generation": {
            "model_sha256": model_sha256(model_id),
            "temperature": temperature,
            "prompt_sha256": prompt_sha256,
        },
        "metrics": behavior["metrics"],
        "coverage": behavior["coverage"],
        "divergence_counts": behavior["divergence_counts"],
        "per_sample": per_sample,
        "gate": {
            "passed": not failures,
            "failures": failures,
            "aggregate_thresholds": behavior["gate"]["thresholds"],
        },
    }


async def run_release_gate(args: argparse.Namespace) -> int:
    samples_path = Path(args.samples)
    sample_manifest, samples = load_release_sample_set(samples_path)
    api_url = _validate_api_url(args.api_url)
    model_id = _validated_model_id()
    temperature = _require_zero_temperature()

    async with httpx.AsyncClient() as client:
        rows = await generate_fresh_rows(
            client,
            api_url=api_url,
            samples=samples,
            timeout_seconds=args.request_timeout,
        )

    summary = build_release_gate_summary(
        rows,
        sample_manifest=sample_manifest,
        sample_sha256=_sha256_file(samples_path),
        model_id=model_id,
        temperature=temperature,
        prompt_sha256=_prompt_bundle_sha256(),
        commit=_release_commit(),
    )

    output_path = Path(args.output)
    write_json_atomic(output_path, summary)

    print(f"Saved sanitized release AI-quality report: {output_path}")
    if summary["gate"]["passed"]:
        print("Fresh-answer release AI-quality gate passed")
        return 0

    print("Fresh-answer release AI-quality gate failed:")
    for failure in summary["gate"]["failures"]:
        print(f"  - {failure}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and gate fresh release-candidate support answers"
    )
    parser.add_argument("--samples", default=DEFAULT_SAMPLES_PATH)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--api-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.request_timeout <= 0:
        print("Error: request timeout must be greater than zero")
        return 2
    try:
        return asyncio.run(run_release_gate(args))
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        httpx.HTTPError,
    ) as exc:
        print(f"Error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
