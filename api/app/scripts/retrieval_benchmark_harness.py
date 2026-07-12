#!/usr/bin/env python3
"""Retrieval benchmark harness for repeated RAGAS runs and A/B comparisons.

Usage examples:

Create strict lockfile:
    python -m app.scripts.retrieval_benchmark_harness lock \
      --output /data/evaluation/benchmarks/retrieval_strict.lock.json \
      --samples /data/evaluation/matrix_realistic_qa_samples_30_20260211.json \
      --backend qdrant \
      --run-name qdrant_strict \
      --kb-manifest /data/evaluation/kb_snapshots/kb_2026_02_11/manifest.json

Run repeated evaluation:
    python -m app.scripts.retrieval_benchmark_harness run \
      --lock-file /data/evaluation/benchmarks/retrieval_strict.lock.json

Compare two benchmark summaries:
    python -m app.scripts.retrieval_benchmark_harness compare \
      --baseline /data/evaluation/benchmarks/qdrant_baseline.summary.json \
      --candidate /data/evaluation/benchmarks/qdrant_current.summary.json \
      --output /data/evaluation/benchmarks/qdrant_compare.json
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import mean, stdev
from typing import Any
from urllib.parse import urlparse

# Keep direct-script imports aligned with module execution from the API root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING  # noqa: E402

DEFAULT_OUTPUT_DIR = "api/data/evaluation/benchmarks"
DEFAULT_API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
LOCK_SCHEMA_VERSION = 1
DEFAULT_READINESS_TIMEOUT = 300
DEFAULT_READINESS_POLL = 5
DEFAULT_PROBE_QUESTION = "Health probe question"
DEFAULT_PROBE_FAIL_PHRASES = ["not fully initialized", "not initialized"]
BEHAVIOR_SCHEMA_VERSION = 1
DEFAULT_BEHAVIOR_OUTPUT = "api/data/evaluation/staff_alignment_behavior.summary.json"
DEFAULT_BEHAVIOR_THRESHOLDS = {
    "max_answer_length_ratio": 1.50,
    "min_greeting_avoidance_rate": 0.95,
    "min_scam_warning_precision": 0.80,
    "min_scam_warning_recall": 1.00,
    "min_wiki_link_recall": 0.90,
    "min_diagnostic_question_rate": 0.75,
    "min_remedy_term_overlap": 0.80,
}
BEHAVIOR_DIVERGENCE_KEYS = (
    "answer_too_long",
    "leading_greeting",
    "scam_warning_missing",
    "scam_warning_false_positive",
    "wiki_link_missing",
    "diagnostic_question_missing",
    "remedy_term_missing",
)
_BEHAVIOR_GATE_SPECS = (
    ("greeting_avoidance_rate", "min_greeting_avoidance_rate", "minimum"),
    ("scam_warning_precision", "min_scam_warning_precision", "minimum"),
    ("scam_warning_recall", "min_scam_warning_recall", "minimum"),
    ("wiki_link_recall", "min_wiki_link_recall", "minimum"),
    ("diagnostic_question_rate", "min_diagnostic_question_rate", "minimum"),
    ("remedy_term_overlap", "min_remedy_term_overlap", "minimum"),
)

_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)
_LEADING_GREETING_RE = re.compile(
    r"^\s*(?:hi|hello|hey|good\s+(?:morning|afternoon|evening))\b",
    re.IGNORECASE,
)
_URL_CANDIDATE_RE = re.compile(r"https?://[^\s<>()\[\]{}]+", re.IGNORECASE)
_SAFE_CASE_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_phrase(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _has_scam_warning(answer: str) -> bool:
    normalized_answer = " ".join(str(answer or "").split())
    normalized_warning = " ".join(SAFETY_REFLEX_WARNING.split())
    return normalized_warning in normalized_answer


def _has_bisq_wiki_link(text: str) -> bool:
    for match in _URL_CANDIDATE_RE.findall(text):
        candidate = match.rstrip(".,;:!?\"'")
        try:
            parsed = urlparse(candidate)
            if (
                parsed.scheme.lower() == "https"
                and parsed.hostname == "bisq.wiki"
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
            ):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _rate(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 1.0


def _behavior_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    choices = " or ".join(f"`{key}`" for key in keys)
    raise ValueError(f"Behavior row requires a non-empty {choices} string")


def _behavior_labels(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Behavior row requires a metadata object")
    labels = metadata.get("behavior_labels")
    if not isinstance(labels, dict) or labels.get("reviewed") is not True:
        raise ValueError("Behavior row requires metadata.behavior_labels.reviewed=true")

    for key in (
        "scam_warning_warranted",
        "staff_linked_wiki",
        "troubleshooting",
        "diagnostic_expected",
    ):
        if not isinstance(labels.get(key), bool):
            raise ValueError(
                f"Behavior row requires boolean metadata.behavior_labels.{key}"
            )

    remedy_terms = labels.get("remedy_terms")
    if not isinstance(remedy_terms, list) or any(
        not isinstance(term, str) or not term.strip() or not _normalized_phrase(term)
        for term in remedy_terms
    ):
        raise ValueError(
            "Behavior row requires metadata.behavior_labels.remedy_terms as "
            "a list of non-empty strings"
        )
    return labels


def _generated_source_urls(row: dict[str, Any]) -> list[str]:
    """Return validated generated-response source URLs, when present."""
    raw_urls = row.get("source_urls", [])
    if raw_urls is None:
        return []
    if not isinstance(raw_urls, list) or any(
        not isinstance(url, str) or not url.strip() for url in raw_urls
    ):
        raise ValueError("Behavior row source_urls must be a list of non-empty strings")
    return [url.strip() for url in raw_urls]


def _load_behavior_rows(input_path: str) -> list[dict[str, Any]]:
    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        raw = raw.get("individual_results")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "Behavior input must be a non-empty JSON list or an evaluation result "
            "with `individual_results`"
        )
    if any(not isinstance(row, dict) for row in raw):
        raise ValueError("Every behavior input row must be a JSON object")
    return raw


def _validate_behavior_thresholds(thresholds: dict[str, float]) -> None:
    max_ratio = thresholds["max_answer_length_ratio"]
    if max_ratio <= 0:
        raise ValueError("max_answer_length_ratio must be greater than zero")
    for name, value in thresholds.items():
        if name == "max_answer_length_ratio":
            continue
        if value < 0 or value > 1:
            raise ValueError(f"{name} must be between 0 and 1")


def _score_behavior_sample(
    row: dict[str, Any], index: int, max_answer_length_ratio: float
) -> dict[str, Any]:
    _behavior_text(row, "question")
    staff_answer = _behavior_text(row, "ground_truth", "staff_answer")
    generated_answer = _behavior_text(row, "answer", "generated_answer")
    generated_source_urls = _generated_source_urls(row)
    labels = _behavior_labels(row)

    staff_word_count = len(_WORD_RE.findall(staff_answer))
    generated_word_count = len(_WORD_RE.findall(generated_answer))
    if staff_word_count == 0:
        raise ValueError("Behavior row staff answer must contain at least one word")

    case_id = row.get("case_id")
    if case_id is None:
        case_id = f"sample_{index + 1:03d}"
    if not isinstance(case_id, str) or not _SAFE_CASE_ID_RE.fullmatch(case_id):
        raise ValueError(
            "Behavior row case_id must use only letters, digits, dot, underscore, "
            "or hyphen (maximum 80 characters)"
        )

    answer_length_ratio = generated_word_count / staff_word_count
    leading_greeting_avoided = not bool(_LEADING_GREETING_RE.search(generated_answer))
    scam_warning_present = _has_scam_warning(generated_answer)
    wiki_link_present = bool(
        _has_bisq_wiki_link(generated_answer)
        or any(_has_bisq_wiki_link(url) for url in generated_source_urls)
    )
    diagnostic_question_present = generated_answer.count("?") == 1

    normalized_answer = f" {_normalized_phrase(generated_answer)} "
    remedy_terms = [str(term).strip() for term in labels["remedy_terms"]]
    matched_remedy_terms = sum(
        1
        for term in remedy_terms
        if f" {_normalized_phrase(term)} " in normalized_answer
    )
    remedy_term_overlap = _rate(matched_remedy_terms, len(remedy_terms))

    divergences: list[str] = []
    if answer_length_ratio > max_answer_length_ratio:
        divergences.append("answer_too_long")
    if not leading_greeting_avoided:
        divergences.append("leading_greeting")
    if labels["scam_warning_warranted"] and not scam_warning_present:
        divergences.append("scam_warning_missing")
    if not labels["scam_warning_warranted"] and scam_warning_present:
        divergences.append("scam_warning_false_positive")
    if labels["staff_linked_wiki"] and not wiki_link_present:
        divergences.append("wiki_link_missing")
    if labels["diagnostic_expected"] and not diagnostic_question_present:
        divergences.append("diagnostic_question_missing")
    if remedy_terms and matched_remedy_terms < len(remedy_terms):
        divergences.append("remedy_term_missing")

    # Keep the report safe to persist: no question, answer, sender, or event text.
    return {
        "case_id": case_id,
        "answer_length_ratio": round(answer_length_ratio, 6),
        "leading_greeting_avoided": leading_greeting_avoided,
        "scam_warning_warranted": labels["scam_warning_warranted"],
        "scam_warning_present": scam_warning_present,
        "staff_linked_wiki": labels["staff_linked_wiki"],
        "wiki_link_present": wiki_link_present,
        "troubleshooting": labels["troubleshooting"],
        "diagnostic_expected": labels["diagnostic_expected"],
        "diagnostic_question_present": diagnostic_question_present,
        "remedy_terms_expected": len(remedy_terms),
        "remedy_terms_matched": matched_remedy_terms,
        "remedy_term_overlap": round(remedy_term_overlap, 6),
        "divergences": divergences,
    }


def _gate_behavior_summary(
    metrics: dict[str, float],
    coverage: dict[str, int],
    thresholds: dict[str, float],
    divergence_counts: dict[str, int],
) -> list[str]:
    failures: list[str] = []
    for metric_name, threshold_name, bound in _BEHAVIOR_GATE_SPECS:
        value = metrics[metric_name]
        threshold = thresholds[threshold_name]
        passed = value <= threshold if bound == "maximum" else value >= threshold
        if not passed:
            relation = "exceeds" if bound == "maximum" else "below"
            failures.append(
                f"{metric_name}: {value:.4f} {relation} {bound} {threshold:.4f}"
            )

    coverage_checks = {
        "scam-positive": coverage["scam_warning_warranted"],
        "scam-negative": coverage["scam_warning_not_warranted"],
        "wiki-link": coverage["staff_linked_wiki"],
        "troubleshooting": coverage["troubleshooting"],
        "diagnostic-expected": coverage["diagnostic_expected"],
        "remedy-term": coverage["remedy_term_samples"],
    }
    failures.extend(
        f"coverage: no reviewed {name} samples"
        for name, count in coverage_checks.items()
        if count == 0
    )
    if divergence_counts["answer_too_long"]:
        failures.append(
            "answer_length_ratio: "
            f"{divergence_counts['answer_too_long']} sample(s) exceed maximum "
            f"{thresholds['max_answer_length_ratio']:.4f}"
        )
    return failures


def build_staff_alignment_behavior_summary(
    rows: list[dict[str, Any]],
    *,
    thresholds: dict[str, float] | None = None,
    input_sha256: str | None = None,
) -> dict[str, Any]:
    """Score reviewed, precomputed staff/AI answer pairs without I/O or models."""
    if not rows:
        raise ValueError("Behavior scoring requires at least one row")

    resolved_thresholds = dict(DEFAULT_BEHAVIOR_THRESHOLDS)
    if thresholds:
        unknown = set(thresholds) - set(DEFAULT_BEHAVIOR_THRESHOLDS)
        if unknown:
            raise ValueError(
                f"Unknown behavior thresholds: {', '.join(sorted(unknown))}"
            )
        resolved_thresholds.update(thresholds)
    _validate_behavior_thresholds(resolved_thresholds)

    per_sample = [
        _score_behavior_sample(
            row, index, resolved_thresholds["max_answer_length_ratio"]
        )
        for index, row in enumerate(rows)
    ]

    scam_true_positives = sum(
        1
        for row in per_sample
        if row["scam_warning_warranted"] and row["scam_warning_present"]
    )
    scam_false_positives = sum(
        1
        for row in per_sample
        if not row["scam_warning_warranted"] and row["scam_warning_present"]
    )
    scam_positives = sum(1 for row in per_sample if row["scam_warning_warranted"])
    wiki_expected = sum(1 for row in per_sample if row["staff_linked_wiki"])
    wiki_present = sum(
        1 for row in per_sample if row["staff_linked_wiki"] and row["wiki_link_present"]
    )
    troubleshooting = sum(1 for row in per_sample if row["troubleshooting"])
    diagnostic_expected = sum(1 for row in per_sample if row["diagnostic_expected"])
    diagnostics_present = sum(
        1
        for row in per_sample
        if row["diagnostic_expected"] and row["diagnostic_question_present"]
    )
    remedy_samples = [row for row in per_sample if row["remedy_terms_expected"] > 0]

    metrics = {
        "answer_length_ratio": round(
            _safe_mean([row["answer_length_ratio"] for row in per_sample]), 6
        ),
        "greeting_avoidance_rate": round(
            _rate(
                sum(1 for row in per_sample if row["leading_greeting_avoided"]),
                len(per_sample),
            ),
            6,
        ),
        "scam_warning_precision": round(
            _rate(scam_true_positives, scam_true_positives + scam_false_positives),
            6,
        ),
        "scam_warning_recall": round(_rate(scam_true_positives, scam_positives), 6),
        "wiki_link_recall": round(_rate(wiki_present, wiki_expected), 6),
        "diagnostic_question_rate": round(
            _rate(diagnostics_present, diagnostic_expected), 6
        ),
        "remedy_term_overlap": round(
            _rate(
                sum(row["remedy_terms_matched"] for row in remedy_samples),
                sum(row["remedy_terms_expected"] for row in remedy_samples),
            ),
            6,
        ),
    }
    coverage = {
        "samples": len(per_sample),
        "scam_warning_warranted": scam_positives,
        "scam_warning_not_warranted": len(per_sample) - scam_positives,
        "staff_linked_wiki": wiki_expected,
        "troubleshooting": troubleshooting,
        "diagnostic_expected": diagnostic_expected,
        "remedy_term_samples": len(remedy_samples),
        "remedy_terms_expected": sum(
            row["remedy_terms_expected"] for row in remedy_samples
        ),
    }
    divergence_counts = {key: 0 for key in BEHAVIOR_DIVERGENCE_KEYS}
    for row in per_sample:
        for divergence in row["divergences"]:
            divergence_counts[divergence] += 1

    failures = _gate_behavior_summary(
        metrics, coverage, resolved_thresholds, divergence_counts
    )
    return {
        "schema_version": BEHAVIOR_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "input_sha256": input_sha256,
        "samples_count": len(per_sample),
        "metrics": metrics,
        "coverage": coverage,
        "divergence_counts": divergence_counts,
        "per_sample": per_sample,
        "gate": {
            "passed": not failures,
            "failures": failures,
            "thresholds": resolved_thresholds,
        },
    }


def run_staff_alignment_behavior(args: argparse.Namespace) -> int:
    """Score and gate precomputed rows without database, API, or model calls."""
    rows = _load_behavior_rows(args.input)
    thresholds = {
        name: float(getattr(args, name)) for name in DEFAULT_BEHAVIOR_THRESHOLDS
    }
    summary = build_staff_alignment_behavior_summary(
        rows,
        thresholds=thresholds,
        input_sha256=_file_sha256(args.input),
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Saved staff-alignment behavior summary: {output_path}")
    for metric, value in summary["metrics"].items():
        print(f"  {metric}: {value:.4f}")
    if summary["gate"]["passed"]:
        print("Staff-alignment behavior gate passed")
        return 0

    print("Staff-alignment behavior gate failed:")
    for failure in summary["gate"]["failures"]:
        print(f"  - {failure}")
    return 1


def _run_cmd(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return out.stdout.strip()
    except Exception:
        return None


def _collect_git_info() -> dict[str, Any]:
    commit = _run_cmd(["git", "rev-parse", "HEAD"])
    branch = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    dirty = _run_cmd(["git", "status", "--porcelain"])
    return {
        "commit": commit,
        "branch": branch,
        "dirty": bool(dirty),
    }


def _collect_dependency_versions() -> dict[str, str | None]:
    pkgs = ["ragas", "datasets", "langchain-openai", "openai", "httpx"]
    out: dict[str, str | None] = {}
    for pkg in pkgs:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = None
    return out


def _expected_environment() -> dict[str, Any]:
    return {
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL"),
        "OPENAI_EMBEDDING_MODEL": os.getenv("OPENAI_EMBEDDING_MODEL"),
        "OPENAI_API_KEY_SET": bool(os.getenv("OPENAI_API_KEY")),
    }


def _build_lock_data(args: argparse.Namespace) -> dict[str, Any]:
    samples_sha = _file_sha256(args.samples)
    kb_sha = _file_sha256(args.kb_manifest) if args.kb_manifest else None
    metrics = _parse_csv_arg(args.metrics)
    bypass_hooks = _parse_csv_arg(args.bypass_hooks)
    fail_phrases = _parse_csv_arg(args.probe_fail_phrases) or DEFAULT_PROBE_FAIL_PHRASES

    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "created_at": _now_iso(),
        "api_url": args.api_url,
        "backend": args.backend,
        "samples": {
            "path": args.samples,
            "sha256": samples_sha,
        },
        "knowledge_base_manifest": (
            {"path": args.kb_manifest, "sha256": kb_sha} if args.kb_manifest else None
        ),
        "run_config": {
            "run_name": args.run_name,
            "output_dir": args.output_dir,
            "repeats": args.repeats,
            "sleep_between": args.sleep_between,
            "max_samples": args.max_samples,
            "simple": args.simple,
            "metrics": metrics,
            "bypass_hooks": bypass_hooks,
            "ragas_timeout": args.ragas_timeout,
            "ragas_max_retries": args.ragas_max_retries,
            "ragas_max_wait": args.ragas_max_wait,
            "ragas_max_workers": args.ragas_max_workers,
            "ragas_batch_size": args.ragas_batch_size,
        },
        "readiness": {
            "timeout_seconds": args.readiness_timeout,
            "poll_seconds": args.readiness_poll,
            "probe_question": args.probe_question,
            "fail_phrases": fail_phrases,
        },
        "expected_environment": _expected_environment(),
    }


def _validate_lock_schema(lock_data: dict[str, Any]) -> None:
    schema = lock_data.get("schema_version")
    if schema != LOCK_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported lock schema version {schema}, expected {LOCK_SCHEMA_VERSION}"
        )


def _validate_expected_environment(lock_data: dict[str, Any]) -> None:
    expected = lock_data.get("expected_environment") or {}
    if not isinstance(expected, dict):
        return
    current = _expected_environment()
    for key in ("OPENAI_MODEL", "OPENAI_EMBEDDING_MODEL", "OPENAI_API_KEY_SET"):
        if key in expected and expected.get(key) != current.get(key):
            raise ValueError(
                f"Environment mismatch for {key}: "
                f"lock={expected.get(key)!r} current={current.get(key)!r}"
            )


def _resolve_run_args_from_lock(args: argparse.Namespace) -> argparse.Namespace:
    if not args.lock_file:
        if not args.samples or not args.backend or not args.run_name:
            raise ValueError(
                "--samples, --backend and --run-name are required without --lock-file."
            )
        return args

    with open(args.lock_file) as f:
        lock_data = json.load(f)
    _validate_lock_schema(lock_data)

    args.api_url = str(lock_data.get("api_url") or args.api_url or DEFAULT_API_BASE_URL)
    args.backend = str(lock_data["backend"])
    args.samples = str(lock_data["samples"]["path"])
    args.kb_manifest = (
        str((lock_data.get("knowledge_base_manifest") or {}).get("path"))
        if lock_data.get("knowledge_base_manifest")
        else None
    )

    run_cfg = lock_data.get("run_config") or {}
    args.run_name = str(run_cfg.get("run_name") or args.run_name)
    args.output_dir = str(run_cfg.get("output_dir") or args.output_dir)
    args.repeats = int(run_cfg.get("repeats", args.repeats))
    args.sleep_between = float(run_cfg.get("sleep_between", args.sleep_between))
    args.max_samples = run_cfg.get("max_samples")
    args.simple = bool(run_cfg.get("simple", args.simple))
    args.metrics = (
        ",".join(run_cfg["metrics"])
        if isinstance(run_cfg.get("metrics"), list)
        else args.metrics
    )
    args.bypass_hooks = (
        ",".join(run_cfg["bypass_hooks"])
        if isinstance(run_cfg.get("bypass_hooks"), list)
        else args.bypass_hooks
    )
    args.ragas_timeout = run_cfg.get("ragas_timeout")
    args.ragas_max_retries = run_cfg.get("ragas_max_retries")
    args.ragas_max_wait = run_cfg.get("ragas_max_wait")
    args.ragas_max_workers = run_cfg.get("ragas_max_workers")
    args.ragas_batch_size = run_cfg.get("ragas_batch_size")

    readiness = lock_data.get("readiness") or {}
    args.readiness_timeout = int(
        readiness.get("timeout_seconds", args.readiness_timeout)
    )
    args.readiness_poll = int(readiness.get("poll_seconds", args.readiness_poll))
    args.probe_question = str(readiness.get("probe_question", args.probe_question))
    fail_phrases = readiness.get("fail_phrases")
    if isinstance(fail_phrases, list):
        args.probe_fail_phrases = ",".join(str(x) for x in fail_phrases)

    return args


def _validate_lock_hashes(args: argparse.Namespace) -> tuple[str, str | None, str]:
    lock_sha = _file_sha256(args.lock_file) if args.lock_file else ""
    samples_sha = _file_sha256(args.samples)
    kb_sha = _file_sha256(args.kb_manifest) if args.kb_manifest else None

    if not args.lock_file:
        return samples_sha, kb_sha, lock_sha

    with open(args.lock_file) as f:
        lock_data = json.load(f)

    lock_sample_sha = str((lock_data.get("samples") or {}).get("sha256") or "")
    if samples_sha != lock_sample_sha:
        raise ValueError(
            f"Sample hash mismatch: lock={lock_sample_sha} current={samples_sha}"
        )

    lock_kb = lock_data.get("knowledge_base_manifest")
    if lock_kb:
        lock_kb_sha = str(lock_kb.get("sha256") or "")
        if kb_sha != lock_kb_sha:
            raise ValueError(
                f"KB manifest hash mismatch: lock={lock_kb_sha} current={kb_sha}"
            )

    _validate_expected_environment(lock_data)
    return samples_sha, kb_sha, lock_sha


async def _wait_for_api_readiness(
    *,
    api_url: str,
    timeout_seconds: int,
    poll_seconds: int,
    probe_question: str,
    fail_phrases: list[str],
    bypass_hooks: list[str] | None,
) -> dict[str, Any]:
    import httpx

    started = time.time()
    attempts = 0
    last_error = ""
    health_payload: dict[str, Any] = {}

    async with httpx.AsyncClient() as client:
        while time.time() - started <= timeout_seconds:
            attempts += 1
            try:
                health_res = await client.get(f"{api_url}/health", timeout=10.0)
                health_res.raise_for_status()
                health_payload = health_res.json()

                payload: dict[str, Any] = {
                    "question": probe_question,
                    "chat_history": [],
                }
                if bypass_hooks:
                    payload["bypass_hooks"] = bypass_hooks
                probe_res = await client.post(
                    f"{api_url}/chat/query",
                    json=payload,
                    timeout=60.0,
                )
                probe_res.raise_for_status()
                answer = str((probe_res.json() or {}).get("answer") or "").strip()
                if answer and all(
                    p.lower() not in answer.lower() for p in fail_phrases
                ):
                    return {
                        "ready": True,
                        "attempts": attempts,
                        "elapsed_seconds": round(time.time() - started, 3),
                        "health": health_payload,
                        "probe_answer_preview": answer[:160],
                    }
                last_error = "Probe answer still indicates non-ready state"
            except Exception as e:
                last_error = str(e)
            await asyncio.sleep(poll_seconds)

    raise RuntimeError(
        f"API readiness check failed after {timeout_seconds}s and {attempts} attempts: {last_error}"
    )


def _runtime_manifest(
    *,
    args: argparse.Namespace,
    samples_sha: str,
    kb_manifest_sha: str | None,
    lock_sha: str,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": _now_iso(),
        "api_url": args.api_url,
        "backend": args.backend,
        "samples_path": args.samples,
        "samples_sha256": samples_sha,
        "knowledge_base_manifest_path": args.kb_manifest,
        "knowledge_base_manifest_sha256": kb_manifest_sha,
        "lock_file": args.lock_file,
        "lock_sha256": lock_sha or None,
        "python_version": sys.version,
        "dependencies": _collect_dependency_versions(),
        "git": _collect_git_info(),
        "environment": _expected_environment(),
        "readiness": readiness,
    }


def create_lock(args: argparse.Namespace) -> int:
    lock_path = Path(args.output)
    if lock_path.exists() and not args.overwrite:
        print(f"Refusing to overwrite existing lock file: {lock_path}")
        print("Use --overwrite to replace it.")
        return 2

    data = _build_lock_data(args)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Saved lock file: {lock_path}")
    print(f"  samples_sha256: {data['samples']['sha256']}")
    if data["knowledge_base_manifest"]:
        print("  kb_manifest_sha256: " f"{data['knowledge_base_manifest']['sha256']}")
    return 0


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
    lock_file: str | None = None,
    lock_sha256: str | None = None,
    runtime_manifest_path: str | None = None,
) -> dict[str, Any]:
    metric_runs: dict[str, list[float]] = defaultdict(list)
    response_time_runs: list[float] = []
    fallback_metrics_used = any(
        bool((result.get("metrics") or {}).get("_fallback_metrics"))
        for result in run_results
    )

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
        "lock_file": lock_file,
        "lock_sha256": lock_sha256,
        "runtime_manifest_path": runtime_manifest_path,
        "samples_count": samples_count,
        "repeats": len(run_results),
        "run_outputs": run_output_paths,
        "fallback_metrics_used": fallback_metrics_used,
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
    from app.scripts.run_ragas_evaluation import run_evaluation

    args = _resolve_run_args_from_lock(args)
    os.environ["API_BASE_URL"] = args.api_url

    samples_sha, kb_manifest_sha, lock_sha = _validate_lock_hashes(args)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metric_names = _parse_csv_arg(args.metrics)
    bypass_hooks = _parse_csv_arg(args.bypass_hooks)
    fail_phrases = _parse_csv_arg(args.probe_fail_phrases) or DEFAULT_PROBE_FAIL_PHRASES
    run_output_paths: list[str] = []
    run_results: list[dict[str, Any]] = []

    print(
        "Waiting for API readiness "
        f"(timeout={args.readiness_timeout}s, poll={args.readiness_poll}s)..."
    )
    readiness = await _wait_for_api_readiness(
        api_url=args.api_url,
        timeout_seconds=args.readiness_timeout,
        poll_seconds=args.readiness_poll,
        probe_question=args.probe_question,
        fail_phrases=fail_phrases,
        bypass_hooks=bypass_hooks,
    )
    print(
        f"API ready after {readiness['elapsed_seconds']:.1f}s "
        f"({readiness['attempts']} attempts)"
    )

    runtime_manifest = _runtime_manifest(
        args=args,
        samples_sha=samples_sha,
        kb_manifest_sha=kb_manifest_sha,
        lock_sha=lock_sha,
        readiness=readiness,
    )
    runtime_manifest_path = output_dir / f"{args.run_name}.runtime.json"
    with open(runtime_manifest_path, "w") as f:
        json.dump(runtime_manifest, f, indent=2)

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
        lock_file=args.lock_file,
        lock_sha256=lock_sha or None,
        runtime_manifest_path=str(runtime_manifest_path),
    )

    summary_path = output_dir / f"{run_name}.summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Saved runtime manifest: {runtime_manifest_path}")
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


def _metric_mean(
    summary: dict[str, Any], metric_names: tuple[str, ...]
) -> tuple[str, float] | None:
    metrics = summary.get("metrics") or {}
    for metric_name in metric_names:
        row = metrics.get(metric_name)
        if not isinstance(row, dict):
            continue
        mean_value = row.get("mean")
        if _is_number(mean_value):
            return metric_name, float(mean_value)
    return None


def gate_benchmark_summary(args: argparse.Namespace) -> int:
    with open(args.summary) as f:
        summary = json.load(f)

    failures: list[str] = []
    if summary.get("fallback_metrics_used"):
        failures.append(
            "ragas: fallback metrics were used; install/fix RAGAS before gating"
        )

    gates = {
        "context_recall": (
            ("recall_at_k", "retrieval_recall_at_k", "context_recall"),
            args.min_recall_at_k,
        ),
        "mrr": (
            ("mrr", "mean_reciprocal_rank"),
            args.min_mrr,
        ),
        "faithfulness": (("faithfulness",), args.min_faithfulness),
        "answer_relevancy": (
            ("answer_relevancy", "answer_relevance"),
            args.min_answer_relevancy,
        ),
    }
    observed: dict[str, dict[str, float | str]] = {}

    for gate_name, (metric_names, floor) in gates.items():
        metric = _metric_mean(summary, metric_names)
        if metric is None:
            failures.append(
                f"{gate_name}: none of {', '.join(metric_names)} present in summary"
            )
            continue
        metric_name, value = metric
        observed[gate_name] = {"metric": metric_name, "value": value, "floor": floor}
        if value < floor:
            failures.append(
                f"{gate_name}: {metric_name}={value:.4f} below floor {floor:.4f}"
            )

    print("Benchmark gate metrics:")
    for gate_name, row in observed.items():
        print(
            f"  {gate_name}: {row['metric']}={float(row['value']):.4f} "
            f"(floor {float(row['floor']):.4f})"
        )

    if failures:
        print("Benchmark gate failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("Benchmark gate passed")
    return 0


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
        "--samples", type=str, default=None, help="Path to sample JSON"
    )
    run_parser.add_argument("--backend", type=str, default=None, choices=["qdrant"])
    run_parser.add_argument(
        "--run-name", type=str, default=None, help="Name prefix for output files"
    )
    run_parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR)
    run_parser.add_argument("--repeats", type=int, default=3)
    run_parser.add_argument("--sleep-between", type=float, default=1.0)
    run_parser.add_argument("--max-samples", type=int, default=None)
    run_parser.add_argument("--simple", action="store_true")
    run_parser.add_argument("--metrics", type=str, default=None)
    run_parser.add_argument("--bypass-hooks", type=str, default="escalation")
    run_parser.add_argument("--api-url", type=str, default=DEFAULT_API_BASE_URL)
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
    run_parser.add_argument(
        "--lock-file",
        type=str,
        default=None,
        help="Optional lock JSON generated by the `lock` command. If set, run config is loaded from lock and hashes/env are validated.",
    )
    run_parser.add_argument(
        "--readiness-timeout",
        type=int,
        default=DEFAULT_READINESS_TIMEOUT,
        help=f"Seconds to wait for API readiness before run (default: {DEFAULT_READINESS_TIMEOUT})",
    )
    run_parser.add_argument(
        "--readiness-poll",
        type=int,
        default=DEFAULT_READINESS_POLL,
        help=f"Seconds between readiness probe attempts (default: {DEFAULT_READINESS_POLL})",
    )
    run_parser.add_argument(
        "--probe-question",
        type=str,
        default=DEFAULT_PROBE_QUESTION,
        help="Probe question used to validate API readiness.",
    )
    run_parser.add_argument(
        "--probe-fail-phrases",
        type=str,
        default=",".join(DEFAULT_PROBE_FAIL_PHRASES),
        help="Comma-separated phrases indicating non-ready probe answers.",
    )

    lock_parser = subparsers.add_parser(
        "lock", help="Create strict benchmark lockfile for reproducible future runs"
    )
    lock_parser.add_argument("--output", type=str, required=True)
    lock_parser.add_argument("--samples", type=str, required=True)
    lock_parser.add_argument("--backend", type=str, required=True, choices=["qdrant"])
    lock_parser.add_argument("--run-name", type=str, required=True)
    lock_parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR)
    lock_parser.add_argument("--repeats", type=int, default=3)
    lock_parser.add_argument("--sleep-between", type=float, default=1.0)
    lock_parser.add_argument("--max-samples", type=int, default=None)
    lock_parser.add_argument("--simple", action="store_true")
    lock_parser.add_argument("--metrics", type=str, default=None)
    lock_parser.add_argument("--bypass-hooks", type=str, default="escalation")
    lock_parser.add_argument("--api-url", type=str, default=DEFAULT_API_BASE_URL)
    lock_parser.add_argument("--kb-manifest", type=str, default=None)
    lock_parser.add_argument("--ragas-timeout", type=int, default=None)
    lock_parser.add_argument("--ragas-max-retries", type=int, default=None)
    lock_parser.add_argument("--ragas-max-wait", type=int, default=None)
    lock_parser.add_argument("--ragas-max-workers", type=int, default=None)
    lock_parser.add_argument("--ragas-batch-size", type=int, default=None)
    lock_parser.add_argument(
        "--readiness-timeout",
        type=int,
        default=DEFAULT_READINESS_TIMEOUT,
    )
    lock_parser.add_argument(
        "--readiness-poll",
        type=int,
        default=DEFAULT_READINESS_POLL,
    )
    lock_parser.add_argument(
        "--probe-question",
        type=str,
        default=DEFAULT_PROBE_QUESTION,
    )
    lock_parser.add_argument(
        "--probe-fail-phrases",
        type=str,
        default=",".join(DEFAULT_PROBE_FAIL_PHRASES),
    )
    lock_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite --output if it already exists.",
    )

    compare_parser = subparsers.add_parser(
        "compare", help="Compare two benchmark summaries"
    )
    compare_parser.add_argument("--baseline", type=str, required=True)
    compare_parser.add_argument("--candidate", type=str, required=True)
    compare_parser.add_argument("--output", type=str, required=True)
    compare_parser.add_argument("--max-overall-drop", type=float, default=0.02)
    compare_parser.add_argument("--max-slice-drop", type=float, default=0.05)
    compare_parser.add_argument("--max-latency-increase-pct", type=float, default=20.0)

    gate_parser = subparsers.add_parser(
        "gate", help="Fail when a benchmark summary is below quality floors"
    )
    gate_parser.add_argument("--summary", type=str, required=True)
    gate_parser.add_argument("--min-recall-at-k", type=float, default=0.38)
    gate_parser.add_argument("--min-mrr", type=float, default=0.60)
    gate_parser.add_argument("--min-faithfulness", type=float, default=0.40)
    gate_parser.add_argument("--min-answer-relevancy", type=float, default=0.55)

    behavior_parser = subparsers.add_parser(
        "behavior",
        help="Offline score and gate reviewed, precomputed staff/AI answer rows",
    )
    behavior_parser.add_argument("--input", type=str, required=True)
    behavior_parser.add_argument("--output", type=str, default=DEFAULT_BEHAVIOR_OUTPUT)
    for threshold_name, default in DEFAULT_BEHAVIOR_THRESHOLDS.items():
        behavior_parser.add_argument(
            f"--{threshold_name.replace('_', '-')}", type=float, default=default
        )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Keep API URL handling aligned with run_ragas_evaluation.
    if hasattr(args, "api_url"):
        os.environ["API_BASE_URL"] = args.api_url

    try:
        if args.command == "run":
            return asyncio.run(run_benchmark(args))
        if args.command == "lock":
            return create_lock(args)
        if args.command == "compare":
            return compare_benchmarks(args)
        if args.command == "gate":
            return gate_benchmark_summary(args)
        if args.command == "behavior":
            return run_staff_alignment_behavior(args)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"Error: {e}")
        return 2

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
