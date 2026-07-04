"""Tests for direct FAQ lookup by ID.

Covers the repository-level ``get_faq_by_id`` and the call sites that
previously performed full-table scans via ``get_all_faqs()``:
FAQService.update_faq, FAQService.delete_faq, and the public FAQ
detail path.
"""

from unittest.mock import MagicMock

import pytest
from app.models.faq import FAQIdentifiedItem, FAQItem
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite
from app.services.faq_service import FAQService
from app.services.public_faq_service import PublicFAQService


@pytest.fixture
def repository(tmp_path):
    """Isolated SQLite repository."""
    repo = FAQRepositorySQLite(str(tmp_path / "faqs.db"))
    yield repo
    repo.close()


@pytest.fixture
def service(test_settings, tmp_path):
    """FAQService backed by an isolated SQLite database."""
    test_settings.DATA_DIR = str(tmp_path)
    faq_service = FAQService(settings=test_settings)
    yield faq_service
    faq_service.repository.close()


def _faq_item(question="How do I trade Bitcoin?", **overrides):
    data = {
        "question": question,
        "answer": "Use the trade view to create offers",
        "category": "Trading",
        "source": "Manual",
        "verified": True,
        "protocol": "bisq_easy",
    }
    data.update(overrides)
    return FAQItem(**data)


def _forbid_full_scan(monkeypatch, repository):
    """Make any full-table scan via get_all_faqs fail loudly."""

    def _fail(*args, **kwargs):
        raise AssertionError("get_all_faqs() must not be used for single-ID lookups")

    monkeypatch.setattr(repository, "get_all_faqs", _fail)


class TestRepositoryGetFaqById:
    """Repository-level single-ID lookup."""

    def test_returns_faq_when_found(self, repository):
        added = repository.add_faq(_faq_item())

        found = repository.get_faq_by_id(added.id)

        assert found is not None
        assert found.id == added.id
        assert found.question == added.question
        assert found.answer == added.answer
        assert found.verified is True

    def test_accepts_integer_ids(self, repository):
        added = repository.add_faq(_faq_item())

        found = repository.get_faq_by_id(int(added.id))

        assert found is not None
        assert found.id == added.id

    def test_returns_none_when_not_found(self, repository):
        assert repository.get_faq_by_id("999999") is None

    def test_returns_none_for_non_numeric_id(self, repository):
        assert repository.get_faq_by_id("not-a-number") is None


class TestFAQServiceGetFaqById:
    """Service-level accessor delegating to the repository."""

    def test_returns_faq_when_found(self, service):
        added = service.repository.add_faq(_faq_item())

        found = service.get_faq_by_id(added.id)

        assert found is not None
        assert found.id == added.id

    def test_returns_none_when_not_found(self, service):
        assert service.get_faq_by_id("999999") is None


class TestNoFullTableScans:
    """update/delete/public-detail must use the direct ID lookup."""

    def test_update_faq_does_not_scan_all_faqs(self, service, monkeypatch):
        added = service.repository.add_faq(_faq_item())
        _forbid_full_scan(monkeypatch, service.repository)

        updated = service.update_faq(added.id, _faq_item(answer="Updated answer"))

        assert updated is not None
        assert updated.answer == "Updated answer"

    def test_delete_faq_does_not_scan_all_faqs(self, service, monkeypatch):
        added = service.repository.add_faq(_faq_item())
        _forbid_full_scan(monkeypatch, service.repository)

        assert service.delete_faq(added.id) is True
        assert service.get_faq_by_id(added.id) is None


class TestPublicDetailPath:
    """Public FAQ detail lookups must use the direct ID lookup."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        PublicFAQService._instance = None
        yield
        PublicFAQService._instance = None

    def _identified_faq(self, faq_id="7", verified=True):
        return FAQIdentifiedItem(
            id=faq_id,
            question="How do I trade Bitcoin?",
            answer="Use the trade view to create offers",
            category="Trading",
            source="Manual",
            verified=verified,
            protocol="bisq_easy",
        )

    def _public_service(self, faq):
        mock_faq_service = MagicMock()
        mock_faq_service.get_all_faqs.return_value = [faq]  # slug init only
        mock_faq_service.get_faq_by_id.side_effect = lambda faq_id: (
            faq if faq_id == faq.id else None
        )
        public_service = PublicFAQService(faq_service=mock_faq_service)
        # After slug initialization, any full listing is a scan regression
        mock_faq_service.get_all_faqs.side_effect = AssertionError(
            "get_all_faqs() must not be used for single-ID lookups"
        )
        return public_service

    def test_get_faq_by_id_uses_direct_lookup(self):
        faq = self._identified_faq()
        public_service = self._public_service(faq)

        result = public_service.get_faq_by_id(faq.id)

        assert result is not None
        assert result["question"] == faq.question

    def test_unverified_faqs_stay_hidden_with_direct_lookup(self):
        faq = self._identified_faq(verified=False)
        public_service = self._public_service(faq)

        assert public_service.get_faq_by_id(faq.id) is None
