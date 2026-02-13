"""Tests for DuplicateFAQError handling in training approve endpoint.

TDD RED: The approve endpoint should return 409 (not 500) when a duplicate
FAQ is detected. The bug was that the exception handler used attribute access
(faq.id) on dict objects returned by search_faq_similarity().
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.security import verify_admin_access
from app.routes.admin.training import router
from app.services.training.unified_pipeline_service import DuplicateFAQError
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestDuplicateFAQErrorHandling:
    """Test that DuplicateFAQError produces 409 with correct detail dict."""

    def _build_similar_faqs_dicts(self):
        """Build similar_faqs as returned by search_faq_similarity() — plain dicts."""
        return [
            {
                "id": 42,
                "question": "How do I start a trade?",
                "answer": "Click Take Offer in the offerbook.",
                "similarity": 0.92,
                "category": "trading",
                "protocol": "bisq_easy",
            }
        ]

    def test_duplicate_faq_error_has_dict_similar_faqs(self):
        """DuplicateFAQError.similar_faqs should be plain dicts (from search_faq_similarity)."""
        faqs = self._build_similar_faqs_dicts()
        err = DuplicateFAQError(
            "Cannot approve: 1 similar FAQ(s) already exist",
            similar_faqs=faqs,
            candidate_id=5,
        )
        assert err.similar_faqs is faqs
        assert isinstance(err.similar_faqs[0], dict)

    def test_exception_handler_builds_detail_from_dicts(self):
        """The exception handler must use dict access, not attribute access.

        This is the core regression test: the handler at training.py:522
        used faq.id (attribute) instead of faq["id"] (dict access), causing
        AttributeError -> unhandled 500 instead of the intended 409.
        """
        faqs = self._build_similar_faqs_dicts()
        err = DuplicateFAQError(
            "Cannot approve: 1 similar FAQ(s) already exist",
            similar_faqs=faqs,
            candidate_id=5,
        )

        # Reproduce what the exception handler should do (dict access)
        detail_faqs = [
            {
                "id": faq["id"],
                "question": faq["question"],
                "answer": (
                    faq["answer"][:200] + "..."
                    if len(faq["answer"]) > 200
                    else faq["answer"]
                ),
                "similarity": faq["similarity"],
                "category": faq.get("category"),
            }
            for faq in err.similar_faqs
        ]

        assert len(detail_faqs) == 1
        assert detail_faqs[0]["id"] == 42
        assert detail_faqs[0]["similarity"] == 0.92

    def test_attribute_access_on_dict_fails(self):
        """Confirm that attribute access on dict raises AttributeError.

        This proves the bug: faq.id on a dict raises AttributeError.
        """
        faq = self._build_similar_faqs_dicts()[0]
        with pytest.raises(AttributeError):
            _ = faq.id  # noqa: B018 — intentionally accessing attribute on dict

    def test_approve_endpoint_returns_409_on_duplicate(self):
        """Full integration: approve endpoint returns 409 when duplicate detected."""
        similar_faqs = self._build_similar_faqs_dicts()

        mock_candidate = MagicMock()
        mock_candidate.generation_confidence = 0.85
        mock_candidate.source = "bisq2"
        mock_candidate.final_score = 0.88
        mock_candidate.routing = "auto_approved"

        mock_service = MagicMock()
        mock_service.repository.get_by_id = MagicMock(return_value=mock_candidate)
        mock_service.approve_candidate = AsyncMock(
            side_effect=DuplicateFAQError(
                "Cannot approve: 1 similar FAQ(s) already exist",
                similar_faqs=similar_faqs,
                candidate_id=5,
            )
        )

        app = FastAPI()

        # Override auth dependency (router-level)
        app.dependency_overrides[verify_admin_access] = lambda: None

        # Mount the router
        app.include_router(router)

        # Set mock service on app state so get_pipeline_service() finds it
        app.state.unified_pipeline_service = mock_service

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/admin/training/candidates/5/approve",
            json={"reviewer": "test_admin"},
        )

        # Should be 409 Conflict, NOT 500
        assert response.status_code == 409, (
            f"Expected 409 Conflict for duplicate FAQ, got {response.status_code}: "
            f"{response.text}"
        )
        data = response.json()
        assert data["detail"]["error"] == "duplicate_faq"
        assert len(data["detail"]["similar_faqs"]) == 1
        assert data["detail"]["similar_faqs"][0]["id"] == 42
