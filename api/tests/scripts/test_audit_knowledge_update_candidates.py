import csv
import sys
from pathlib import Path

import pytest
from app.scripts import audit_knowledge_update_candidates as audit


def _raw_candidate(**overrides):
    values = {
        "id": 1,
        "source": "matrix",
        "source_event_id": "$event",
        "source_timestamp": "2026-06-17T10:00:00+00:00",
        "question_text": "Do buyers need reputation in Bisq Easy?",
        "staff_answer": "Buyers do not need reputation; sellers use reputation.",
    }
    values.update(overrides)
    return values


def _audit_row(**overrides):
    values = {
        "candidate_id": 1,
        "recommendation": "review_new_page",
        "routing": "FULL_REVIEW",
        "source": "matrix",
        "protocol": "bisq_easy",
        "category": "reputation",
        "proposal_kind": "create_new",
        "target_page_id": "bisq2-reputation-basics",
        "exact_cluster_size": 1,
        "topic_cluster_key": "bisq_easy_reputation_or_risk",
        "topic_cluster_size": 1,
        "blocking_failures": [],
        "warnings": [],
        "question": "What is Bisq Easy?",
        "answer": "Bisq Easy is peer-to-peer bitcoin trading.",
    }
    values.update(overrides)
    return values


def test_parse_args_requires_explicit_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["audit_knowledge_update_candidates.py"])

    with pytest.raises(SystemExit):
        audit._parse_args()


def test_parse_args_uses_private_random_output_dir_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export_path = tmp_path / "export.json"
    output_path = tmp_path / "private-output"
    monkeypatch.setattr(
        sys,
        "argv",
        ["audit_knowledge_update_candidates.py", "--export", str(export_path)],
    )
    monkeypatch.setattr(
        audit.tempfile,
        "mkdtemp",
        lambda prefix: str(output_path),
    )

    args = audit._parse_args()

    assert args.export == export_path
    assert args.output_dir == output_path


def test_candidate_from_dict_preserves_defaults_when_fields_are_absent() -> None:
    candidate = audit._candidate_from_dict(_raw_candidate())

    assert candidate.routing == "FULL_REVIEW"
    assert candidate.review_status == "pending"
    assert candidate.is_calibration_sample is True
    assert candidate.has_correction is False


def test_candidate_from_dict_rejects_missing_required_fields() -> None:
    raw = _raw_candidate()
    raw.pop("staff_answer")

    with pytest.raises(ValueError, match="staff_answer"):
        audit._candidate_from_dict(raw)


def test_write_csv_escapes_spreadsheet_formula_cells(tmp_path: Path) -> None:
    output = tmp_path / "audit.csv"

    audit._write_csv(
        output,
        [
            _audit_row(
                blocking_failures=["@risky"],
                warnings=["-warning"],
                question='=IMPORTXML("https://example.invalid")',
                answer="+cmd",
            )
        ],
    )

    with output.open(encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))

    assert row["blocking_failures"] == "'@risky"
    assert row["warnings"] == "'-warning"
    assert row["question"].startswith("'=")
    assert row["answer"] == "'+cmd"


def test_write_exported_pages_materializes_safe_filenames(tmp_path: Path) -> None:
    audit._write_exported_pages(
        {
            "llm_wiki_pages": [
                {
                    "name": "../bisq2-reputation-basics.md",
                    "markdown": "# Bisq Easy reputation",
                }
            ]
        },
        tmp_path,
    )

    page = tmp_path / "knowledge" / "llm_wiki" / "pages" / "bisq2-reputation-basics.md"
    assert page.read_text(encoding="utf-8") == "# Bisq Easy reputation\n"


def test_write_exported_pages_fails_on_invalid_page_rows(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid LLM Wiki page export rows"):
        audit._write_exported_pages(
            {
                "llm_wiki_pages": [
                    {"name": "bisq2-reputation-basics.md", "markdown": "# Valid"},
                    {"name": "", "markdown": "# Missing filename"},
                ]
            },
            tmp_path,
        )


def test_audit_existing_proposals_uses_edited_candidate_text() -> None:
    rows = audit._audit_existing_proposals(
        {
            "all_candidates": [
                {
                    "id": 7,
                    "question_text": "unrelated raw question",
                    "staff_answer": "unrelated raw answer",
                    "edited_question_text": "Bisq Easy reputation basics",
                    "edited_staff_answer": "Seller reputation basics in Bisq Easy",
                }
            ],
            "knowledge_update_proposals": [
                {
                    "id": 99,
                    "candidate_id": 7,
                    "status": "pending",
                    "target_page_id": "bisq2-reputation-basics",
                    "target_page_title": "Bisq Easy reputation basics",
                }
            ],
        }
    )

    assert rows[0]["flags"] == []


def test_render_markdown_uses_singular_candidate_for_rework_group() -> None:
    rework_triage = {
        "groups": [
            {
                "size": 1,
                "action": "manual_decision",
                "target_page_id": "all-trading",
                "issue_codes": ["missing_protocol"],
                "examples": [{"question": "How do I open mediation?"}],
            }
        ]
    }
    summary = {
        "candidate_count": 1,
        "duplicate_clusters": 0,
        "topic_clusters": 0,
        "admin_clusters": 0,
        "page_count": 0,
        "proposal_count": 0,
        "recommendations": {},
        "rework_triage": {
            "total_blocked": 1,
            "group_count": 1,
            "action_counts": {"manual_decision": 1},
        },
        "blocking_failures": {},
        "duplicate_page_titles": [],
        "page_flags": {},
        "proposal_flags": {},
    }

    markdown = audit._render_markdown(summary, [], [], [], rework_triage)

    assert "- 1 candidate `manual_decision`" in markdown
    assert "1 candidates `manual_decision`" not in markdown
