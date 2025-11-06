"""
Tests for FAQ rebuild optimization - verifying that vector store rebuilds
are only triggered when verified FAQs are modified or deleted.

This module tests the performance optimization that prevents unnecessary
vector store rebuilds when unverified FAQs (which are not in the vector
store) are updated or deleted.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from app.models.faq import FAQItem
from app.services.faq_service import FAQService


@pytest.fixture(scope="function")
def faq_service_with_mock_callback(test_settings):
    """Create FAQ service with mocked update callback to track rebuild triggers.

    Function scope ensures each test gets fresh FAQ data.
    """
    # Use the FAQ file path from settings to ensure consistency
    faq_file = Path(test_settings.FAQ_FILE_PATH)

    # Ensure parent directory exists
    faq_file.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing FAQ file to ensure clean slate
    # This prevents interference from previous tests in the session
    if faq_file.exists():
        faq_file.unlink()

    # Write test FAQs to the file BEFORE creating FAQService
    # This ensures the file exists and is populated when FAQRepository initializes
    test_faqs = [
        {
            "question": "Verified FAQ 1",
            "answer": "Answer 1",
            "category": "General",
            "source": "Manual",
            "verified": True,
        },
        {
            "question": "Unverified FAQ 1",
            "answer": "Answer 2",
            "category": "General",
            "source": "Manual",
            "verified": False,
        },
        {
            "question": "Verified FAQ 2",
            "answer": "Answer 3",
            "category": "Trading",
            "source": "Manual",
            "verified": True,
        },
        {
            "question": "Unverified FAQ 2",
            "answer": "Answer 4",
            "category": "Trading",
            "source": "Manual",
            "verified": False,
        },
    ]

    with open(faq_file, "w", encoding="utf-8") as f:
        for faq in test_faqs:
            f.write(json.dumps(faq) + "\n")

    # Now create FAQ service (repository will find the populated file)
    faq_service = FAQService(settings=test_settings)

    # Create a mock callback to track when rebuilds are triggered
    mock_callback = Mock()
    faq_service.register_update_callback(mock_callback)

    return faq_service, mock_callback


@pytest.mark.unit
def test_delete_verified_faq_triggers_rebuild(faq_service_with_mock_callback):
    """Test that deleting a verified FAQ triggers vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get a verified FAQ
    all_faqs = faq_service.get_all_faqs()
    assert len(all_faqs) > 0, "No FAQs loaded - fixture setup failed"

    verified_faq = next((faq for faq in all_faqs if faq.verified), None)
    assert verified_faq is not None, "No verified FAQ found in test data"

    # Delete it
    result = faq_service.delete_faq(verified_faq.id)

    # Verify deletion succeeded and rebuild was triggered
    assert result is True
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_delete_unverified_faq_skips_rebuild(faq_service_with_mock_callback):
    """Test that deleting an unverified FAQ does NOT trigger vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get an unverified FAQ
    all_faqs = faq_service.get_all_faqs()
    unverified_faq = next((faq for faq in all_faqs if not faq.verified), None)
    assert unverified_faq is not None, "No unverified FAQ found in test data"

    # Delete it
    result = faq_service.delete_faq(unverified_faq.id)

    # Verify deletion succeeded but rebuild was NOT triggered
    assert result is True
    mock_callback.assert_not_called()


@pytest.mark.unit
def test_update_verified_faq_triggers_rebuild(faq_service_with_mock_callback):
    """Test that updating a verified FAQ triggers vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get a verified FAQ
    all_faqs = faq_service.get_all_faqs()
    verified_faq = next((faq for faq in all_faqs if faq.verified), None)
    assert verified_faq is not None, "No verified FAQ found in test data"

    # Update it
    updated_data = FAQItem(
        question=verified_faq.question,
        answer="Updated answer",
        category=verified_faq.category,
        source=verified_faq.source,
        verified=True,
    )
    result = faq_service.update_faq(verified_faq.id, updated_data)

    # Verify update succeeded and rebuild was triggered
    assert result is not None
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_update_unverified_faq_skips_rebuild(faq_service_with_mock_callback):
    """Test that updating an unverified FAQ does NOT trigger vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get an unverified FAQ
    all_faqs = faq_service.get_all_faqs()
    unverified_faq = next((faq for faq in all_faqs if not faq.verified), None)
    assert unverified_faq is not None, "No unverified FAQ found in test data"

    # Update it
    updated_data = FAQItem(
        question=unverified_faq.question,
        answer="Updated answer",
        category=unverified_faq.category,
        source=unverified_faq.source,
        verified=False,
    )
    result = faq_service.update_faq(unverified_faq.id, updated_data)

    # Verify update succeeded but rebuild was NOT triggered
    assert result is not None
    mock_callback.assert_not_called()


@pytest.mark.unit
def test_verify_unverified_faq_triggers_rebuild(faq_service_with_mock_callback):
    """Test that verifying an unverified FAQ triggers vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get an unverified FAQ
    all_faqs = faq_service.get_all_faqs()
    unverified_faq = next((faq for faq in all_faqs if not faq.verified), None)
    assert unverified_faq is not None, "No unverified FAQ found in test data"

    # Verify it (change verified=False to verified=True)
    updated_data = FAQItem(
        question=unverified_faq.question,
        answer=unverified_faq.answer,
        category=unverified_faq.category,
        source=unverified_faq.source,
        verified=True,  # This is the key change
    )
    result = faq_service.update_faq(unverified_faq.id, updated_data)

    # Verify update succeeded and rebuild was triggered
    assert result is not None
    assert result.verified is True
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_bulk_delete_only_verified_triggers_rebuild(faq_service_with_mock_callback):
    """Test that bulk deleting only verified FAQs triggers rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get all verified FAQs
    all_faqs = faq_service.get_all_faqs()
    verified_faq_ids = [faq.id for faq in all_faqs if faq.verified]

    # Delete them all
    success, failed, failed_ids = faq_service.bulk_delete_faqs(verified_faq_ids)

    # Verify deletions succeeded and rebuild was triggered once
    assert success == len(verified_faq_ids)
    assert failed == 0
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_bulk_delete_only_unverified_skips_rebuild(faq_service_with_mock_callback):
    """Test that bulk deleting only unverified FAQs does NOT trigger rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get all unverified FAQs
    all_faqs = faq_service.get_all_faqs()
    unverified_faq_ids = [faq.id for faq in all_faqs if not faq.verified]

    # Delete them all
    success, failed, failed_ids = faq_service.bulk_delete_faqs(unverified_faq_ids)

    # Verify deletions succeeded but rebuild was NOT triggered
    assert success == len(unverified_faq_ids)
    assert failed == 0
    mock_callback.assert_not_called()


