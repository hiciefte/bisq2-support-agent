from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from app.channels.constants import DIRECT_DELIVERY_ACTIONS
from app.scripts import release_ai_quality_report as report_module
from app.scripts.release_ai_quality_report import (
    build_infrastructure_failure_report,
    ensure_safe_report,
    report_passed,
    validate_release_ai_quality_report,
    write_json_atomic,
)

COMMIT = "a" * 40
MODEL_SHA256 = "b" * 64


def _failure_report() -> dict:
    return build_infrastructure_failure_report(COMMIT, MODEL_SHA256)


def _per_sample_failure_report() -> dict:
    report = _failure_report()
    report["coverage"]["samples"] = 1
    report["per_sample"] = [
        {
            "case_id": "safe-case",
            "answer_length_ratio": 0.0,
            "leading_greeting_avoided": True,
            "scam_warning_warranted": False,
            "scam_warning_present": False,
            "staff_linked_wiki": False,
            "wiki_link_present": False,
            "troubleshooting": False,
            "diagnostic_expected": False,
            "diagnostic_question_present": False,
            "remedy_terms_expected": 0,
            "remedy_terms_matched": 0,
            "remedy_term_overlap": 1.0,
            "divergences": [],
            "case_kind": "standard",
            "response_contract": {
                "request_error": None,
                "requires_human": False,
                "routing_action": "",
                "mcp_tools": [],
                "evaluation_source": "unavailable",
            },
            "gate": {
                "passed": False,
                "failures": ["empty_answer", "review_draft_unavailable"],
            },
        }
    ]
    report["gate"]["failures"] = ["per_sample_gate_failed"]
    return report


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_nested_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_nested_keys(child) for child in value))
    return set()


def test_infrastructure_failure_report_uses_strict_sanitized_schema() -> None:
    report = _failure_report()

    assert validate_release_ai_quality_report(report) is report
    assert _nested_keys(report).isdisjoint(
        {
            "question",
            "answer",
            "ground_truth",
            "source_urls",
            "result",
            "tool_result",
            "model_id",
        }
    )
    assert report["generation"]["model_sha256"] == MODEL_SHA256


@pytest.mark.parametrize("location", ("top", "generation", "gate"))
def test_report_validator_rejects_unknown_or_raw_fields(location: str) -> None:
    report = _failure_report()
    target = report if location == "top" else report[location]
    target["generated_answer"] = "must not be archived"

    with pytest.raises(ValueError, match="unsupported schema"):
        validate_release_ai_quality_report(report)


@pytest.mark.parametrize("schema_version", (True, 1.0, "1"))
def test_report_validator_requires_integer_schema_version(
    schema_version: object,
) -> None:
    report = _failure_report()
    report["schema_version"] = schema_version

    with pytest.raises(ValueError, match="schema version"):
        validate_release_ai_quality_report(report)


def test_report_validator_rejects_raw_model_id() -> None:
    report = _failure_report()
    report["generation"]["model_id"] = "openai:release-model"

    with pytest.raises(ValueError, match="unsupported schema"):
        validate_release_ai_quality_report(report)


def test_report_validator_rejects_unknown_evaluation_source() -> None:
    report = _per_sample_failure_report()
    report["per_sample"][0]["response_contract"]["evaluation_source"] = "raw_answer"

    with pytest.raises(ValueError, match="evaluation source"):
        validate_release_ai_quality_report(report)


def test_report_evaluation_actions_match_delivery_actions() -> None:
    assert report_module.DIRECT_EVALUATION_ROUTING_ACTIONS == DIRECT_DELIVERY_ACTIONS


@pytest.mark.parametrize(
    ("request_error", "requires_human", "routing_action", "evaluation_source"),
    (
        ("http_error", False, "auto_send", "delivered"),
        (None, False, "auto_send", "review_draft"),
        (None, True, "needs_human", "delivered"),
        (None, False, "unknown", "delivered"),
    ),
)
def test_report_validator_rejects_inconsistent_evaluation_source(
    request_error: str | None,
    requires_human: bool,
    routing_action: str,
    evaluation_source: str,
) -> None:
    report = _per_sample_failure_report()
    response = report["per_sample"][0]["response_contract"]
    response.update(
        {
            "request_error": request_error,
            "requires_human": requires_human,
            "routing_action": routing_action,
            "evaluation_source": evaluation_source,
        }
    )

    with pytest.raises(ValueError, match="evaluation source"):
        validate_release_ai_quality_report(report)


def test_report_validator_requires_explicit_unavailable_review_failure() -> None:
    report = _per_sample_failure_report()
    report["per_sample"][0]["gate"]["failures"] = ["empty_answer"]

    with pytest.raises(ValueError, match="fail explicitly"):
        validate_release_ai_quality_report(report)


