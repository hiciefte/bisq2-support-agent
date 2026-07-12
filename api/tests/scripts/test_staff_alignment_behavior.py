"""Offline staff-alignment behavior scoring and CLI gate tests."""

import json
import sys
from pathlib import Path

import pytest
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from app.scripts.retrieval_benchmark_harness import (
    BEHAVIOR_DIVERGENCE_KEYS,
    BEHAVIOR_SCHEMA_VERSION,
    build_staff_alignment_behavior_summary,
    main,
)
from app.scripts.run_ragas_evaluation import _load_evaluation_samples

FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "staff_alignment_behavior.json"
)


def _behavior_row(
    *,
    case_id: str,
    ground_truth: str,
    answer: str,
    scam_warning_warranted: bool,
    staff_linked_wiki: bool = False,
    troubleshooting: bool = False,
    diagnostic_expected: bool = False,
    remedy_terms: list[str] | None = None,
    source_urls: list[str] | None = None,
    reviewed: bool = True,
) -> dict:
    return {
        "case_id": case_id,
        "question": "Sanitized fixture question?",
        "ground_truth": ground_truth,
        "answer": answer,
        "source_urls": source_urls or [],
        "metadata": {
            "behavior_labels": {
                "reviewed": reviewed,
                "scam_warning_warranted": scam_warning_warranted,
                "staff_linked_wiki": staff_linked_wiki,
                "troubleshooting": troubleshooting,
                "diagnostic_expected": diagnostic_expected,
                "remedy_terms": remedy_terms or [],
            }
        },
    }


def _failing_rows() -> list[dict]:
    return [
        _behavior_row(
            case_id="missing-required-behaviors",
            ground_truth=(
                "Use an SPV resync and follow https://bisq.wiki/Resyncing_SPV_file."
            ),
            answer="Hi. Restart.",
            scam_warning_warranted=True,
            staff_linked_wiki=True,
            troubleshooting=True,
            diagnostic_expected=True,
            remedy_terms=["SPV resync"],
        ),
        _behavior_row(
            case_id="unwarranted-warning",
            ground_truth="Wait.",
            answer=SAFETY_REFLEX_WARNING,
            scam_warning_warranted=False,
        ),
    ]


def test_reviewed_fixture_passes_and_report_omits_raw_text() -> None:
    rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture_json = json.dumps(rows).lower()
    assert all(
        forbidden not in fixture_json
        for forbidden in ("sender", "event_id", "room_id", "user_id")
    )

    summary = build_staff_alignment_behavior_summary(rows)

    assert summary["schema_version"] == BEHAVIOR_SCHEMA_VERSION
    assert summary["samples_count"] == len(rows)
    assert summary["gate"]["passed"] is True
    assert summary["divergence_counts"] == {key: 0 for key in BEHAVIOR_DIVERGENCE_KEYS}
    assert summary["metrics"]["scam_warning_precision"] == 1.0
    assert summary["metrics"]["scam_warning_recall"] == 1.0
    assert summary["metrics"]["wiki_link_recall"] == 1.0
    assert summary["metrics"]["diagnostic_question_rate"] == 1.0
    assert summary["metrics"]["remedy_term_overlap"] == 1.0
    assert all(
        key not in sample
        for sample in summary["per_sample"]
        for key in ("question", "ground_truth", "staff_answer", "answer")
    )


def test_divergence_counts_are_stable_allowlisted_integers() -> None:
    summary = build_staff_alignment_behavior_summary(_failing_rows())

    assert summary["gate"]["passed"] is False
    assert summary["divergence_counts"] == {
        "answer_too_long": 1,
        "leading_greeting": 1,
        "scam_warning_missing": 1,
        "scam_warning_false_positive": 1,
        "wiki_link_missing": 1,
        "diagnostic_question_missing": 1,
        "remedy_term_missing": 1,
    }
    assert all(
        isinstance(value, int) and value >= 0
        for value in summary["divergence_counts"].values()
    )


def test_unreviewed_behavior_labels_are_rejected() -> None:
    row = _behavior_row(
        case_id="not-reviewed",
        ground_truth="Direct answer.",
        answer="Direct answer.",
        scam_warning_warranted=False,
        reviewed=False,
    )

    with pytest.raises(ValueError, match="reviewed=true"):
        build_staff_alignment_behavior_summary([row])


@pytest.mark.parametrize(
    "url",
    [
        "https://bisq.wiki.example/guide",
        "https://bisq.wiki@evil.example/guide",
        "https://bisq.wiki:443.evil.example/guide",
        "https://bisq.wiki%2eevil.example/guide",
        "http://bisq.wiki/guide",
    ],
)
def test_wiki_metric_rejects_lookalike_or_insecure_url(url: str) -> None:
    row = _behavior_row(
        case_id="lookalike-wiki",
        ground_truth="Use the reviewed wiki link.",
        answer=f"Use {url}.",
        scam_warning_warranted=False,
        staff_linked_wiki=True,
    )

    summary = build_staff_alignment_behavior_summary([row])

    assert summary["per_sample"][0]["wiki_link_present"] is False
    assert summary["divergence_counts"]["wiki_link_missing"] == 1


def test_wiki_metric_accepts_structured_generated_source_url() -> None:
    row = _behavior_row(
        case_id="structured-wiki-source",
        ground_truth="Use the reviewed wiki link.",
        answer="Follow the reviewed SPV resync steps.",
        source_urls=["https://bisq.wiki/Resyncing_SPV_file"],
        scam_warning_warranted=False,
        staff_linked_wiki=True,
    )

    summary = build_staff_alignment_behavior_summary([row])

    assert summary["per_sample"][0]["wiki_link_present"] is True
    assert summary["divergence_counts"]["wiki_link_missing"] == 0