@pytest.mark.unit
def test_bulk_delete_mixed_triggers_rebuild_once(faq_service_with_mock_callback):
    """Test that bulk deleting mixed FAQs triggers rebuild only once."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get all FAQs (both verified and unverified)
    all_faqs = faq_service.get_all_faqs()
    all_faq_ids = [faq.id for faq in all_faqs]

    # Delete them all
    success, failed, failed_ids = faq_service.bulk_delete_faqs(all_faq_ids)

    # Verify deletions succeeded and rebuild was triggered exactly once
    assert success == len(all_faq_ids)
    assert failed == 0
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_add_faq_always_triggers_rebuild(faq_service_with_mock_callback):
    """Test that adding a new FAQ always triggers rebuild (verified or not)."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Add a new unverified FAQ
    new_faq = FAQItem(
        question="New FAQ",
        answer="New answer",
        category="General",
        source="Manual",
        verified=False,
    )
    result = faq_service.add_faq(new_faq)

    # Verify addition succeeded and rebuild was triggered
    assert result is not None
    mock_callback.assert_called_once()

    # Reset mock and add a verified FAQ
    mock_callback.reset_mock()
    new_verified_faq = FAQItem(
        question="New Verified FAQ",
        answer="New verified answer",
        category="General",
        source="Manual",
        verified=True,
    )
    result = faq_service.add_faq(new_verified_faq)

    # Verify addition succeeded and rebuild was triggered
    assert result is not None
    mock_callback.assert_called_once()
