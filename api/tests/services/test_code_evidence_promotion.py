import json
from pathlib import Path

from app.core.config import Settings
from app.services.knowledge_updates.code_evidence_promotion import (
    CodeEvidencePromotionService,
)
from app.services.rag.code_evidence import CodeEvidenceRecord
from app.services.rag.llm_wiki_loader import LLMWikiLoader
from app.services.training.unified_repository import UnifiedFAQCandidateRepository


def _record(**overrides) -> CodeEvidenceRecord:
    data = {
        "id": "bisq2:abc123:HTTPException.404:42",
        "type": "code_fact",
        "repo": "bisq2",
        "commit": "abc123",
        "path": "api/src/main/java/bisq/api/OfferResource.java",
        "line_start": 42,
        "line_end": 44,
        "symbol": "OfferResource.HTTPException.404",
        "protocol": "bisq_easy",
        "audience": "public_review_candidate",
        "freshness_class": "release_bound",
        "risk_level": "medium",
        "claim": "OfferResource can return user-visible error detail: Offer not found.",
        "support_use": "Use when users report that an offer disappeared before they could take it.",
        "public_guidance": (
            "If a user sees Offer not found, explain that the offer may already "
            "have been taken or removed. Ask them to refresh the offer list and retry."
        ),
        "applies_to_versions": ["2.1.0"],
        "source_refs": [
            "code:bisq2@abc123:api/src/main/java/bisq/api/OfferResource.java:42-44"
        ],
    }
    data.update(overrides)
    return CodeEvidenceRecord.from_dict(data)


def test_code_evidence_promotion_creates_review_queue_candidate_and_proposal(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    service = CodeEvidencePromotionService(
        settings=settings,
        repository=repository,
    )
    record = _record()

    result = service.create_or_get_proposal(
        record=record,
        question="The app says Offer not found. What should I do?",
    )

    candidate = result.candidate
    proposal = result.proposal
    assert candidate.source == "code_evidence"
    assert candidate.routing == "FULL_REVIEW"
    assert candidate.protocol == "bisq_easy"
    assert candidate.staff_answer == record.public_guidance
    assert candidate.original_staff_answer == record.claim
    assert proposal.candidate_id == candidate.id
    assert proposal.proposal_kind == "create_new"
    assert proposal.source_refs == record.source_refs
    assert "Offer not found" in proposal.preview_markdown
    assert record.source_refs[0] in proposal.preview_markdown
    assert any(
        check["code"] == "code_source_refs" and check["status"] == "pass"
        for check in proposal.checks
    )
    sources = json.loads(candidate.generated_answer_sources or "[]")
    assert sources[0]["type"] == "code"
    assert sources[0]["source_ref"] == record.source_refs[0]
    assert sources[0]["freshness_class"] == "release_bound"
    assert sources[0]["applies_to_versions"] == ["2.1.0"]


def test_code_evidence_promotion_is_idempotent_by_source_ref(tmp_path: Path) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    service = CodeEvidencePromotionService(
        settings=settings,
        repository=repository,
    )
    record = _record()

    first = service.create_or_get_proposal(record=record)
    second = service.create_or_get_proposal(record=record)

    assert second.candidate.id == first.candidate.id
    assert second.proposal.id == first.proposal.id


def test_approved_code_evidence_proposal_enters_public_rag_via_llm_wiki(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    service = CodeEvidencePromotionService(
        settings=settings,
        repository=repository,
    )
    result = service.create_or_get_proposal(record=_record())

    approved = service.knowledge_update_service.approve(
        candidate=result.candidate,
        reviewer="support-admin",
    )
    docs = LLMWikiLoader().load_documents(Path(settings.LLM_WIKI_DIR_PATH))

    assert approved.status == "approved"
    assert len(docs) == 1
    assert "Offer not found" in docs[0].page_content
    assert "refresh the offer list" in docs[0].page_content
    assert "OfferResource.HTTPException.404" not in docs[0].page_content
    assert _record().source_refs[0] in docs[0].metadata["source_refs"]


def test_code_evidence_promotion_rejects_record_without_public_guidance(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    service = CodeEvidencePromotionService(
        settings=settings,
        repository=repository,
    )
    record = _record(audience="staff_only", public_guidance=None)

    try:
        service.create_or_get_proposal(record=record)
    except ValueError as exc:
        assert "public guidance" in str(exc)
    else:
        raise AssertionError("promotion without public guidance should fail")


def test_code_evidence_promotion_rejects_mismatched_source_ref(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    service = CodeEvidencePromotionService(
        settings=settings,
        repository=repository,
    )
    record = _record(
        source_refs=[
            "code:bisq2@abc123:api/src/main/java/bisq/api/OtherResource.java:42-44"
        ],
    )

    try:
        service.create_or_get_proposal(record=record)
    except ValueError as exc:
        assert "match the structured code evidence" in str(exc)
    else:
        raise AssertionError("promotion with mismatched source ref should fail")


def test_code_evidence_promotion_rejects_any_mismatched_source_ref(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    service = CodeEvidencePromotionService(
        settings=settings,
        repository=repository,
    )
    record = _record(
        source_refs=[
            "code:bisq2@abc123:api/src/main/java/bisq/api/OfferResource.java:42-44",
            "code:bisq2@abc123:api/src/main/java/bisq/api/OtherResource.java:42-44",
        ],
    )

    try:
        service.create_or_get_proposal(record=record)
    except ValueError as exc:
        assert "match the structured code evidence" in str(exc)
    else:
        raise AssertionError("promotion with any mismatched source ref should fail")