def test_bare_scam_label_does_not_satisfy_static_warning_metric() -> None:
    row = _behavior_row(
        case_id="bare-scam-label",
        ground_truth=SAFETY_REFLEX_WARNING,
        answer="That sounds like a scam.",
        scam_warning_warranted=True,
    )

    summary = build_staff_alignment_behavior_summary([row])

    assert summary["per_sample"][0]["scam_warning_present"] is False
    assert summary["divergence_counts"]["scam_warning_missing"] == 1


def test_mutated_scam_warning_does_not_satisfy_unchanged_warning_metric() -> None:
    row = _behavior_row(
        case_id="mutated-static-warning",
        ground_truth=SAFETY_REFLEX_WARNING,
        answer=SAFETY_REFLEX_WARNING.replace("messages;", "messages."),
        scam_warning_warranted=True,
    )

    summary = build_staff_alignment_behavior_summary([row])

    assert summary["per_sample"][0]["scam_warning_present"] is False
    assert summary["divergence_counts"]["scam_warning_missing"] == 1


def test_diagnostic_metric_requires_exactly_one_question_when_reviewed() -> None:
    row = _behavior_row(
        case_id="too-many-diagnostics",
        ground_truth="Which version are you using?",
        answer="Which version? What trade state?",
        scam_warning_warranted=False,
        troubleshooting=True,
        diagnostic_expected=True,
    )

    summary = build_staff_alignment_behavior_summary([row])

    assert summary["per_sample"][0]["diagnostic_question_present"] is False
    assert summary["divergence_counts"]["diagnostic_question_missing"] == 1


def test_direct_remedy_troubleshooting_does_not_require_question() -> None:
    row = _behavior_row(
        case_id="direct-remedy",
        ground_truth="Run an SPV resync.",
        answer="Run an SPV resync.",
        scam_warning_warranted=False,
        troubleshooting=True,
        diagnostic_expected=False,
        remedy_terms=["SPV resync"],
    )

    summary = build_staff_alignment_behavior_summary([row])

    assert summary["divergence_counts"]["diagnostic_question_missing"] == 0


def test_one_long_answer_cannot_be_hidden_by_short_samples() -> None:
    rows = [
        _behavior_row(
            case_id="long-outlier",
            ground_truth="Short staff answer.",
            answer=" ".join(["excess"] * 12),
            scam_warning_warranted=False,
        ),
        _behavior_row(
            case_id="short-one",
            ground_truth="One two three four five six seven eight nine ten.",
            answer="Short.",
            scam_warning_warranted=False,
        ),
        _behavior_row(
            case_id="short-two",
            ground_truth="One two three four five six seven eight nine ten.",
            answer="Short.",
            scam_warning_warranted=False,
        ),
    ]

    summary = build_staff_alignment_behavior_summary(rows)

    assert summary["metrics"]["answer_length_ratio"] < 1.5
    assert summary["divergence_counts"]["answer_too_long"] == 1
    assert any(
        failure.startswith("answer_length_ratio:")
        for failure in summary["gate"]["failures"]
    )


def test_behavior_cli_writes_summary_and_returns_zero(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / "behavior-summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "retrieval_benchmark_harness",
            "behavior",
            "--input",
            str(FIXTURE_PATH),
            "--output",
            str(output_path),
        ],
    )

    assert main() == 0
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["gate"]["passed"] is True


def test_behavior_cli_accepts_existing_evaluation_result(tmp_path, monkeypatch) -> None:
    rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    input_path = tmp_path / "evaluation-result.json"
    output_path = tmp_path / "behavior-summary.json"
    input_path.write_text(json.dumps({"individual_results": rows}), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "retrieval_benchmark_harness",
            "behavior",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    assert main() == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["gate"]["passed"]


def test_reviewed_stage1_artifact_has_explicit_fresh_generation_handoff(
    tmp_path,
) -> None:
    rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    input_path = tmp_path / "reviewed-behavior.json"
    input_path.write_text(
        json.dumps({"schema_version": 1, "individual_results": rows}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        _load_evaluation_samples(str(input_path))

    loaded = _load_evaluation_samples(str(input_path), allow_behavior_review=True)

    assert [row["case_id"] for row in loaded] == [row["case_id"] for row in rows]
    assert all(row["metadata"]["behavior_labels"]["reviewed"] for row in loaded)


def test_fresh_generation_handoff_rejects_unreviewed_stage1_row(tmp_path) -> None:
    rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    rows[0]["metadata"]["behavior_labels"]["reviewed"] = False
    input_path = tmp_path / "pending-behavior.json"
    input_path.write_text(
        json.dumps({"schema_version": 1, "individual_results": rows}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        _load_evaluation_samples(str(input_path), allow_behavior_review=True)


def test_behavior_cli_writes_summary_and_returns_one_on_gate_failure(
    tmp_path, monkeypatch
) -> None:
    input_path = tmp_path / "failing-rows.json"
    output_path = tmp_path / "behavior-summary.json"
    input_path.write_text(json.dumps(_failing_rows()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "retrieval_benchmark_harness",
            "behavior",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    assert main() == 1
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["gate"]["passed"] is False
    assert saved["divergence_counts"]["scam_warning_missing"] == 1
