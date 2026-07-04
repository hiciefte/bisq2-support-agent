"""Tests for approve_candidate atomicity and idempotency guards.

Review finding F2: approve_candidate performed a non-atomic cross-database
write (faqs.db then unified_training.db) with no review-status guard, so a
crash between the two writes left a verified FAQ plus a still-pending
candidate, and re-approval created a duplicate FAQ. These tests cover:
- rejection of non-pending candidates before any FAQ write
- guarded approval via approve_pending with compensation on a lost race
- idempotent recovery via the candidate's own validated faq_id link
- an explicit conflict (instead of a silent relink) when an unlinked FAQ
  merely shares the exact question text, since FAQs carry no candidate
  provenance and could belong to an unrelated candidate
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.training.unified_pipeline_service import (
    CandidateReviewConflictError,
    UnifiedPipelineService,
)

QUESTION = "How do I start trading on Bisq Easy?"
ANSWER = "Open the trade wizard from the Trade tab."


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "unified_training.db")


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.OPENAI_API_KEY = "test-key"
    settings.BISQ_STAFF_USERS = ["support-staff"]
    return settings


@pytest.fixture
def mock_rag_service() -> MagicMock:
    mock = MagicMock()
    mock.search_faq_similarity = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_faq_service() -> MagicMock:
    mock = MagicMock()
    mock.add_faq = MagicMock(return_value=MagicMock(id="faq_new_1"))
    mock.get_faq_by_id = MagicMock(return_value=None)
    mock.get_filtered_faqs = MagicMock(return_value=[])
    mock.delete_faq = MagicMock(return_value=True)
    return mock


@pytest.fixture
def service(db_path, mock_settings, mock_rag_service, mock_faq_service):
    return UnifiedPipelineService(
        settings=mock_settings,
        rag_service=mock_rag_service,
        faq_service=mock_faq_service,
        db_path=db_path,
    )


@pytest.fixture
def pending_candidate(service):
    return service.repository.create(
        source="matrix",
        source_event_id="$atomicity_test:matrix.org",
        source_timestamp="2026-01-15T10:00:00Z",
        question_text=QUESTION,
        staff_answer=ANSWER,
        routing="FULL_REVIEW",
    )


class TestStatusGuard:
    @pytest.mark.asyncio
    async def test_pending_candidate_approves_once(
        self, service, pending_candidate, mock_faq_service
    ):
        faq_id = await service.approve_candidate(pending_candidate.id, reviewer="admin")

        assert faq_id == "faq_new_1"
        mock_faq_service.add_faq.assert_called_once()
        stored = service.repository.get_by_id(pending_candidate.id)
        assert stored.review_status == "approved"
        assert stored.faq_id == "faq_new_1"
        assert stored.reviewed_by == "admin"

    @pytest.mark.asyncio
    async def test_second_approve_raises_conflict_without_new_faq(
        self, service, pending_candidate, mock_faq_service
    ):
        await service.approve_candidate(pending_candidate.id, reviewer="admin")
        mock_faq_service.add_faq.reset_mock()

        with pytest.raises(CandidateReviewConflictError):
            await service.approve_candidate(pending_candidate.id, reviewer="admin2")

        mock_faq_service.add_faq.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejected_candidate_conflicts_before_any_faq_write(
        self, service, pending_candidate, mock_faq_service
    ):
        service.repository.reject(
            pending_candidate.id, reviewer="admin", reason="incorrect"
        )

        with pytest.raises(CandidateReviewConflictError):
            await service.approve_candidate(pending_candidate.id, reviewer="admin")

        mock_faq_service.add_faq.assert_not_called()


class TestLostRaceCompensation:
    @pytest.mark.asyncio
    async def test_zero_rows_updated_deletes_created_faq_and_raises(
        self, service, pending_candidate, mock_faq_service, monkeypatch
    ):
        # Simulate a concurrent reviewer winning the race between the status
        # check and the guarded update.
        monkeypatch.setattr(
            service.repository, "approve_pending", lambda *a, **kw: False
        )

        with pytest.raises(CandidateReviewConflictError):
            await service.approve_candidate(pending_candidate.id, reviewer="admin")

        mock_faq_service.add_faq.assert_called_once()
        mock_faq_service.delete_faq.assert_called_once_with("faq_new_1")

    @pytest.mark.asyncio
    async def test_recovered_faq_is_not_deleted_on_lost_race(
        self, service, pending_candidate, mock_faq_service, monkeypatch, db_path
    ):
        # A previous interrupted approval already created and linked the FAQ;
        # losing the race must not delete that pre-existing FAQ.
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE unified_faq_candidates SET faq_id = ? WHERE id = ?",
            ("faq_prev", pending_candidate.id),
        )
        conn.commit()
        conn.close()
        mock_faq_service.get_faq_by_id.return_value = SimpleNamespace(
            id="faq_prev", question=QUESTION, answer=ANSWER
        )
        monkeypatch.setattr(
            service.repository, "approve_pending", lambda *a, **kw: False
        )

        with pytest.raises(CandidateReviewConflictError):
            await service.approve_candidate(pending_candidate.id, reviewer="admin")

        mock_faq_service.add_faq.assert_not_called()
        mock_faq_service.delete_faq.assert_not_called()


class TestCrashRecoveryIdempotency:
    @pytest.mark.asyncio
    async def test_exact_question_match_raises_conflict_instead_of_silent_relink(
        self, service, pending_candidate, mock_faq_service
    ):
        # A FAQ with identical question text but no candidate link may belong
        # to an UNRELATED candidate (FAQs carry no provenance). Approval must
        # surface a conflict for explicit admin resolution, not silently
        # relink and skip duplicate detection.
        mock_faq_service.get_filtered_faqs.return_value = [
            SimpleNamespace(id="faq_prev", question=QUESTION, answer=ANSWER)
        ]

        with pytest.raises(CandidateReviewConflictError) as exc_info:
            await service.approve_candidate(pending_candidate.id, reviewer="admin")

        assert exc_info.value.faq_id == "faq_prev"
        assert "faq_prev" in str(exc_info.value)
        mock_faq_service.add_faq.assert_not_called()
        stored = service.repository.get_by_id(pending_candidate.id)
        assert stored.review_status == "pending"

    @pytest.mark.asyncio
    async def test_exact_question_match_with_force_proceeds_to_creation(
        self, service, pending_candidate, mock_faq_service
    ):
        mock_faq_service.get_filtered_faqs.return_value = [
            SimpleNamespace(id="faq_prev", question=QUESTION, answer=ANSWER)
        ]

        faq_id = await service.approve_candidate(
            pending_candidate.id, reviewer="admin", force=True
        )

        assert faq_id == "faq_new_1"
        mock_faq_service.add_faq.assert_called_once()
        stored = service.repository.get_by_id(pending_candidate.id)
        assert stored.review_status == "approved"
        assert stored.faq_id == "faq_new_1"

    @pytest.mark.asyncio
    async def test_reuses_candidate_faq_id_link_when_faq_exists(
        self, service, pending_candidate, mock_faq_service, db_path
    ):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE unified_faq_candidates SET faq_id = ? WHERE id = ?",
            ("faq_linked", pending_candidate.id),
        )
        conn.commit()
        conn.close()
        mock_faq_service.get_faq_by_id.return_value = SimpleNamespace(
            id="faq_linked", question=QUESTION, answer=ANSWER
        )

        faq_id = await service.approve_candidate(pending_candidate.id, reviewer="admin")

        assert faq_id == "faq_linked"
        mock_faq_service.add_faq.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_faq_id_link_falls_back_to_creation(
        self, service, pending_candidate, mock_faq_service, db_path
    ):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE unified_faq_candidates SET faq_id = ? WHERE id = ?",
            ("faq_deleted", pending_candidate.id),
        )
        conn.commit()
        conn.close()
        mock_faq_service.get_faq_by_id.return_value = None

        faq_id = await service.approve_candidate(pending_candidate.id, reviewer="admin")

        assert faq_id == "faq_new_1"
        mock_faq_service.add_faq.assert_called_once()

    @pytest.mark.asyncio
    async def test_recovery_lookup_failure_does_not_block_approval(
        self, service, pending_candidate, mock_faq_service
    ):
        mock_faq_service.get_filtered_faqs.side_effect = RuntimeError("db locked")

        faq_id = await service.approve_candidate(pending_candidate.id, reviewer="admin")

        assert faq_id == "faq_new_1"
        mock_faq_service.add_faq.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_question_text_is_not_recovered(
        self, service, pending_candidate, mock_faq_service
    ):
        mock_faq_service.get_filtered_faqs.return_value = [
            SimpleNamespace(
                id="faq_other",
                question="How do I start trading on Bisq 1?",
                answer=ANSWER,
            )
        ]

        faq_id = await service.approve_candidate(pending_candidate.id, reviewer="admin")

        assert faq_id == "faq_new_1"
        mock_faq_service.add_faq.assert_called_once()