@pytest.mark.parametrize("request_error", (None, "http_error"))
def test_report_validator_requires_request_error_failure_consistency(
    request_error: str | None,
) -> None:
    report = _per_sample_failure_report()
    report["per_sample"][0]["response_contract"]["request_error"] = request_error
    if request_error is None:
        report["per_sample"][0]["gate"]["failures"].append("request_failed")

    with pytest.raises(ValueError, match="request error must match"):
        validate_release_ai_quality_report(report)


@pytest.mark.parametrize(
    ("location", "unsafe_failure"),
    (
        ("aggregate", "credential=must-not-archive"),
        ("aggregate", "https://service.invalid/private"),
        ("per_sample", "answer: arbitrary generated response"),
    ),
)
def test_report_validator_rejects_failure_text_outside_closed_allowlists(
    location: str, unsafe_failure: str
) -> None:
    report = (
        _per_sample_failure_report() if location == "per_sample" else _failure_report()
    )
    target = (
        report["per_sample"][0]["gate"] if location == "per_sample" else report["gate"]
    )
    target["failures"] = [unsafe_failure]

    with pytest.raises(ValueError, match="unsupported failure code"):
        validate_release_ai_quality_report(report)


def test_report_validator_requires_expected_commit_and_model_bindings() -> None:
    report = _failure_report()

    assert (
        validate_release_ai_quality_report(
            report,
            expected_commit=COMMIT,
            expected_model_sha256=MODEL_SHA256,
        )
        is report
    )
    with pytest.raises(ValueError, match="commit does not match"):
        validate_release_ai_quality_report(
            report,
            expected_commit="c" * 40,
            expected_model_sha256=MODEL_SHA256,
        )
    with pytest.raises(ValueError, match="model digest does not match"):
        validate_release_ai_quality_report(
            report,
            expected_commit=COMMIT,
            expected_model_sha256="d" * 64,
        )


@pytest.mark.parametrize(
    ("threshold", "value"),
    (
        ("max_answer_length_ratio", 0),
        ("max_answer_length_ratio", -0.1),
        ("min_greeting_avoidance_rate", -0.01),
        ("min_scam_warning_precision", 1.01),
        ("min_scam_warning_recall", -0.01),
        ("min_wiki_link_recall", 1.01),
        ("min_diagnostic_question_rate", -0.01),
        ("min_remedy_term_overlap", 1.01),
    ),
)
def test_report_validator_rejects_out_of_range_aggregate_thresholds(
    threshold: str, value: float
) -> None:
    report = _failure_report()
    report["gate"]["aggregate_thresholds"][threshold] = value

    with pytest.raises(ValueError, match=r"positive|safe range"):
        validate_release_ai_quality_report(report)


def test_ensure_safe_report_replaces_untrusted_content_and_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps({"answer": "sensitive generated content"}), encoding="utf-8"
    )

    expected_commit = "c" * 40
    expected_model_sha = "d" * 64
    assert ensure_safe_report(path, expected_commit, expected_model_sha) is False

    saved = json.loads(path.read_text(encoding="utf-8"))
    validate_release_ai_quality_report(
        saved,
        expected_commit=expected_commit,
        expected_model_sha256=expected_model_sha,
    )
    assert saved["gate"]["passed"] is False
    assert saved["generation"]["model_sha256"] == expected_model_sha
    assert "sensitive generated content" not in path.read_text(encoding="utf-8")


def test_ensure_replaces_valid_report_with_mismatched_release_binding(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_failure_report()), encoding="utf-8")
    expected_commit = "c" * 40
    expected_model_sha = "d" * 64

    assert ensure_safe_report(path, expected_commit, expected_model_sha) is False

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["release_commit"] == expected_commit
    assert saved["generation"]["model_sha256"] == expected_model_sha
    assert saved["gate"]["failures"] == ["quality_report_unavailable_or_invalid"]


def test_report_pass_is_checked_separately_from_artifact_safety(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_failure_report()), encoding="utf-8")

    assert ensure_safe_report(path, COMMIT, MODEL_SHA256) is True
    assert report_passed(path, COMMIT, MODEL_SHA256) is False


def test_atomic_report_write_preserves_previous_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "report.json"
    path.write_text("previous\n", encoding="utf-8")
    report = copy.deepcopy(_failure_report())

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(report_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_json_atomic(path, report)

    assert path.read_text(encoding="utf-8") == "previous\n"
    assert list(tmp_path.glob(".report.json.*.tmp")) == []


def test_ensure_replacement_failure_leaves_unsafe_prior_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "report.json"
    unsafe_prior = '{"answer":"unsafe prior artifact"}\n'
    path.write_text(unsafe_prior, encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(report_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        ensure_safe_report(path, COMMIT, MODEL_SHA256)

    assert path.read_text(encoding="utf-8") == unsafe_prior
    assert list(tmp_path.glob(".report.json.*.tmp")) == []
