import json
from pathlib import Path

import pytest
from app.services.rag.code_evidence import (
    CodeEvidenceLoader,
    CodeEvidenceRecord,
    StaffCodeEvidenceRetriever,
)
from app.services.rag.source_refs import parse_code_source_ref


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows),
        encoding="utf-8",
    )


def _valid_record(**overrides) -> dict:
    record = {
        "id": "bisq2:abc123:BisqEasyTradeAmountLimits:getMaxUsdTradeAmount",
        "type": "code_fact",
        "repo": "bisq2",
        "commit": "abc123",
        "path": "bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java",
        "line_start": 77,
        "line_end": 84,
        "symbol": "BisqEasyTradeAmountLimits.getMaxUsdTradeAmount",
        "protocol": "bisq_easy",
        "audience": "staff_only",
        "freshness_class": "main_branch",
        "risk_level": "medium",
        "claim": "Bisq Easy caps reputation-based trade amount at 600 USD.",
        "support_use": "Use for staff investigation of trade-size limits.",
        "source_refs": [
            "code:bisq2@abc123:bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java:77-84"
        ],
    }
    record.update(overrides)
    return record


def test_loader_validates_and_redacts_sensitive_values(tmp_path: Path) -> None:
    source = tmp_path / "code_knowledge" / "code_evidence.jsonl"
    _write_jsonl(
        source,
        [
            _valid_record(
                claim="API password default is hunter2 for local testing.",
                support_use="Do not share token sk-test-123 with users.",
            )
        ],
    )

    records = CodeEvidenceLoader(source).load()

    assert len(records) == 1
    assert records[0].claim == "API [REDACTED] default is [REDACTED] for local testing."
    assert records[0].support_use == "Do not share [REDACTED] with users."


def test_loader_redacts_compact_api_key_and_wallet_seed_text(tmp_path: Path) -> None:
    source = tmp_path / "code_knowledge" / "code_evidence.jsonl"
    _write_jsonl(
        source,
        [
            _valid_record(
                claim="api_key=abcd1234 and wallet_seed:abandon should stay private.",
                support_use="The password:swordfish value is fake test data.",
            )
        ],
    )

    records = CodeEvidenceLoader(source).load()

    assert records[0].claim == (
        "[REDACTED]=[REDACTED] and [REDACTED]:[REDACTED] " "should stay private."
    )
    assert records[0].support_use == (
        "The [REDACTED]:[REDACTED] value is fake test data."
    )


def test_loader_rejects_boolean_line_numbers(tmp_path: Path) -> None:
    source = tmp_path / "code_knowledge" / "code_evidence.jsonl"
    _write_jsonl(source, [_valid_record(line_start=True)])

    with pytest.raises(ValueError, match="line_start"):
        CodeEvidenceLoader(source).load()


def test_loader_rejects_invalid_audience(tmp_path: Path) -> None:
    source = tmp_path / "code_knowledge" / "code_evidence.jsonl"
    _write_jsonl(source, [_valid_record(audience="public")])

    with pytest.raises(ValueError, match="audience"):
        CodeEvidenceLoader(source).load()


def test_loader_skips_blank_lines_and_missing_files(tmp_path: Path) -> None:
    missing = tmp_path / "code_knowledge" / "code_evidence.jsonl"
    assert CodeEvidenceLoader(missing).load() == []

    existing = tmp_path / "code_knowledge" / "code_evidence.jsonl"
    existing.parent.mkdir(parents=True)
    existing.write_text("\n\n", encoding="utf-8")
    assert CodeEvidenceLoader(existing).load() == []


def test_record_to_retrieved_document_keeps_staff_only_metadata() -> None:
    record = CodeEvidenceRecord.from_dict(_valid_record())

    doc = record.to_retrieved_document(score=0.75)

    assert doc.content.startswith("Claim: Bisq Easy caps")
    assert doc.metadata["type"] == "code_fact"
    assert doc.metadata["audience"] == "staff_only"
    assert doc.metadata["source_refs"] == record.source_refs
    assert doc.score == 0.75


def test_staff_retriever_filters_by_protocol_and_public_status(tmp_path: Path) -> None:
    source = tmp_path / "code_knowledge" / "code_evidence.jsonl"
    _write_jsonl(
        source,
        [
            _valid_record(
                id="staff-match",
                protocol="bisq_easy",
                audience="staff_only",
                claim="Sell offers require reputation evidence.",
            ),
            _valid_record(
                id="public-reviewed",
                protocol="bisq_easy",
                audience="public_reviewed",
                claim="Reviewed public guidance should not be in staff-only raw evidence.",
                public_guidance="Reviewed public guidance should not be retrieved by the staff-only raw evidence retriever.",
            ),
            _valid_record(
                id="wrong-protocol",
                protocol="multisig_v1",
                audience="staff_only",
                claim="Multisig deposits use a different flow.",
            ),
        ],
    )

    retriever = StaffCodeEvidenceRetriever(CodeEvidenceLoader(source))

    docs = retriever.retrieve(
        "Why can I not create a sell offer?", protocol="bisq_easy"
    )

    assert [doc.id for doc in docs] == ["staff-match"]
    assert docs[0].metadata["audience"] == "staff_only"
    assert "public" not in docs[0].content.lower()


def test_staff_retriever_scores_query_terms(tmp_path: Path) -> None:
    source = tmp_path / "code_knowledge" / "code_evidence.jsonl"
    _write_jsonl(
        source,
        [
            _valid_record(
                id="reputation",
                claim="Sell offer creation depends on reputation score.",
            ),
            _valid_record(
                id="startup",
                claim="Startup can wait for seed node bootstrap readiness.",
            ),
        ],
    )

    retriever = StaffCodeEvidenceRetriever(CodeEvidenceLoader(source))

    docs = retriever.retrieve("sell offer reputation limit", k=2)

    assert [doc.id for doc in docs] == ["reputation"]
    assert docs[0].score > 0


def test_code_source_refs_reject_branch_or_tag_like_revisions() -> None:
    assert (
        parse_code_source_ref(
            "code:bisq2@abc123:bisq-easy/src/main/java/Foo.java:10-12"
        )
        is not None
    )
    assert (
        parse_code_source_ref(
            "code:bisq2@release-2.1:bisq-easy/src/main/java/Foo.java:10-12"
        )
        is None
    )
    assert (
        parse_code_source_ref(
            "code:bisq2@develop:bisq-easy/src/main/java/Foo.java:10-12"
        )
        is None
    )
